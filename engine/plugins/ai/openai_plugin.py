"""
Market Bias Platform — OpenAI Plugin (3C-R)
Uses OpenAI JSON Schema structured output natively via _call_model().
"""
import logging
from typing import Dict, Optional

from core.config import settings
from plugins.ai.base import AIPlugin, AIProviderError, parse_json_response

logger = logging.getLogger(__name__)


class OpenAIPlugin(AIPlugin):
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._base_url = base_url or getattr(settings, "openai_base_url", None) or None
        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.ai_model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        try:
            import openai
        except ImportError:
            raise AIProviderError("openai package not installed. Run: pip install openai")

        try:
            client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url or None)
        except Exception as exc:
            raise AIProviderError(f"[openai] Client init failed: {exc}") from exc

        model_lower = self._model.lower()
        is_reasoning = any(m in model_lower for m in ["o1", "o3", "o4"])
        is_qwen = "qwen" in model_lower

        kwargs: Dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }

        if not is_reasoning:
            kwargs["temperature"] = 0.3

        if is_qwen:
            # Qwen thinking models: enable thinking, skip response_format
            kwargs["extra_body"] = {"enable_thinking": True}
        elif not is_reasoning and json_schema:
            # Use full JSON Schema mode for reliable structured output
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "ai_response",
                    "schema": json_schema,
                    "strict": False,
                },
            }
        elif not is_reasoning:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"[openai] API call failed: {exc}") from exc

        return parse_json_response(content)
