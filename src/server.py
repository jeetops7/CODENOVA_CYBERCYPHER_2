"""
LogiFlow Sentinel - web server.

    python -m src.server          # http://localhost:8501

A small FastAPI app: it owns one simulation + agent session and serves the
static front end in ``web/`` (a 3D globe built with globe.gl).
"""

from __future__ import annotations

import threading
import zlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import SentinelAgent, default_backend
from . import routing
from .geo import CITIES, HUB_KIND, HUBS
from .rag import KnowledgeBase
from .simulator import LogisticsSimulator

WEB = Path(__file__).resolve().parent.parent / "web"
ENGINES = ["rules", "claude", "ollama"]

app = FastAPI(title="LogiFlow Sentinel")
_lock = threading.Lock()


class Session:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.engine = default_backend() if default_backend() in ENGINES else "rules"
        self.reset()

    def reset(self) -> None:
        self.sim = LogisticsSimulator()
        self.tick = 0
        self.investigations: List[Dict[str, Any]] = []
        self.handled: set = set()
        self.audit: List[Dict[str, Any]] = []

    def investigate_new(self) -> None:
        agent = SentinelAgent(kb=self.kb, backend=self.engine)
        for event in list(self.sim.active_events):
            if event["event_id"] in self.handled:
                continue
            result = agent.investigate(event, self.sim.shipments, self.sim.active_events)
            result["tick"] = self.tick
            self.investigations.insert(0, result)
            self.audit = result["actions"] + self.audit
            self.handled.add(event["event_id"])


session = Session(KnowledgeBase())


def _jitter(sid: str):
    key = sid.encode()
    return ((zlib.crc32(key) % 100) / 100 - 0.5) * 1.4, ((zlib.crc32(key[::-1]) % 100) / 100 - 0.5) * 1.8


def _event_geo(event: Dict[str, Any]) -> Dict[str, float]:
    loc = event.get("location")
    if loc in HUBS:
        return {"lat": HUBS[loc][0], "lng": HUBS[loc][1]}
    if loc in CITIES:
        return {"lat": CITIES[loc][0], "lng": CITIES[loc][1]}
    desc = event["description"].lower()
    for hub, (lat, lng) in HUBS.items():
        if hub.split()[0].lower() in desc:
            return {"lat": lat, "lng": lng}
    by_id = {s["shipment_id"]: s for s in session.sim.shipments}
    for sid in event.get("affected_shipments", []):
        hub = by_id.get(sid, {}).get("warehouse_checkpoint")
        if hub in HUBS:
            return {"lat": HUBS[hub][0], "lng": HUBS[hub][1]}
    return {"lat": 39.0, "lng": -98.0}


def _shipment(s: Dict[str, Any]) -> Dict[str, Any]:
    hub = HUBS.get(s["warehouse_checkpoint"], (39.0, -98.0))
    jlat, jlng = _jitter(s["shipment_id"])
    o, d = CITIES.get(s["origin"]), CITIES.get(s["destination"])
    return {
        **{k: s.get(k) for k in ("shipment_id", "status", "carrier", "warehouse_checkpoint",
                                  "origin", "destination", "sla_hours", "current_eta", "planned_eta", "shipped_at", "priority", "mitigated", "mode", "cargo")},
        "route_key": "|".join([s["origin"], s["warehouse_checkpoint"], s["destination"], s.get("mode", "road")]),
        "lat": hub[0] + jlat, "lng": hub[1] + jlng, "hub": {"lat": hub[0], "lng": hub[1]},
        "from": {"lat": o[0], "lng": o[1]} if o else None, "to": {"lat": d[0], "lng": d[1]} if d else None,
    }


