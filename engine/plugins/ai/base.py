"""
Market Bias Platform — AI Plugin Base Class (3C-R Architecture)

Architecture:
  - AIPlugin.generate_structured(prompt, response_model) -> T  [concrete, in base]
      Calls _call_model(prompt, json_schema) -> dict, then validates with Pydantic.
  - AIPlugin._call_model(prompt, json_schema) -> dict  [abstract]
      Each provider implements this using its native structured-output API.
      Providers without native support parse JSON from raw text themselves.
  - generate_narrative() is a thin convenience wrapper → generate_structured().
  - On failure: raise AIProviderError (caller catches, renders st.error()).
"""
from __future__ import annotations

import abc
import json
import re
import logging
from typing import Any, Dict, List, Optional, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ScenarioResponse(BaseModel):
    """Typed forward scenario shared by single-asset narratives."""

    scenario: str
    probability: str
    description: str


class AIResponse(BaseModel):
    """Single-asset narrative response schema."""
    executive_summary: str
    macro_context: str
    quant_regime_analysis: str
    forward_scenarios: List[ScenarioResponse]
    contradictions: List[str]
    tail_risks: List[str]
    actionable_strategies: List[str]
    # Provider metadata is injected after validation; the model need not invent it.
    model_used: str = ""


# ── Error ─────────────────────────────────────────────────────────────────────

class AIProviderError(Exception):
    """Raised when an AI provider call fails. Caught by dashboard with st.error()."""
    pass


# ── Base Plugin ───────────────────────────────────────────────────────────────

class AIPlugin(abc.ABC):
    """Base class for AI provider plugins (3C-R architecture).

    Subclasses MUST implement:
        - name (property)
        - model_name (property)
        - is_configured (property)
        - _call_model(prompt, json_schema) -> dict

    Subclasses MAY override:
        - generate_structured() — for providers that want full control.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'openai', 'gemini', 'claude'."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """The specific model string used for API calls."""

    @property
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True iff the required API key / credentials are present."""

    # ── Core primitive (providers implement this) ─────────────────────────────

    @abc.abstractmethod
    def _call_model(self, prompt: str, json_schema: Optional[Dict] = None) -> Dict:
        """Call the underlying model and return a parsed dict.

        Args:
            prompt: The full text prompt.
            json_schema: Optional JSON Schema dict. Providers that support native
                structured output (OpenAI JSON Schema mode, Gemini response_schema,
                Claude tool_use) SHOULD use it for reliability. Providers that don't
                support it SHOULD ignore it and parse JSON from raw text.

        Returns:
            A dict matching the schema (or best effort).

        Raises:
            AIProviderError: on any API / parsing failure.
        """

    # ── Typed generic (concrete in base, built on _call_model) ───────────────

    def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        """Call the model and validate the response against a Pydantic model.

        Args:
            prompt: The full text prompt.
            response_model: A Pydantic BaseModel subclass describing the
                expected response shape. Its JSON schema is passed to
                _call_model() so providers can use native structured output.

        Returns:
            A validated instance of response_model.

        Raises:
            AIProviderError: on API failure or schema validation failure.
        """
        json_schema = response_model.model_json_schema()
        try:
            raw = self._call_model(prompt, json_schema)
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(
                f"[{self.name}] _call_model failed: {exc}"
            ) from exc

        try:
            return response_model.model_validate(raw)
        except Exception as exc:
            raise AIProviderError(
                f"[{self.name}] Response validation failed against "
                f"{response_model.__name__}: {exc}. Raw: {raw}"
            ) from exc

    # ── Convenience wrapper (backward-compatible) ─────────────────────────────

    def generate_narrative(
        self,
        asset: str,
        regime: str,
        score: float,
        data_summary: dict,
        framework_rules: dict,
    ) -> AIResponse:
        """Convenience wrapper: builds a standard prompt and calls generate_structured.

        Kept for backward compatibility. New code should call generate_structured()
        directly with prompts built in ai_layer/.
        """
        prompt = _build_default_prompt(asset, regime, score, data_summary, framework_rules)
        response = self.generate_structured(prompt, AIResponse)
        # Inject model_used since it comes from the plugin, not the AI response
        return response.model_copy(update={"model_used": self.model_name})


# ── Shared JSON parsing utility ───────────────────────────────────────────────

def parse_json_response(text: str) -> Dict:
    """Robustly extract and parse JSON from raw model text output.

    Handles:
        - Raw JSON objects
        - Markdown ```json ... ``` fences
        - Extra text around JSON

    Raises:
        AIProviderError: if no valid JSON object is found.
    """
    # Try raw parse first (fastest path — model followed instructions)
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding a bare JSON object anywhere in the text
    obj_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    raise AIProviderError(
        f"Could not extract valid JSON from model response. "
        f"First 500 chars: {text[:500]}"
    )


# ── Default prompt builder (used by generate_narrative backward-compat) ───────

def _build_default_prompt(
    asset: str,
    regime: str,
    score: float,
    data_summary: dict,
    framework_rules: dict,
) -> str:
    return f"""You are a highly seasoned Macro-Quant Hedge Fund Manager specializing in the {asset} market.
The internal rules-based framework has determined the current regime is: {regime} (Score: {score:+.1f}).

DATA SUMMARY:
{json.dumps(data_summary, indent=2)}

FRAMEWORK WEIGHTS (Why we look at this):
{json.dumps(framework_rules, indent=2)}

TASK:
Do not blindly restate the data. Act as a sophisticated quantitative trader.
1. Provide a macro context explaining the current environment.
2. Provide a deep quantitative regime analysis (referencing concepts like Hidden Markov Regime Switching, Volatility Clustering, Mean Reversion, or Gamma Exposure when applicable).
3. Identify forward-looking scenarios (Base, Bull, Bear) with estimated probabilities.
4. Point out contradictions (e.g. price bullish but breadth/liquidity deteriorating).
5. Highlight tail risks.
6. Suggest actionable execution strategies (e.g. options structures, delta hedging, pairs).

CRITICAL CONSTRAINT: The regime "{regime}" is authoritative. Explain and support it — do not override it.

Return ONLY a valid JSON object matching this schema (no markdown, no extra text):
{{
    "executive_summary": "1 paragraph summary",
    "macro_context": "Detailed macro environment context",
    "quant_regime_analysis": "Deep quantitative breakdown",
    "forward_scenarios": [
        {{"scenario": "Base Case", "probability": "60%", "description": "..."}},
        {{"scenario": "Bull Case", "probability": "25%", "description": "..."}},
        {{"scenario": "Bear Case", "probability": "15%", "description": "..."}}
    ],
    "contradictions": ["contradiction 1"],
    "tail_risks": ["risk 1"],
    "actionable_strategies": ["strategy 1"]
}}"""
