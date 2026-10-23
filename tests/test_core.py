from src.rag import KnowledgeBase, load_rules
from src.simulator import LogisticsSimulator
from src.tools import Toolbox
from src.agent import SentinelAgent
from src import evaluate


def kb():
    return KnowledgeBase(force_local=True)


def test_rules_are_parsed():
    rules = load_rules()
    assert len(rules) >= 60 and rules[0]["id"] == "R1"


def test_retrieval_finds_strike_policy():
    assert any(h.rule_id == "R12" for h in kb().retrieve("carrier strike reassign shipments"))


def test_toolbox_guardrails():
    sim = LogisticsSimulator(seed=0)
    sim.shipments[0]["status"] = "DELIVERED"
    tb = Toolbox(sim.shipments, [], kb())
    assert tb.reroute_shipment(sim.shipments[0]["shipment_id"], "Denver Hub")["status"] == "error"
    assert tb.reroute_shipment(sim.shipments[1]["shipment_id"], "Atlantis")["status"] == "error"
    assert tb.escalate_to_operator(sim.shipments[1]["shipment_id"], " ")["status"] == "error"


def test_cannot_assign_struck_carrier():
    sim = LogisticsSimulator(seed=0)
    event = sim.inject_event("EVT-8003")
    tb = Toolbox(sim.shipments, sim.active_events, kb())
    assert tb.reassign_carrier("SHP-1001", "RouteMasters")["status"] == "error"


def test_agent_mutates_state_and_stops_delay():
    sim = LogisticsSimulator(seed=0)
    event = sim.inject_event("EVT-8003")
    result = SentinelAgent(kb=kb(), backend="rules").investigate(event, sim.shipments, sim.active_events)
    assert result["actions"] and result["steps"][-1]["tool"] == "finish"
    assert all(s["carrier"] != "RouteMasters" for s in sim.shipments if s["shipment_id"] in event["affected_shipments"])


def test_global_dataset_is_consistent():
    import json
    from src.geo import CITIES, HUBS
    from src.rag import ROOT
    ships = json.loads((ROOT / "data/shipment_data.json").read_text())
    events = json.loads((ROOT / "data/disaster_scenario.json").read_text())
    ids = {s["shipment_id"] for s in ships}
    assert len(ships) >= 400 and len(events) >= 55
    assert all(s["origin"] in CITIES and s["destination"] in CITIES and s["warehouse_checkpoint"] in HUBS for s in ships)
    assert all(set(e["affected_shipments"]) <= ids for e in events)
    assert {"sea", "air", "rail", "road"} <= {s["mode"] for s in ships}


def test_every_scenario_is_resolvable():
    sim = LogisticsSimulator(seed=0)
    agent = SentinelAgent(kb=kb(), backend="rules")
    for scenario in list(sim.scenarios):
        event = sim.inject_event(scenario["event_id"])
        result = agent.investigate(event, sim.shipments, sim.active_events)
        assert result["actions"], scenario["event_id"]
        assert not [s for s in result["steps"] if s["observation"].get("status") == "error"], scenario["event_id"]


def test_sea_freight_cannot_use_road_carrier():
    sim = LogisticsSimulator(seed=0)
    sea = next(s for s in sim.shipments if s.get("mode") == "sea")
    tb = Toolbox(sim.shipments, [], kb())
    assert tb.reassign_carrier(sea["shipment_id"], "Speedy Haul")["status"] == "error"


def test_eval_harness_meets_baseline():
    report = evaluate.run(force_local=True)
    assert report["action_accuracy"] == 1.0 and report["hit@4"] >= 0.6  # TF-IDF baseline


def test_faiss_semantic_retrieval_beats_baseline():
    report = evaluate.run(force_local=False)
    assert report["backend"] == "faiss" and report["hit@4"] >= 0.8 and report["action_accuracy"] == 1.0


def test_graph_runs_retrieve_agent_tools():
    from src.agent import build_graph, _make_llm
    sim = LogisticsSimulator(seed=0)
    event = sim.inject_event("EVT-8007")
    box = Toolbox(sim.shipments, sim.active_events, kb())
    graph = build_graph(_make_llm("rules", sim.shipments), box, kb())
    out = graph.invoke({"messages": [], "event": event, "policies": []})
    assert out["policies"] and out["messages"][-1].name == "finish"


