"""
Market Bias Platform — Manus AI Plugin (3C-R)
Manus exposes an OpenAI-compatible endpoint.
Uses json_object mode (no JSON Schema support confirmed), fallback to parse_json_response.
"""
import logging
from typing import Dict, Optional

from core.config import settings
from plugins.ai.base import AIPlugin, AIProviderError, parse_json_response

logger = logging.getLogger(__name__)

_MANUS_BASE_URL = "https://api.manus.ai/v1"


class ManusPlugin(AIPlugin):
    @property
    def name(self) -> str:
        return "manus"

    @property
    def model_name(self) -> str:
        return settings.ai_model

    @property
    def is_configured(self) -> bool:
        return bool(getattr(settings, "manus_api_key", None))

    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        try:
            from openai import OpenAI
        except ImportError:
            raise AIProviderError(
                "openai package not installed. Run: pip install openai"
            )

        try:
            client = OpenAI(api_key=settings.manus_api_key, base_url=_MANUS_BASE_URL)
        except Exception as exc:
            raise AIProviderError(f"[manus] Client init failed: {exc}") from exc

        # Manus is OpenAI-compatible but JSON Schema mode support is uncertain;
        # use json_object mode which is broadly supported.
        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a quantitative market analyst. Output valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            content = response.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"[manus] API call failed: {exc}") from exc

        return parse_json_response(content)
