"""
Market Bias Platform — Gemini Plugin (3C-R)
Uses Gemini response_schema for native structured output via _call_model().
"""
import logging
import time
from copy import deepcopy
from typing import Dict, Optional

from core.config import settings
from plugins.ai.base import AIPlugin, AIProviderError, parse_json_response

logger = logging.getLogger(__name__)

_TRANSIENT_GEMINI_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
)


def _is_transient_gemini_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return any(marker in message for marker in _TRANSIENT_GEMINI_MARKERS)


def _normalize_schema_for_gemini(json_schema: Dict) -> Dict:
    """Inline local refs and remove keywords unsupported by Gemini Developer API."""
    schema = deepcopy(json_schema)
    definitions = schema.get("$defs", {})

    def _walk(node):
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if ref and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            if name in definitions:
                return _walk(definitions[name])

        return {
            key: _walk(value)
            for key, value in node.items()
            if key not in {"$defs", "additionalProperties"}
        }

    return _walk(schema)


class GeminiPlugin(AIPlugin):
    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return settings.ai_model

    @property
    def is_configured(self) -> bool:
        return bool(getattr(settings, "gemini_api_key", None))

    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise AIProviderError(
                "google-genai package not installed. Run: pip install google-genai"
            )

        try:
            client = genai.Client(api_key=settings.gemini_api_key)
        except Exception as exc:
            raise AIProviderError(f"[gemini] Client init failed: {exc}") from exc

        # Build config — use response_schema for native structured output if available
        config_kwargs: Dict = {"temperature": 0.4}
        if json_schema:
            # Gemini supports response_schema for constrained JSON generation
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = _normalize_schema_for_gemini(json_schema)

        config = types.GenerateContentConfig(**config_kwargs)

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                text = response.text or ""
                break
            except Exception as exc:
                is_last_attempt = attempt == 2
                if is_last_attempt or not _is_transient_gemini_error(exc):
                    raise AIProviderError(f"[gemini] API call failed: {exc}") from exc
                delay_seconds = 2 ** attempt
                logger.warning(
                    "[gemini] Transient API error; retrying in %ss (%s/3): %s",
                    delay_seconds,
                    attempt + 1,
                    exc,
                )
                time.sleep(delay_seconds)

        return parse_json_response(text)