def test_api_flow():
    from fastapi.testclient import TestClient
    from src.server import app
    c = TestClient(app)
    c.post("/api/reset")
    state = c.post("/api/inject", json={"event_id": "EVT-8003"}).json()
    assert state["investigations"] and state["events"][0]["handled"]
    assert c.post("/api/search", json={"query": "carrier strike"}).json()["results"]


def test_hub_capabilities_and_reroute_guardrail():
    from src.geo import hub_accepts
    assert hub_accepts("sea", "Rotterdam Gateway") and not hub_accepts("sea", "Omaha Relay")
    assert hub_accepts("air", "Frankfurt Air Hub") and not hub_accepts("air", "Suez Canal Hub")
    sim = LogisticsSimulator(seed=0)
    sea = next(s for s in sim.shipments if s.get("mode") == "sea")
    tb = Toolbox(sim.shipments, [], kb())
    assert tb.reroute_shipment(sea["shipment_id"], "Omaha Relay")["status"] == "error"


def test_sea_route_stays_on_water():
    import numpy as np
    from src import routing
    path = routing.sea_route(routing.point_of("Shanghai Yangshan"), routing.point_of("Long Beach Gateway"),
                             "Shanghai Yangshan", "Long Beach Gateway")
    assert path and len(path) > 20
    ocean = routing._ocean()
    on_water = [bool(ocean[routing._cell(tuple(p))]) for p in path[2:-2]]
    assert sum(on_water) / len(on_water) > 0.98


def test_sea_route_uses_suez_canal():
    from src import routing
    path = routing.sea_route(routing.point_of("Dubai Jebel Ali"), routing.point_of("Rotterdam Gateway"),
                             "Dubai Jebel Ali", "Rotterdam Gateway")
    assert any(abs(p[1] - 32.35) < 0.4 and 29.9 < p[0] < 31.4 for p in path)  # passes through the canal, not around Africa


def test_rail_and_feeder_legs():
    from src import routing
    assert routing.leg_mode("sea", "Atlanta, GA", "Savannah Port") == "road"   # inland feeder
    assert routing.leg_mode("sea", "Shanghai Yangshan", "Los Angeles, CA") == "sea"
    legs = routing.shipment_route("Sao Paulo, Brazil", "Panama Colon Hub", "Los Angeles, CA", "sea")
    assert [l["mode"] for l in legs] == ["road", "sea", "sea"]                  # via Santos
    rail = routing.rail_route(routing.point_of("Shanghai, China"), routing.point_of("Istanbul Gateway"))
    assert any(abs(p[0] - 43.24) < 1.5 and abs(p[1] - 76.89) < 1.5 for p in rail)  # passes Almaty


def test_india_coverage():
    import json
    from src.rag import ROOT
    ships = json.loads((ROOT / "data/shipment_data.json").read_text())
    india = [s for s in ships if s["origin"].endswith("India") or s["destination"].endswith("India")]
    assert len(india) >= 200
    assert {"sea", "air", "rail", "road"} <= {s["mode"] for s in india}
    assert all(s.get("shipped_at") and s.get("planned_eta") for s in ships)


def test_clock_delivers_shipments_and_dispatches_new_ones():
    sim = LogisticsSimulator(seed=0)
    before = len(sim.shipments)
    for _ in range(6):
        sim.simulate_step()
    assert any(s["status"] == "DELIVERED" for s in sim.shipments)
    assert max(int(s["shipment_id"][4:]) for s in sim.shipments) >= 2000 + before - 30  # new ids were issued
    assert sim.clock > sim.start


def test_node_dashboard_api():
    from fastapi.testclient import TestClient
    from src.server import app
    c = TestClient(app)
    c.post("/api/reset")
    c.post("/api/inject", json={"event_id": "EVT-9101"})
    d = c.post("/api/node", json={"kind": "city", "name": "Chennai, India"}).json()
    assert d["node"]["name"] == "Chennai, India" and d["kpis"]["total"] > 10
    row = d["shipments"][0]
    assert {"shipped_at", "planned_eta", "current_eta", "legs", "history", "progress", "delay_h"} <= set(row)
    assert any(i["type"] == "Cyclone" for i in d["incidents"])
    hub = c.post("/api/node", json={"kind": "hub", "name": "Delhi ICD Tughlakabad"}).json()
    assert hub["node"]["type"] and hub["kpis"]["total"] > 0
