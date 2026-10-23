"""
LogiFlow Sentinel - autonomous incident agent (LangGraph).

Graph per disruption::

    START -> retrieve (RAG) -> agent (LLM + tools) <-> tools -> END

* ``retrieve``  pulls the governing policies from the FAISS knowledge base
* ``agent``     a tool-calling chat model reasons and picks actions
* ``tools``     a ToolNode executes them against the simulation (guardrailed)
The loop ends when the model calls ``finish`` or stops calling tools.

The chat model is pluggable: Claude (``langchain-anthropic``), Ollama
(``langchain-ollama``), or ``RuleChatModel``, a deterministic offline stand-in
so the demo works with no keys and no local model.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .geo import CITIES, HUBS, hub_accepts
from .rag import ROOT, KnowledgeBase
from .tools import CARRIERS, Toolbox, build_tools

load_dotenv(ROOT / ".env")

RECURSION_LIMIT = 160  # each tool call costs two graph steps (agent + tools)

SYSTEM_PROMPT = """You are LogiFlow Sentinel, an autonomous logistics operations agent.
You are handed one active disruption plus the policies retrieved for it. Resolve it for every affected shipment.

Workflow:
1. Read the retrieved policies. Call search_policy again if you need something more specific.
2. Call get_shipment when you need details of an affected shipment.
3. Take the most policy-compliant action per shipment: reroute_shipment, reassign_carrier,
   prioritize_shipment, or escalate_to_operator when no compliant automatic fix exists.
4. Call finish with a short summary and an overall risk level.