def snapshot() -> Dict[str, Any]:
    s = session
    incidents_by_ship: Dict[str, List[str]] = {}
    for e in s.sim.active_events:
        for sid in e.get("affected_shipments", []):
            incidents_by_ship.setdefault(sid, []).append(e["type"])
    return {
        "tick": s.tick,
        "clock": s.sim.clock.isoformat() + "Z",
        "cities": [{"name": n, "lat": v[0], "lng": v[1]} for n, v in CITIES.items()],
        "engine": s.engine,
        "engines": ENGINES,
        "retrieval": s.kb.backend,
        "shipments": [{**_shipment(x), "incidents": incidents_by_ship.get(x["shipment_id"], [])} for x in s.sim.shipments],
        "events": [{**e, **_event_geo(e), "handled": e["event_id"] in s.handled,
                    "ticks_left": max(0, e.get("duration_ticks", 8) - (s.tick - e.get("started_tick", 0)))}
                   for e in s.sim.active_events],
        "scenarios": [{"event_id": e["event_id"], "type": e["type"], "severity": e["severity"], "region": e.get("region", ""), "location": e.get("location") or e.get("carrier") or e.get("region", "")}
                      for e in s.sim.available_scenarios],
        "investigations": s.investigations,
        "audit": s.audit[:30],
        "hubs": [{"name": n, "lat": v[0], "lng": v[1]} for n, v in HUBS.items()],
    }


class Inject(BaseModel):
    event_id: str


class Engine(BaseModel):
    engine: str


class Routes(BaseModel):
    keys: List[str]


class Node(BaseModel):
    kind: str  # "city" | "hub"
    name: str


class Query(BaseModel):
    query: str


@app.get("/api/state")
def state():
    with _lock:
        return snapshot()


@app.post("/api/tick")
def tick():
    with _lock:
        session.tick += 1
        session.sim.simulate_step()
        session.investigate_new()
        return snapshot()


@app.post("/api/inject")
def inject(body: Inject):
    with _lock:
        if session.sim.inject_event(body.event_id):
            session.tick += 1
            session.sim.simulate_step()
            session.investigate_new()
        return snapshot()


@app.post("/api/reset")
def reset():
    with _lock:
        session.reset()
        return snapshot()


@app.post("/api/engine")
def engine(body: Engine):
    with _lock:
        if body.engine in ENGINES:
            session.engine = body.engine
        return snapshot()


@app.post("/api/routes")
def get_routes(body: Routes):
    """Surface route legs for the given shipment lanes (computed on demand, cached)."""
    def one(key: str):
        origin, hub, dest, mode = key.split("|")
        return key, routing.shipment_route(origin, hub, dest, mode)

    with ThreadPoolExecutor(6) as pool:
        return dict(pool.map(one, body.keys[:80]))


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", ""))


