"""
Market Bias Platform — Anthropic Claude Plugin (3C-R)
Uses Claude tool_use for native structured output via _call_model().
"""
import logging
from typing import Any, Dict, Optional

from core.config import settings
from plugins.ai.base import AIPlugin, AIProviderError, parse_json_response

logger = logging.getLogger(__name__)


class ClaudePlugin(AIPlugin):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.ai_model

    @property
    def name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        try:
            import anthropic
        except ImportError:
            raise AIProviderError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        try:
            client = anthropic.Anthropic(api_key=self._api_key)
        except Exception as exc:
            raise AIProviderError(f"[claude] Client init failed: {exc}") from exc

        if json_schema:
            # Use tool_use for native structured output — most reliable with Claude
            tool: Dict[str, Any] = {
                "name": "structured_response",
                "description": "Return the analysis as structured data.",
                "input_schema": json_schema,
            }
            try:
                response = client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=(
                        "You are an expert macro-quantitative analyst. "
                        "Always call the structured_response tool with your analysis."
                    ),
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "structured_response"},
                    messages=[{"role": "user", "content": prompt}],
                )
                # Extract tool_use block input
                for block in response.content:
                    if block.type == "tool_use" and block.name == "structured_response":
                        return block.input  # already a dict
                raise AIProviderError("[claude] No tool_use block in response")
            except AIProviderError:
                raise
            except Exception as exc:
                raise AIProviderError(f"[claude] API call (tool_use) failed: {exc}") from exc
        else:
            # Fallback: plain text with JSON parsing
            try:
                response = client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    temperature=0.3,
                    system=(
                        "You are an expert macro-quantitative analyst. "
                        "Always respond with valid JSON only, no markdown formatting."
                    ),
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text or ""
            except Exception as exc:
                raise AIProviderError(f"[claude] API call failed: {exc}") from exc

            return parse_json_response(text)