Rules: cite policy IDs like [R4] in your reasoning; never act against a retrieved policy;
use only valid hubs and carriers; write one short sentence of reasoning before each tool call."""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    event: Dict[str, Any]
    policies: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Offline chat model
# ---------------------------------------------------------------------------
def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], (a[1] - b[1]) * math.cos(math.radians(a[0])))


REROUTE_TYPES = {"Cyclone", "Track Blockage", "Severe Storm", "Warehouse Congestion", "Typhoon", "Hurricane", "Flooding", "Earthquake", "Wildfire",
                 "Volcanic Ash", "Airspace Closure", "Port Congestion", "Port Strike", "Canal Disruption", "Piracy Risk"}
REASSIGN_TYPES = {"Carrier Strike", "Vehicle Breakdown", "Rail Strike", "Driver Shortage", "Fuel Shortage", "Carrier Insolvency"}
CARRIER_PREFERENCE = {
    "road": ["FastLine Express", "Global Logistics", "EuroRail Cargo", "SilkRoad Logistics", "Speedy Haul", "RouteMasters"],
    "sea": ["TransOcean Freight", "Pacific Bridge Lines", "Global Logistics", "SilkRoad Logistics"],
    "air": ["AeroLink Cargo", "FastLine Express"],
    "rail": ["EuroRail Cargo", "SilkRoad Logistics", "RouteMasters"],
}
INDIAN_CARRIERS = {"road": ["Bharat Freightways", "IndiaLink Logistics"], "sea": ["Coastal Lines India"],
                   "air": ["SkyBridge Air Cargo"], "rail": ["IndiaLink Logistics"]}
CRITICAL_CARGO = {"Pharmaceuticals", "Vaccines", "Perishables", "Medical devices"}


def plan_actions(event: Dict[str, Any], shipments: Dict[str, Dict[str, Any]], rule_ids: List[str], unavailable=frozenset()):
    """Playbook per disruption type -> list of (tool, thought, args)."""
    kind = event["type"]
    cite = ", ".join(f"[{i}]" for i in rule_ids[:3]) or "[no policy found]"
    desc = event["description"].lower()
    blocked = {event["location"]} if event.get("location") in HUBS else {h for h in HUBS if h.split()[0].lower() in desc}
    struck = ({event["carrier"]} if event.get("carrier") else {c for c in CARRIERS if c.lower() in desc}) | set(unavailable)
    plan = []
    for sid in event["affected_shipments"]:
        s = shipments.get(sid)
        if s is None or s["status"] == "DELIVERED":
            continue
        critical = s.get("cargo") in CRITICAL_CARGO
        if kind in REROUTE_TYPES:
            here = HUBS.get(s["warehouse_checkpoint"], (39.0, -98.0))
            mode = s.get("mode", "road")
            options = [h for h in HUBS if h not in blocked and h != s["warehouse_checkpoint"] and hub_accepts(mode, h)]
            o, d = CITIES.get(s["origin"], here), CITIES.get(s["destination"], here)
            # least detour for the shipment's actual journey, tie-broken by closeness to the disrupted hub
            hub = min(options, key=lambda h: _dist(o, HUBS[h]) + _dist(HUBS[h], d) + 0.35 * _dist(here, HUBS[h]))
            plan.append(("reroute_shipment", f"{sid} ({s.get('cargo', 'cargo')}) is exposed to the {kind.lower()}; divert via {hub} ({mode}-capable) per {cite}.",
                         {"shipment_id": sid, "new_hub": hub}))
            if s["sla_hours"] < 48 or critical:
                why = "critical cargo" if critical else f"tight SLA ({s['sla_hours']}h)"
                plan.append(("prioritize_shipment", f"{sid} has {why}; prioritize per {cite}.", {"shipment_id": sid, "priority": 1}))
        elif kind in REASSIGN_TYPES:
            mode = s.get("mode", "road")
            ranked = CARRIER_PREFERENCE[mode]
            if s["origin"].endswith("India") or s["destination"].endswith("India"):
                ranked = INDIAN_CARRIERS[mode] + ranked  # domestic freight: prefer Indian operators
            options = [c for c in ranked if c not in struck and c != s["carrier"]]
            if not options:
                plan.append(("escalate_to_operator", f"No {mode} carrier is available for {sid} ({cite}); escalating.",
                             {"shipment_id": sid, "reason": f"{kind}: no alternative {mode} carrier with capacity"}))
                continue
            plan.append(("reassign_carrier", f"{sid} must leave {s['carrier']}; {options[0]} is the best available {mode} carrier per {cite}.",
                         {"shipment_id": sid, "new_carrier": options[0]}))
        elif kind == "Cold Chain Failure":
            plan.append(("prioritize_shipment", f"{sid} ({s.get('cargo', 'cargo')}) is at temperature risk; P1 per {cite}.", {"shipment_id": sid, "priority": 1}))
            plan.append(("escalate_to_operator", f"A human must verify cold storage integrity for {sid} ({cite}).",
                         {"shipment_id": sid, "reason": f"Cold-chain failure at {event.get('location', 'hub')}: quarantine check required for {s.get('cargo', 'cargo')}."}))
        elif kind == "Customs Hold":
            plan.append(("prioritize_shipment", f"Raise {sid} so paperwork is expedited per {cite}.", {"shipment_id": sid, "priority": 1}))
            plan.append(("escalate_to_operator", f"Clearance needs shipper paperwork, so a human must chase it ({cite}).",
                         {"shipment_id": sid, "reason": "Customs hold: expedited paperwork required from shipper (typically 48-72h otherwise)."}))
        else:  # Port closure, IT / cyber, sanctions, inventory: no safe automatic fix
            plan.append(("escalate_to_operator", f"No automatic action satisfies {cite} for {sid}; escalating.",
                         {"shipment_id": sid, "reason": f"{kind}: {event['description']}"}))
    return plan


class RuleChatModel(BaseChatModel):
    """Deterministic tool-calling chat model; emits the playbook one call per turn."""

    shipments: Dict[str, Dict[str, Any]]
    unavailable: frozenset = frozenset()

    @property
    def _llm_type(self) -> str:
        return "rules"

    def bind_tools(self, tools, **kwargs):  # tools are already known to the playbook
        return self

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        done = sum(isinstance(m, ToolMessage) for m in messages)
        context = next(m.content for m in messages if isinstance(m, HumanMessage))
        event = json.loads(re.search(r"<event>(.*?)</event>", context, re.S).group(1))
        rule_ids = re.findall(r"\[(R\d+)\]", context.split("<policies>")[-1])
        plan = plan_actions(event, self.shipments, rule_ids, self.unavailable)

        if done < len(plan):
            tool, thought, args = plan[done]
            if done == 0 and rule_ids:
                first = re.search(r"\[(R\d+)\] (.*)", context.split("<policies>")[-1])
                thought = f"Top policy [{first.group(1)}]: {first.group(2)} {thought}"
        else:
            tool, thought = "finish", "Every affected shipment has been handled."
            args = {
                "summary": f"Handled {event['type']} for {len(plan)} action(s) using policies {', '.join(rule_ids[:3]) or 'n/a'}.",
                "risk_level": {"CRITICAL": "Critical", "HIGH": "High", "MEDIUM": "Medium"}.get(event["severity"].upper(), "Low"),
            }
        msg = AIMessage(content=thought, tool_calls=[{"name": tool, "args": args, "id": f"call_{done}"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _make_llm(backend: str, shipments: List[Dict[str, Any]], unavailable=frozenset()) -> BaseChatModel:
    if backend == "claude":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), temperature=0, max_tokens=1500)
    if backend == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=os.getenv("OLLAMA_MODEL", "llama3.1"), temperature=0)
    return RuleChatModel(shipments={s["shipment_id"]: s for s in shipments}, unavailable=frozenset(unavailable))


def default_backend() -> str:
    forced = os.getenv("LLM_BACKEND")
    if forced:
        return forced
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else "rules"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph(llm: BaseChatModel, toolbox: Toolbox, kb: KnowledgeBase):
    tools = build_tools(toolbox)
    llm_with_tools = llm.bind_tools(tools)

    def retrieve(state: AgentState) -> Dict[str, Any]:
        event = state["event"]
        hits = [h.to_dict() for h in kb.retrieve(f"{event['type']}: {event['description']}", top_k=4)]
        listing = "\n".join(f"[{h['rule_id']}] {h['text']}" for h in hits)
        prompt = (f"<event>{json.dumps(event)}</event>\n"
                  f"Valid hubs: {', '.join(HUBS)}\nValid carriers: {', '.join(CARRIERS)}\n"
                  f"<policies>\n{listing}")
        return {"policies": hits, "messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)]}

    def agent(state: AgentState) -> Dict[str, Any]:
        return {"messages": [llm_with_tools.invoke(list(state["messages"]))]}

    def route_after_agent(state: AgentState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    def route_after_tools(state: AgentState) -> str:
        return END if state["messages"][-1].name == "finish" else "agent"

    g = StateGraph(AgentState)
    g.add_node("retrieve", retrieve)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "agent")
    g.add_conditional_edges("agent", route_after_agent, ["tools", END])
    g.add_conditional_edges("tools", route_after_tools, ["agent", END])
    return g.compile()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


def _build_trace(state: Dict[str, Any], backend_name: str) -> Dict[str, Any]:
    steps = [{
        "thought": "Retrieving the policies that apply to this disruption (RAG).",
        "tool": "search_policy",
        "args": {"query": f"{state['event']['type']}: {state['event']['description']}"},
        "observation": {"status": "success", "backend": backend_name, "results": state["policies"]},
    }]
    results = {m.tool_call_id: m for m in state["messages"] if isinstance(m, ToolMessage)}
    summary, risk = "Investigation ended without a summary.", "Medium"
    for m in state["messages"]:
        if not isinstance(m, AIMessage):
            continue
        for call in m.tool_calls:
            tm = results.get(call["id"])
            obs = json.loads(tm.content) if tm is not None and tm.content.startswith("{") else {}
            steps.append({"thought": _text(m.content), "tool": call["name"], "args": call["args"], "observation": obs})
            if call["name"] == "finish":
                summary, risk = call["args"].get("summary", summary), call["args"].get("risk_level", risk)
    return {"steps": steps, "summary": summary, "risk_level": risk}


class SentinelAgent:
    def __init__(self, kb: Optional[KnowledgeBase] = None, backend: Optional[str] = None) -> None:
        self.kb = kb or KnowledgeBase()
        self.backend = backend or default_backend()

    def _run(self, backend: str, event, shipments, active_events):
        toolbox = Toolbox(shipments, active_events, self.kb)
        graph = build_graph(_make_llm(backend, shipments, toolbox._struck_carriers()), toolbox, self.kb)
        initial = {"messages": [], "event": event, "policies": []}
        final = initial
        try:  # stream so partial progress survives hitting the step limit
            for final in graph.stream(initial, {"recursion_limit": RECURSION_LIMIT}, stream_mode="values"):
                pass
        except GraphRecursionError:
            pass
        return toolbox, final

    def investigate(self, event: Dict[str, Any], shipments: List[Dict[str, Any]],
                    active_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run the graph for one disruption and return its full trace."""
        brain = self.backend
        try:
            toolbox, final = self._run(brain, event, shipments, active_events)
        except Exception as exc:  # missing key, offline model, malformed tool call...
            brain = f"rules (fallback: {type(exc).__name__})"
            toolbox, final = self._run("rules", event, shipments, active_events)
        trace = _build_trace(final, self.kb.backend)
        cited = sorted({h["rule_id"] for s in trace["steps"] if s["tool"] == "search_policy"
                        for h in s["observation"].get("results", [])}, key=lambda r: int(r[1:]))
        return {"event": event, "brain": brain, "retrieval_backend": self.kb.backend,
                "steps": trace["steps"], "summary": trace["summary"], "risk_level": trace["risk_level"],
                "policies": cited, "actions": toolbox.audit_log}
