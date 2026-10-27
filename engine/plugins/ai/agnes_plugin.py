"""Agnes AI provider using its OpenAI-compatible Chat Completions API."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Dict, Optional

from core.config import settings
from plugins.ai.base import AIPlugin, AIProviderError, parse_json_response

logger = logging.getLogger(__name__)

_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504", "TIMEOUT", "TIMED OUT",
    "UNAVAILABLE", "CONNECTION ERROR", "CONNECTION RESET", "TEMPORARILY",
)


def _plain_answer_limit(json_schema: Optional[Dict]) -> int | None:
    """Return the safe length for a one-field chat answer schema."""
    if not isinstance(json_schema, dict):
        return None
    properties = json_schema.get("properties")
    if not isinstance(properties, dict) or set(properties) != {"answer"}:
        return None
    answer = properties.get("answer") or {}
    if answer.get("type") != "string":
        return None
    return min(int(answer.get("maxLength") or 16000), 16000)


def _unwrap_support_answer(text: str) -> str:
    """Remove complete or truncated ``{"answer": ...}`` wrappers from chat text."""
    answer = text.strip()
    for _ in range(2):
        try:
            wrapped = parse_json_response(answer)
        except AIProviderError:
            break
        inner = wrapped.get("answer") if isinstance(wrapped, dict) else None
        if not isinstance(inner, str) or not inner.strip() or inner.strip() == answer:
            break
        answer = inner.strip()

    # A response that hits the token ceiling can be missing only the closing
    # quote/object. Decode the already-complete JSON string payload and keep the
    # useful report instead of showing its transport wrapper in the UI.
    partial = re.match(
        r'^\s*(?:```(?:json)?\s*\n?)?\s*\{\s*"answer"\s*:\s*"',
        answer,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if partial:
        payload = answer[partial.end():]
        trailing_slashes = len(payload) - len(payload.rstrip("\\"))
        if trailing_slashes % 2:
            payload = payload[:-1]
        try:
            decoded = json.loads('"' + payload + '"')
        except json.JSONDecodeError:
            try:
                decoded = json.JSONDecoder(strict=False).decode('"' + payload + '"')
            except json.JSONDecodeError:
                decoded = None
        if isinstance(decoded, str) and decoded.strip():
            answer = decoded.strip()
    answer = re.sub(
        r"<(?:think|analysis|reasoning)\b[^>]*>.*?</(?:think|analysis|reasoning)\s*>",
        "",
        answer,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    return answer


def _is_transient_error(exc: Exception, openai_module) -> bool:
    """Classify retryable transport/provider errors without logging credentials."""
    transient_types = tuple(
        error_type for name in ("APIConnectionError", "APITimeoutError", "RateLimitError")
        if (error_type := getattr(openai_module, name, None)) is not None
    )
    if transient_types and isinstance(exc, transient_types):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
        return True
    return any(marker in str(exc).upper() for marker in _TRANSIENT_MARKERS)


class AgnesPlugin(AIPlugin):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self._api_key = settings.agnes_api_key if api_key is None else api_key
        self._model = model or settings.ai_model or "agnes-2.5-flash"
        self._base_url = base_url or settings.agnes_base_url

    @property
    def name(self) -> str:
        return "agnes"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        try:
            import openai
        except ImportError as exc:
            raise AIProviderError("openai package not installed. Run: pip install openai") from exc

        if not self._api_key:
            raise AIProviderError("[agnes] AGNES_API_KEY is not configured")
        try:
            client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
        except Exception as exc:
            raise AIProviderError(f"[agnes] Client init failed: {exc}") from exc

        schema_instruction = ""
        plain_answer_limit = _plain_answer_limit(json_schema)
        if plain_answer_limit:
            # The support assistant is a single Markdown string. Asking the model
            # to JSON-escape a long forensic memo wastes tokens and turns harmless
            # output truncation into an invalid response. Wrap it locally instead.
            schema_instruction = (
                "\n\nReturn only the final answer as plain Markdown, without a JSON wrapper "
                f"or markdown fence. Keep it under {plain_answer_limit - 256} characters "
                "and reserve space for a complete conclusion. Never output hidden reasoning, "
                "analysis/reasoning tags, think tags, or narration about calling tools. "
                "Write in Vietnamese only; English proper names and finance terms are allowed, "
                "but do not mix in Chinese or other languages."
            )
        elif json_schema:
            # Agnes documents OpenAI-compatible chat/tool calling, but not a
            # strict JSON-Schema response mode. Keep the portable contract in
            # the prompt, then validate the result with Pydantic in AIPlugin.
            schema_instruction = (
                "\n\nReturn only one valid JSON object matching this JSON Schema. "
                "Do not use markdown fences or commentary:\n"
                + json.dumps(json_schema, ensure_ascii=False)
            )
        kwargs: Dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt + schema_instruction}],
            "temperature": 0.3,
            # Detailed decision memos can exceed the old short-chat envelope.
            # This is a ceiling, not a requested minimum; simple answers remain short.
            "max_tokens": 5000,
        }
        if json_schema and plain_answer_limit is None:
            # Agnes' OpenAI-compatible endpoint supports JSON object mode. Without
            # it the model can wrap the requested object in a second JSON string or
            # a markdown fence, which makes an otherwise valid answer fail closed.
            kwargs["response_format"] = {"type": "json_object"}
        for attempt in range(3):
            try:
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                if plain_answer_limit:
                    answer = content.strip()
                    if not answer:
                        if attempt == 2:
                            raise AIProviderError("[agnes] Empty support response after 3 attempts")
                        time.sleep(2 ** attempt)
                        continue
                    answer = _unwrap_support_answer(answer)
                    if len(answer) > plain_answer_limit:
                        suffix = "\n\n_[Báo cáo đã được rút gọn theo giới hạn hiển thị.]_"
                        answer = answer[:plain_answer_limit - len(suffix)].rstrip() + suffix
                    return {"answer": answer}
                try:
                    return parse_json_response(content)
                except AIProviderError as exc:
                    # OpenAI-compatible providers occasionally return prose/fences
                    # despite the schema instruction. A fresh generation is safe and
                    # usually fixes it; never expose the raw response in the final error.
                    if attempt == 2:
                        raise AIProviderError(
                            "[agnes] Invalid structured response after 3 attempts"
                        ) from exc
                    logger.warning(
                        "[agnes] Invalid structured response; retrying (attempt %d/3)",
                        attempt + 1,
                    )
                    time.sleep(2 ** attempt)
                    continue
            except AIProviderError:
                raise
            except Exception as exc:
                transient = _is_transient_error(exc, openai)
                if attempt == 2 or not transient:
                    status_code = getattr(exc, "status_code", None)
                    suffix = f" (HTTP {status_code})" if status_code else ""
                    raise AIProviderError(
                        f"[agnes] API call failed: {type(exc).__name__}{suffix}"
                    ) from exc
                delay = 2 ** attempt
                logger.warning(
                    "[agnes] Transient %s; retrying in %ss (attempt %d/3)",
                    type(exc).__name__, delay, attempt + 1,
                )
                time.sleep(delay)
        raise AIProviderError("[agnes] API call failed without a response")