@app.post("/api/node")
def node_dashboard(body: Node):
    """Everything the city/hub dashboard shows: shipments, timing, route legs, incidents, history."""
    with _lock:
        s = session
        clock = s.sim.clock
        coords = HUBS.get(body.name) if body.kind == "hub" else CITIES.get(body.name)
        if coords is None:
            return {"error": "unknown node"}
        near_hubs = {h for h, c in HUBS.items() if routing.gc_deg(c, coords) < 0.6}
        if body.kind == "hub":
            members = [x for x in s.sim.shipments if x["warehouse_checkpoint"] == body.name]
        else:
            members = [x for x in s.sim.shipments if body.name in (x["origin"], x["destination"]) or x["warehouse_checkpoint"] in near_hubs]
        members = [dict(x) for x in members]
        active = [dict(e) for e in s.sim.active_events]
        invs = [{"event": i["event"], "tick": i.get("tick"), "actions": list(i["actions"])} for i in s.investigations]
        active_ids = {e["event_id"] for e in active}
        member_ids = {x["shipment_id"] for x in members}
        tick = s.tick

    def detail(x):
        legs = routing.shipment_route(x["origin"], x["warehouse_checkpoint"], x["destination"], x.get("mode", "road"))
        shipped, planned, eta = _parse(x["shipped_at"]), _parse(x["planned_eta"]), _parse(x["current_eta"])
        total = max(1.0, (eta - shipped).total_seconds())
        progress = 1.0 if x["status"] == "DELIVERED" else max(0.0, min(0.98, (clock - shipped).total_seconds() / total))
        hist = []
        for inv in invs:
            if x["shipment_id"] in inv["event"].get("affected_shipments", []):
                hist.append({"tick": inv["tick"], "event_id": inv["event"]["event_id"], "event": inv["event"]["type"],
                             "severity": inv["event"]["severity"], "active": inv["event"]["event_id"] in active_ids,
                             "actions": [{"action": a["action"], "details": a["details"]} for a in inv["actions"]
                                         if a["shipment_id"] == x["shipment_id"]]})
        return {
            **{k: x.get(k) for k in ("shipment_id", "status", "carrier", "origin", "destination", "warehouse_checkpoint",
                                      "mode", "cargo", "sla_hours", "priority", "mitigated", "escalated",
                                      "shipped_at", "planned_eta", "current_eta")},
            "delay_h": round((eta - planned).total_seconds() / 3600, 1),
            "progress": round(progress, 3),
            "legs": [{"from": l["from"], "to": l["to"], "mode": l["mode"], "km": l["km"]} for l in legs],
            "km": sum(l["km"] for l in legs),
            "history": hist,
            "incident_ids": [e["event_id"] for e in active if x["shipment_id"] in e.get("affected_shipments", [])],
        }

    with ThreadPoolExecutor(6) as pool:
        ships = list(pool.map(detail, members))
    ships.sort(key=lambda r: r["current_eta"])

    live = [r for r in ships if r["status"] != "DELIVERED"]
    delayed = [r for r in live if r["status"] == "DELAYED"]
    kpis = {
        "total": len(ships), "in_transit": sum(r["status"] == "IN_TRANSIT" for r in ships),
        "at_checkpoint": sum(r["status"] == "AT_CHECKPOINT" for r in ships), "delayed": len(delayed),
        "delivered": len(ships) - len(live), "rerouted": sum(bool(r["mitigated"]) for r in ships),
        "avg_delay_h": round(sum(r["delay_h"] for r in live if r["delay_h"] > 0) / max(1, sum(r["delay_h"] > 0 for r in live)), 1),
        "on_time_pct": round(100 * (1 - len(delayed) / max(1, len(live)))),
        "km": sum(r["km"] for r in ships),
    }
    related = [e for e in active if e.get("location") == body.name or member_ids & set(e.get("affected_shipments", []))]
    past = [i for i in invs if i["event"]["event_id"] not in active_ids and member_ids & set(i["event"].get("affected_shipments", []))]
    incidents = [{**{k: e.get(k) for k in ("event_id", "type", "severity", "description", "region", "location")},
                  "active": True, "affected_here": len(member_ids & set(e.get("affected_shipments", []))),
                  "ticks_left": max(0, e.get("duration_ticks", 8) - (tick - e.get("started_tick", 0)))} for e in related]
    incidents += [{**{k: i["event"].get(k) for k in ("event_id", "type", "severity", "description", "region", "location")},
                   "active": False, "affected_here": len(member_ids & set(i["event"].get("affected_shipments", []))),
                   "ticks_left": 0} for i in past[:5]]
    nearby = [{"kind": "hub", "name": h} for h, c in HUBS.items() if h != body.name and routing.gc_deg(c, coords) < 1.0]
    if body.kind == "hub":
        nearby += [{"kind": "city", "name": c} for c, v in CITIES.items() if routing.gc_deg(v, coords) < 1.0]
    else:
        nearby += [{"kind": "city", "name": c} for c, v in CITIES.items() if c != body.name and routing.gc_deg(v, coords) < 1.0]
    return {
        "node": {"kind": body.kind, "name": body.name, "lat": coords[0], "lng": coords[1],
                 "type": HUB_KIND.get(body.name, "City") if body.kind == "hub" else "City"},
        "clock": clock.isoformat() + "Z", "kpis": kpis, "incidents": incidents, "nearby": nearby, "shipments": ships,
    }


@app.post("/api/search")
def search(body: Query):
    hits = session.kb.retrieve(body.query, top_k=6) if body.query.strip() else []
    return {"backend": session.kb.backend, "results": [h.to_dict() for h in hits]}


@app.get("/api/policies")
def policies():
    return {"backend": session.kb.backend, "rules": session.kb.rules}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8501, log_level="warning")
