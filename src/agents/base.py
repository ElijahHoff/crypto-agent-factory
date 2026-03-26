"""Base agent with Anthropic Claude backbone."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import anthropic
from loguru import logger
from pydantic import BaseModel

from src.config import settings


class AgentResponse(BaseModel):
    agent_name: str
    stage: str
    content: str
    structured: dict[str, Any] | None = None
    warnings: list[str] = []
    errors: list[str] = []


class BaseAgent(ABC):
    """Every agent in the factory inherits from this."""

    name: str = "base_agent"
    role: str = "Generic agent"
    temperature: float = 0.3

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt specific to this agent's role."""
        ...

    @abstractmethod
    def build_user_prompt(self, context: dict[str, Any]) -> str:
        """Build the user message from pipeline context."""
        ...

    def call_llm(
        self,
        user_prompt: str,
        *,
        max_tokens: int = 8192,
        response_format: str = "json",
    ) -> str:
        """Call Claude and return raw text response."""
        system = self.system_prompt()
        if response_format == "json":
            system += (
                "\n\nIMPORTANT: Respond ONLY with valid JSON. "
                "No markdown fences, no preamble, no commentary outside the JSON."
            )

        logger.info(f"[{self.name}] Calling LLM ({self.model})...")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        logger.debug(f"[{self.name}] Got {len(text)} chars, {response.usage.output_tokens} tokens")
        return text

    def call_llm_structured(self, user_prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Call LLM and parse JSON response."""
        raw = self.call_llm(user_prompt, response_format="json", **kwargs)
        # Strip markdown fences if model added them anyway
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        return json.loads(cleaned)

    def run(self, context: dict[str, Any]) -> AgentResponse:
        """Main entry point: build prompt → call LLM → parse → return."""
        try:
            user_prompt = self.build_user_prompt(context)
            structured = self.call_llm_structured(user_prompt)
            return AgentResponse(
                agent_name=self.name,
                stage=context.get("stage", "unknown"),
                content=json.dumps(structured, indent=2),
                structured=structured,
            )
        except json.JSONDecodeError as e:
            logger.error(f"[{self.name}] JSON parse error: {e}")
            # Fallback: return raw text
            raw = self.call_llm(self.build_user_prompt(context), response_format="text")
            return AgentResponse(
                agent_name=self.name,
                stage=context.get("stage", "unknown"),
                content=raw,
                errors=[f"JSON parse failed: {e}"],
            )
        except Exception as e:
            logger.exception(f"[{self.name}] Error")
            return AgentResponse(
                agent_name=self.name,
                stage=context.get("stage", "unknown"),
                content="",
                errors=[str(e)],
            )
