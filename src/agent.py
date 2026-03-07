from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from langchain.schema import BaseMessage  # noqa: F401  # imported to satisfy langchain usage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

try:  # Prefer the community integration when available
    from langchain_community.chat_models import ChatOllama  # type: ignore
except Exception:  # Fallback for environments using langchain-ollama
    from langchain_ollama import ChatOllama  # type: ignore

try:  # Package-style import (recommended when running as a module)
    from . import tools  # type: ignore
except Exception:  # Script-style fallback for direct execution
    import tools  # type: ignore


class AgentDecision(BaseModel):
    """
    Structured decision returned by the logistics agent.

    This schema is enforced via PydanticOutputParser so the LLM
    must always emit a JSON object compatible with this model.
    """

    risk_level: Literal["Low", "Medium", "Critical"] = Field(
        ...,
        description="Overall operational risk level for the shipment.",
    )
    reasoning: str = Field(
        ...,
        description="Concise explanation of why this risk level and action were chosen.",
    )
    recommended_action: str = Field(
        ...,
        description=(
            "Name of the single best tool to call, e.g. "
            "'reroute_shipment', 'prioritize_shipment', "
            "'reassign_carrier', 'escalate_to_operator', or 'no_action'."
        ),
    )
    action_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary of arguments to pass to the chosen tool.",
    )


