"""
LogiFlow Sentinel - agent tools.

A ``Toolbox`` wraps the live simulation state so every tool call has a real
effect on the shipments the dashboard renders, and enforces the operational
guardrails (delivered shipments are immutable, struck carriers are off-limits,
hubs and carriers must exist).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Literal

from langchain_core.tools import tool

from .geo import HUBS, hub_accepts

# Which transport modes each carrier can legally handle
CARRIER_MODES = {
    "FastLine Express": {"road", "air"},
    "Global Logistics": {"road", "sea"},
    "Speedy Haul": {"road"},
    "RouteMasters": {"road", "rail"},
    "TransOcean Freight": {"sea"},
    "Pacific Bridge Lines": {"sea"},
    "AeroLink Cargo": {"air"},
    "EuroRail Cargo": {"rail", "road"},
    "SilkRoad Logistics": {"rail", "sea", "road"},
    "Bharat Freightways": {"road"},
    "IndiaLink Logistics": {"road", "rail"},
    "Coastal Lines India": {"sea"},
    "SkyBridge Air Cargo": {"air"},
}
CARRIERS = list(CARRIER_MODES)

class Toolbox:
    """Executes tool calls against the simulator state."""

    def __init__(self, shipments: List[Dict[str, Any]], active_events: List[Dict[str, Any]], kb) -> None:
        self._shipments = {s["shipment_id"]: s for s in shipments}
        self._events = active_events
        self._kb = kb
        self.audit_log: List[Dict[str, Any]] = []
        self._registry: Dict[str, Callable[..., Dict[str, Any]]] = {
            "search_policy": self.search_policy,
            "get_shipment": self.get_shipment,
            "reroute_shipment": self.reroute_shipment,
            "reassign_carrier": self.reassign_carrier,
            "prioritize_shipment": self.prioritize_shipment,
            "escalate_to_operator": self.escalate_to_operator,
        }

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        fn = self._registry.get(name)
        if fn is None:
            return {"status": "error", "message": f"Unknown tool '{name}'"}
        try:
            return fn(**args)
        except TypeError as exc:
            return {"status": "error", "message": f"Bad arguments: {exc}"}

    # -- read-only tools -------------------------------------------------
    def search_policy(self, query: str) -> Dict[str, Any]:
        hits = self._kb.retrieve(query, top_k=4)
        return {
            "status": "success",
            "backend": self._kb.backend,
            "results": [h.to_dict() for h in hits],
        }

    def get_shipment(self, shipment_id: str) -> Dict[str, Any]:
        shipment = self._shipments.get(shipment_id)
        if shipment is None:
            return {"status": "error", "message": f"Shipment {shipment_id} not found"}
        return {"status": "success", "shipment": dict(shipment)}

    # -- mutating tools --------------------------------------------------
    def _guard(self, shipment_id: str):
        shipment = self._shipments.get(shipment_id)
        if shipment is None:
            return None, {"status": "error", "message": f"Shipment {shipment_id} not found"}
        if shipment.get("status") == "DELIVERED":
            return None, {"status": "error", "message": "Shipment already delivered"}
        return shipment, None

    def _record(self, shipment_id: str, action: str, details: str) -> None:
        self.audit_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "shipment_id": shipment_id,
            "action": action,
            "details": details,
        })

    def _struck_carriers(self) -> set:
        """Carriers that cannot take work: on strike, in rail/driver dispute, or insolvent."""
        out = set()
        for e in self._events:
            if e.get("carrier"):
                out.add(e["carrier"])
            elif e.get("type") == "Carrier Strike":
                out.update(c for c in CARRIERS if c.lower() in e.get("description", "").lower())
        return out

    def reroute_shipment(self, shipment_id: str, new_hub: str) -> Dict[str, Any]:
        shipment, err = self._guard(shipment_id)
        if err:
            return err
        if new_hub not in HUBS:
            return {"status": "error", "message": f"Unknown hub '{new_hub}'. Valid: {', '.join(HUBS)}"}
        mode = shipment.get("mode", "road")
        if not hub_accepts(mode, new_hub):
            return {"status": "error", "message": f"{new_hub} cannot handle {mode} freight"}
        old = shipment["warehouse_checkpoint"]
        shipment.update(warehouse_checkpoint=new_hub, status="IN_TRANSIT", mitigated=True)
        self._record(shipment_id, "REROUTE", f"{old} → {new_hub}")
        return {"status": "success", "shipment_id": shipment_id, "from": old, "to": new_hub}

    def reassign_carrier(self, shipment_id: str, new_carrier: str) -> Dict[str, Any]:
        shipment, err = self._guard(shipment_id)
        if err:
            return err
        if new_carrier not in CARRIERS:
            return {"status": "error", "message": f"Unknown carrier '{new_carrier}'. Valid: {', '.join(CARRIERS)}"}
        if new_carrier in self._struck_carriers():
            return {"status": "error", "message": f"{new_carrier} is currently unavailable (strike/insolvency)"}
        mode = shipment.get("mode", "road")
        if mode not in CARRIER_MODES[new_carrier]:
            return {"status": "error", "message": f"{new_carrier} cannot carry {mode} freight"}
        old = shipment["carrier"]
        shipment.update(carrier=new_carrier, status="IN_TRANSIT", mitigated=True)
        self._record(shipment_id, "REASSIGN", f"{old} → {new_carrier}")
        return {"status": "success", "shipment_id": shipment_id, "from": old, "to": new_carrier}

    def prioritize_shipment(self, shipment_id: str, priority: int) -> Dict[str, Any]:
        shipment, err = self._guard(shipment_id)
        if err:
            return err
        if not 1 <= int(priority) <= 5:
            return {"status": "error", "message": "Priority must be between 1 and 5"}
        shipment["priority"] = int(priority)
        self._record(shipment_id, "PRIORITIZE", f"Priority set to P{int(priority)}")
        return {"status": "success", "shipment_id": shipment_id, "priority": int(priority)}

    def escalate_to_operator(self, shipment_id: str, reason: str) -> Dict[str, Any]:
        if shipment_id not in self._shipments:
            return {"status": "error", "message": f"Shipment {shipment_id} not found"}
        if not reason.strip():
            return {"status": "error", "message": "Escalation reason cannot be empty"}
        self._shipments[shipment_id]["escalated"] = True
        self._record(shipment_id, "ESCALATE", reason)
        return {"status": "success", "shipment_id": shipment_id, "operator_notified": True}


def build_tools(box: Toolbox) -> list:
    """Expose a Toolbox as LangChain tools (schemas are derived from the signatures)."""

    @tool
    def search_policy(query: str) -> Dict[str, Any]:
        """Semantic search over the operational policy knowledge base. Use it to find the rules governing a situation."""
        return box.search_policy(query)

    @tool
    def get_shipment(shipment_id: str) -> Dict[str, Any]:
        """Fetch current details (status, carrier, hub, SLA, priority) for one shipment."""
        return box.get_shipment(shipment_id)

    @tool(description="Reroute a shipment via a different hub. Valid hubs: " + ", ".join(HUBS) + ".")
    def reroute_shipment(shipment_id: str, new_hub: str) -> Dict[str, Any]:
        return box.reroute_shipment(shipment_id, new_hub)

    @tool(description="Move a shipment to another carrier. Valid carriers: " + ", ".join(CARRIERS) + ".")
    def reassign_carrier(shipment_id: str, new_carrier: str) -> Dict[str, Any]:
        return box.reassign_carrier(shipment_id, new_carrier)

    @tool
    def prioritize_shipment(shipment_id: str, priority: int) -> Dict[str, Any]:
        """Set operational priority from 1 (highest) to 5 (lowest)."""
        return box.prioritize_shipment(shipment_id, priority)

    @tool
    def escalate_to_operator(shipment_id: str, reason: str) -> Dict[str, Any]:
        """Hand a case to a human operator when no policy-compliant automatic fix exists."""
        return box.escalate_to_operator(shipment_id, reason)

    @tool
    def finish(summary: str, risk_level: Literal["Low", "Medium", "High", "Critical"]) -> Dict[str, Any]:
        """End the investigation once every affected shipment is handled, with a short summary and overall risk level."""
        return {"status": "success", "summary": summary, "risk_level": risk_level}

    return [search_policy, get_shipment, reroute_shipment, reassign_carrier,
            prioritize_shipment, escalate_to_operator, finish]