class LogisticsAgent:
    """
    LogiFlow Sentinel agent that observes shipment state, detects risk,
    and executes the appropriate intervention via simulation tools.
    """

    def __init__(self, model_name: str = "llama3") -> None:
        """
        Initialize the logistics agent and its LLM chain.

        Args:
            model_name: Name of the local Ollama model to target.
        """
        self._parser = PydanticOutputParser(pydantic_object=AgentDecision)

        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "You are LogiFlow Sentinel, an expert logistics operations AI. "
                        "You monitor shipments, detect risks (weather, temperature, route issues, "
                        "capacity constraints, etc.), and choose the safest, most operationally sound "
                        "single action to take.\n\n"
                        "You MUST respond with a single JSON object that strictly follows this schema:\n"
                        "{format_instructions}\n\n"
                        "Domain rules and guardrails:\n"
                        "- Temperature-sensitive pharmaceutical cargo must stay below 25°C at all times.\n"
                        "- Shipments containing keywords like 'pharma', 'vaccine', or 'clinical' are "
                        "highly critical.\n"
                        "- Weather alerts such as 'storm', 'snow', 'flood', or 'hurricane' on the route "
                        "increase risk significantly.\n"
                        "- Never attempt to reroute or change priority of a shipment that is already "
                        "delivered; in such cases prefer 'no_action' or 'escalate_to_operator'.\n"
                        "- Only call tools that are explicitly available: 'reroute_shipment', "
                        "'prioritize_shipment', 'reassign_carrier', 'escalate_to_operator', "
                        "or 'no_action'.\n"
                        "- When no meaningful intervention is needed, use 'no_action' with "
                        "`risk_level` set to 'Low'."
                    ),
                ),
                (
                    "user",
                    (
                        "Evaluate the following shipment and external events.\n\n"
                        "Shipment data JSON:\n"
                        "{shipment_data_json}\n\n"
                        "External events JSON (may be empty):\n"
                        "{external_events_json}\n\n"
                        "Think carefully about regulatory and operational risk, then "
                        "choose exactly one tool and suitable parameters."
                    ),
                ),
            ]
        ).partial(format_instructions=self._parser.get_format_instructions())

        # Local Ollama chat model; JSON-formatted responses are requested
        self._llm = ChatOllama(
            model=model_name,
            format="json",
            temperature=0.1,
        )

        # LCEL chain: prompt -> LLM -> Pydantic parser
        self._chain = self._prompt | self._llm | self._parser

        # Action registry mapping tool names to concrete functions
        self._action_registry: Dict[str, Callable[..., Dict[str, Any]]] = {
            "reroute_shipment": tools.reroute_shipment,
            "prioritize_shipment": tools.prioritize_shipment,
            "reassign_carrier": tools.reassign_carrier,
            "escalate_to_operator": tools.escalate_to_operator,
            # Synthetic tool representing a deliberate no-op
            "no_action": self._no_action,
        }

    @staticmethod
    def _no_action(**_: Any) -> Dict[str, Any]:
        """
        Fallback tool used when the agent determines that no intervention is required.
        """
        return {
            "status": "no_action",
            "operation": "none",
            "message": "No operational intervention taken.",
        }

    @staticmethod
    def _is_status_normal(shipment_data: Dict[str, Any]) -> bool:
        """
        Heuristic check for a 'normal' shipment state to allow early exit.
        """
        status_value = str(shipment_data.get("status", "")).lower()
        # Common 'healthy' states in logistics operations
        normal_statuses = {"on_time", "in_transit", "normal", "ok"}
        return status_value in normal_statuses

    def _execute_action(
        self,
        decision: AgentDecision,
        shipment_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute the chosen tool based on the LLM decision.
        """
        action_name = decision.recommended_action.strip()
        params: Dict[str, Any] = dict(decision.action_parameters or {})

        # Ensure shipment_id is always propagated when available
        shipment_id: Optional[str] = shipment_data.get("shipment_id")
        if shipment_id and "shipment_id" not in params:
            params["shipment_id"] = shipment_id

        # Normalize some common 'no-op' spellings
        if action_name.lower() in {"no_action", "none", "noop", "no-op"}:
            return self._no_action(**params)

        tool_fn = self._action_registry.get(action_name)
        if tool_fn is None:
            # Graceful handling of unknown tool names
            return {
                "status": "error",
                "operation": "unknown_action",
                "requested_action": action_name,
                "action_parameters": params,
                "message": (
                    "The agent recommended an unknown action. "
                    "No operational change was executed."
                ),
            }

        try:
            return tool_fn(**params)
        except TypeError as exc:
            # Parameter mismatch or missing arguments
            return {
                "status": "error",
                "operation": action_name,
                "action_parameters": params,
                "message": f"Failed to execute tool due to parameter mismatch: {exc}",
            }
        except Exception as exc:  # pragma: no cover - defensive guardrail
            return {
                "status": "error",
                "operation": action_name,
                "action_parameters": params,
                "message": f"Unexpected error while executing tool: {exc}",
            }

    def observe_and_act(
        self,
        shipment_data: Dict[str, Any],
        external_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Observe the shipment state and external events, reason about risk,
        and (optionally) execute the appropriate intervention.

        - If the shipment status is normal and there are no external events,
          the method returns a Low Risk / No Action response immediately
          without calling the LLM (to save cost and latency).
        - Otherwise, it constructs a structured prompt, invokes the LLM chain,
          parses the response into `AgentDecision`, and executes the
          corresponding tool from `tools.py`.
        """
        external_events = external_events or []

        # Cost-saving fast path: healthy status and no notable events
        if self._is_status_normal(shipment_data) and not external_events:
            tool_result = self._no_action()
            return {
                "risk_level": "Low",
                "reasoning": (
                    "Shipment status is normal and no external risk events were detected; "
                    "no intervention required."
                ),
                "recommended_action": "no_action",
                "action_parameters": {},
                "tool_result": tool_result,
            }

        shipment_json = json.dumps(shipment_data, ensure_ascii=False, indent=2)
        events_json = json.dumps(external_events, ensure_ascii=False, indent=2)

        try:
            decision: AgentDecision = self._chain.invoke(
                {
                    "shipment_data_json": shipment_json,
                    "external_events_json": events_json,
                }
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            # Robust handling for parsing / schema issues
            fallback_reason = (
                "LLM output could not be parsed into the required JSON schema. "
                f"Parsing error: {exc}"
            )
            # In case of uncertainty, escalate to a human operator
            fallback_decision = AgentDecision(
                risk_level="Critical",
                reasoning=fallback_reason,
                recommended_action="escalate_to_operator",
                action_parameters={
                    "reason": fallback_reason,
                    "shipment_id": shipment_data.get("shipment_id", "UNKNOWN"),
                },
            )
            tool_result = self._execute_action(fallback_decision, shipment_data)
            return {
                "risk_level": fallback_decision.risk_level,
                "reasoning": fallback_decision.reasoning,
                "recommended_action": fallback_decision.recommended_action,
                "action_parameters": fallback_decision.action_parameters,
                "tool_result": tool_result,
            }

        # Execute the recommended action
        tool_result = self._execute_action(decision, shipment_data)

        return {
            "risk_level": decision.risk_level,
            "reasoning": decision.reasoning,
            "recommended_action": decision.recommended_action,
            "action_parameters": decision.action_parameters,
            "tool_result": tool_result,
        }


if __name__ == "__main__":
    """
    Simple manual test harness for the LogisticsAgent.

    This can be run directly to verify end-to-end behavior against
    a mock shipment and synthetic external events.
    """
    # Example mock shipment payload
    mock_shipment = {
        "shipment_id": "SHIP-12345",
        "status": "in_transit",
        "origin": "San Francisco, CA",
        "destination": "Seattle, WA",
        "cargo_type": "pharma - vaccines",
        "current_temperature_c": 27.5,
        "expected_delivery_eta_hours": 10,
        "route": "I-5 North",
    }

    # Example external events, including a weather alert on the route
    mock_external_events = [
        {
            "type": "weather_alert",
            "severity": "high",
            "description": "Severe storm warning with heavy rain and possible flooding along I-5.",
            "affected_routes": ["I-5 North"],
        }
    ]

    agent = LogisticsAgent()
    result = agent.observe_and_act(mock_shipment, mock_external_events)

    # For debugging / quick inspection only: pretty-print the result JSON
    print(json.dumps(result, indent=2, ensure_ascii=False))

