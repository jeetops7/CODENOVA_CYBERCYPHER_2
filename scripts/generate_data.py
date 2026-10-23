"""
Regenerate the global demo dataset (deterministic, seed 42).

    python scripts/generate_data.py

Keeps the 30 hand-written SHP-10xx shipments and EVT-80xx scenarios, and adds
~100 shipments on real global lanes (sea / air / rail / road) plus ~28
worldwide disruption scenarios whose affected shipments are picked from the
lanes that actually pass through the disrupted hub or use the struck carrier.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
rng = random.Random(42)

CARRIERS = {
    "FastLine Express": {"road", "air"}, "Global Logistics": {"road", "sea"}, "Speedy Haul": {"road"},
    "RouteMasters": {"road", "rail"}, "TransOcean Freight": {"sea"}, "Pacific Bridge Lines": {"sea"},
    "AeroLink Cargo": {"air"}, "EuroRail Cargo": {"rail", "road"}, "SilkRoad Logistics": {"rail", "sea", "road"},
    "Bharat Freightways": {"road"}, "IndiaLink Logistics": {"road", "rail"},
    "Coastal Lines India": {"sea"}, "SkyBridge Air Cargo": {"air"},
}
INDIAN = {"Bharat Freightways", "IndiaLink Logistics", "Coastal Lines India", "SkyBridge Air Cargo"}
NOW = datetime(2026, 3, 9, 12)  # data is authored relative to this instant; the simulator re-bases it to the present
CARGO = {
    "sea": ["Consumer goods", "Auto parts", "Machinery", "Apparel", "Electronics", "Semiconductors"],
    "air": ["Pharmaceuticals", "Vaccines", "Semiconductors", "Perishables", "Electronics", "Medical devices"],
    "rail": ["Auto parts", "Machinery", "Consumer goods", "Electronics"],
    "road": ["Consumer goods", "Perishables", "Auto parts", "Pharmaceuticals", "Machinery", "Apparel"],
}
SLA = {"sea": [336, 480, 720], "air": [24, 48, 72, 96], "rail": [120, 168, 240], "road": [24, 48, 72, 96]}

# (origin, destination, mode, checkpoint hub)
LANES = [
    ("Shanghai, China", "Los Angeles, CA", "sea", "Shanghai Yangshan"),
    ("Shenzhen, China", "Seattle, WA", "sea", "Shenzhen Yantian"),
    ("Shanghai, China", "Rotterdam, Netherlands", "sea", "Suez Canal Hub"),
    ("Mumbai, India", "Hamburg, Germany", "sea", "Suez Canal Hub"),
    ("Singapore, Singapore", "London, UK", "sea", "Suez Canal Hub"),
    ("Dubai, UAE", "Rotterdam, Netherlands", "sea", "Dubai Jebel Ali"),
    ("Busan, South Korea", "Los Angeles, CA", "sea", "Busan Terminal"),
    ("Tokyo, Japan", "Vancouver, Canada", "sea", "Tokyo Bay Hub"),
    ("Singapore, Singapore", "Sydney, Australia", "sea", "Singapore Strait Hub"),
    ("Jakarta, Indonesia", "Rotterdam, Netherlands", "sea", "Singapore Strait Hub"),
    ("Mumbai, India", "London, UK", "sea", "Mumbai Nhava Sheva"),
    ("Dubai, UAE", "Nairobi, Kenya", "sea", "Mombasa Gateway"),
    ("Mumbai, India", "Nairobi, Kenya", "sea", "Mombasa Gateway"),
    ("Rotterdam, Netherlands", "New York, NY", "sea", "Rotterdam Gateway"),
    ("Hamburg, Germany", "Boston, MA", "sea", "Hamburg Port"),
    ("Hamburg, Germany", "Shanghai, China", "sea", "Hamburg Port"),
    ("Sao Paulo, Brazil", "Rotterdam, Netherlands", "sea", "Santos Port Hub"),
    ("Sao Paulo, Brazil", "Shanghai, China", "sea", "Santos Port Hub"),
    ("Shenzhen, China", "New York, NY", "sea", "Panama Colon Hub"),
    ("Sao Paulo, Brazil", "Los Angeles, CA", "sea", "Panama Colon Hub"),
    ("Johannesburg, South Africa", "Rotterdam, Netherlands", "sea", "Cape Town Hub"),
    ("Lagos, Nigeria", "Rotterdam, Netherlands", "sea", "Lagos Apapa Hub"),
    ("London, UK", "Lagos, Nigeria", "sea", "Lagos Apapa Hub"),
    ("Atlanta, GA", "Hamburg, Germany", "sea", "Savannah Port"),
    ("Atlanta, GA", "Rotterdam, Netherlands", "sea", "Savannah Port"),
    ("Mexico City, Mexico", "Shanghai, China", "sea", "Manzanillo Port"),
    ("Tokyo, Japan", "Mexico City, Mexico", "sea", "Manzanillo Port"),
    ("Toronto, Canada", "Shanghai, China", "sea", "Vancouver Gateway"),
    ("Vancouver, Canada", "Tokyo, Japan", "sea", "Vancouver Gateway"),
    ("Los Angeles, CA", "Tokyo, Japan", "sea", "Long Beach Gateway"),
    ("Shanghai, China", "Chicago, IL", "sea", "Long Beach Gateway"),
    ("Sydney, Australia", "Singapore, Singapore", "sea", "Sydney Botany Hub"),
    ("Hong Kong, China", "Frankfurt, Germany", "air", "Hong Kong Air Hub"),
    ("Hong Kong, China", "Chicago, IL", "air", "Hong Kong Air Hub"),
    ("Shenzhen, China", "Los Angeles, CA", "air", "Hong Kong Air Hub"),
    ("Frankfurt, Germany", "New York, NY", "air", "Frankfurt Air Hub"),
    ("Delhi, India", "Frankfurt, Germany", "air", "Frankfurt Air Hub"),
    ("Frankfurt, Germany", "Tokyo, Japan", "air", "Frankfurt Air Hub"),
    ("Shanghai, China", "Chicago, IL", "air", "Anchorage Air Hub"),
    ("Tokyo, Japan", "New York, NY", "air", "Anchorage Air Hub"),
    ("Seoul, South Korea", "Dallas, TX", "air", "Anchorage Air Hub"),
    ("Mumbai, India", "London, UK", "air", "Dubai Jebel Ali"),
    ("Delhi, India", "Johannesburg, South Africa", "air", "Dubai Jebel Ali"),
    ("London, UK", "New York, NY", "air", "London Thames Hub"),
    ("Paris, France", "Boston, MA", "air", "London Thames Hub"),
    ("Istanbul, Turkey", "Lagos, Nigeria", "air", "Istanbul Gateway"),
    ("Shanghai, China", "Frankfurt, Germany", "rail", "Istanbul Gateway"),
    ("Shenzhen, China", "Hamburg, Germany", "rail", "Istanbul Gateway"),
    ("Milan, Italy", "Rotterdam, Netherlands", "rail", "Frankfurt Air Hub"),
    ("Madrid, Spain", "Hamburg, Germany", "rail", "Frankfurt Air Hub"),
    ("Paris, France", "Frankfurt, Germany", "rail", "Frankfurt Air Hub"),
    ("Mexico City, Mexico", "Dallas, TX", "road", "Dallas Center"),
    ("Toronto, Canada", "Chicago, IL", "road", "Chicago Transit"),
    ("Vancouver, Canada", "Seattle, WA", "road", "Vancouver Gateway"),
    ("Johannesburg, South Africa", "Cape Town, South Africa", "road", "Cape Town Hub"),
    ("Delhi, India", "Mumbai, India", "road", "Mumbai Nhava Sheva"),
    ("Bangkok, Thailand", "Singapore, Singapore", "road", "Singapore Strait Hub"),
    ("Melbourne, Australia", "Sydney, Australia", "road", "Sydney Botany Hub"),
    ("Nairobi, Kenya", "Mombasa, Kenya", "road", "Mombasa Gateway"),
    ("Hong Kong, China", "Shenzhen, China", "road", "Shenzhen Yantian"),
]

# India: domestic road + rail (incl. dedicated freight corridors), coastal ports, air cargo
INDIA_LANES = [
    ("Delhi, India", "Mumbai, India", "road", "Jaipur Dry Port"),
    ("Mumbai, India", "Delhi, India", "road", "Ahmedabad Logistics Hub"),
    ("Pune, India", "Bengaluru, India", "road", "Pune Logistics Hub"),
    ("Hyderabad, India", "Nagpur, India", "road", "Nagpur Multimodal Hub"),
    ("Nagpur, India", "Mumbai, India", "road", "Nagpur Multimodal Hub"),
    ("Lucknow, India", "Delhi, India", "road", "Delhi ICD Tughlakabad"),
    ("Kanpur, India", "Delhi, India", "road", "Delhi ICD Tughlakabad"),
    ("Ludhiana, India", "Delhi, India", "road", "Ludhiana Dry Port"),
    ("Kolkata, India", "Guwahati, India", "road", "Guwahati Gateway Hub"),
    ("Coimbatore, India", "Kochi, India", "road", "Kochi Vallarpadam Hub"),
    ("Surat, India", "Mumbai, India", "road", "Mumbai Nhava Sheva"),
    ("Indore, India", "Mumbai, India", "road", "Mumbai Nhava Sheva"),
    ("Bengaluru, India", "Chennai, India", "road", "Chennai Port Hub"),
    ("Chennai, India", "Hyderabad, India", "road", "Chennai Port Hub"),
    ("Jaipur, India", "Ahmedabad, India", "road", "Ahmedabad Logistics Hub"),
    ("Delhi, India", "Ahmedabad, India", "rail", "Jaipur Dry Port"),
    ("Ahmedabad, India", "Delhi, India", "rail", "Jaipur Dry Port"),
    ("Mumbai, India", "Delhi, India", "rail", "Ahmedabad Logistics Hub"),
    ("Kolkata, India", "Delhi, India", "rail", "Delhi ICD Tughlakabad"),
    ("Chennai, India", "Delhi, India", "rail", "Nagpur Multimodal Hub"),
    ("Bengaluru, India", "Mumbai, India", "rail", "Pune Logistics Hub"),
    ("Ludhiana, India", "Mumbai, India", "rail", "Delhi ICD Tughlakabad"),
    ("Nagpur, India", "Chennai, India", "rail", "Nagpur Multimodal Hub"),
    ("Ahmedabad, India", "Dubai, UAE", "sea", "Mundra Port Hub"),
    ("Delhi, India", "Rotterdam, Netherlands", "sea", "Mundra Port Hub"),
    ("Dubai, UAE", "Mumbai, India", "sea", "Mundra Port Hub"),
    ("Surat, India", "Hamburg, Germany", "sea", "Mundra Port Hub"),
    ("Pune, India", "New York, NY", "sea", "Mumbai Nhava Sheva"),
    ("Mumbai, India", "Singapore, Singapore", "sea", "Mumbai Nhava Sheva"),
    ("Chennai, India", "Singapore, Singapore", "sea", "Chennai Port Hub"),
    ("Chennai, India", "Hamburg, Germany", "sea", "Chennai Port Hub"),
    ("Bengaluru, India", "Los Angeles, CA", "sea", "Chennai Port Hub"),
    ("Hyderabad, India", "Rotterdam, Netherlands", "sea", "Chennai Port Hub"),
    ("Shanghai, China", "Chennai, India", "sea", "Chennai Port Hub"),
    ("Kolkata, India", "Singapore, Singapore", "sea", "Kolkata Haldia Hub"),
    ("Singapore, Singapore", "Kolkata, India", "sea", "Kolkata Haldia Hub"),
    ("Visakhapatnam, India", "Shanghai, China", "sea", "Visakhapatnam Port Hub"),
    ("Hyderabad, India", "Tokyo, Japan", "sea", "Visakhapatnam Port Hub"),
    ("Kochi, India", "Dubai, UAE", "sea", "Kochi Vallarpadam Hub"),
    ("Kochi, India", "London, UK", "sea", "Kochi Vallarpadam Hub"),
    ("Coimbatore, India", "Rotterdam, Netherlands", "sea", "Kochi Vallarpadam Hub"),
    ("Delhi, India", "Frankfurt, Germany", "air", "Delhi Air Cargo Hub"),
    ("Delhi, India", "New York, NY", "air", "Delhi Air Cargo Hub"),
    ("Delhi, India", "Mumbai, India", "air", "Delhi Air Cargo Hub"),
    ("Mumbai, India", "London, UK", "air", "Mumbai Air Cargo Hub"),
    ("Mumbai, India", "Dubai, UAE", "air", "Mumbai Air Cargo Hub"),
    ("Mumbai, India", "Bengaluru, India", "air", "Mumbai Air Cargo Hub"),
    ("Bengaluru, India", "Singapore, Singapore", "air", "Bengaluru Air Cargo Hub"),
    ("Bengaluru, India", "San Francisco, CA", "air", "Bengaluru Air Cargo Hub"),
    ("Hyderabad, India", "London, UK", "air", "Hyderabad Air Cargo Hub"),
    ("Hyderabad, India", "Delhi, India", "air", "Hyderabad Air Cargo Hub"),
    ("Chennai, India", "Frankfurt, Germany", "air", "Chennai Air Cargo Hub"),
    ("Kolkata, India", "Hong Kong, China", "air", "Kolkata Air Cargo Hub"),
]
LANES = [l for l in LANES if l[1] != "Mombasa, Kenya"]  # Mombasa is a hub, not a city entry


def load(name):
    return json.loads((DATA / name).read_text())


def times(sla, delayed):
    """shipped_at / planned_eta / current_eta relative to NOW (shipment is part-way through its journey)."""
    total = sla * rng.uniform(0.8, 1.0)
    done = rng.uniform(0.1, 0.9)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    planned = NOW + timedelta(hours=(1 - done) * total)
    current = planned + timedelta(hours=rng.randint(6, 48)) if delayed else planned
    return {"shipped_at": fmt(NOW - timedelta(hours=done * total)), "planned_eta": fmt(planned), "current_eta": fmt(current)}


def build_shipments():
    base = [s for s in load("shipment_data.json") if int(s["shipment_id"][4:]) < 2000]
    for i, s in enumerate(base):
        s.setdefault("mode", "road")
        s.setdefault("cargo", CARGO["road"][i % len(CARGO["road"])])
        s.update(times(s["sla_hours"], s["status"] == "DELAYED"))
    out, n = list(base), 2001
    pool = LANES * 3 + INDIA_LANES * 4
    rng.shuffle(pool)
    for origin, dest, mode, hub in pool:
        india = origin.endswith("India") or dest.endswith("India")
        compatible = [c for c, m in CARRIERS.items() if mode in m]
        pref = [c for c in compatible if (c in INDIAN) == india] if india and rng.random() < 0.65 else compatible
        carrier = rng.choice(pref or compatible)
        roll = rng.random()
        status = "DELAYED" if roll < 0.08 else "AT_CHECKPOINT" if roll < 0.26 else "IN_TRANSIT"
        sla = rng.choice(SLA[mode])
        out.append({
            "shipment_id": f"SHP-{n}", "origin": origin, "destination": dest,
            "carrier": carrier, "warehouse_checkpoint": hub, "status": status, "sla_hours": sla,
            "mode": mode, "cargo": rng.choice(CARGO[mode]), **times(sla, status == "DELAYED"),
        })
        n += 1
    return out


# (type, severity, location hub, description, selector, extra fields)
HUB = lambda h, n=10, mode=None: ("hub", h, n, mode)
CAR = lambda c, n=12: ("carrier", c, n, None)
EVENTS = [
    ("Typhoon", "HIGH", "Shanghai Yangshan", "Typhoon landfall near Shanghai; Yangshan deep-water terminals suspended for 36 hours.", HUB("Shanghai Yangshan"), {"region": "Asia-Pacific"}),
    ("Typhoon", "HIGH", "Busan Terminal", "Super typhoon tracking toward the Korean peninsula; terminal cranes locked down.", HUB("Busan Terminal"), {"region": "Asia-Pacific"}),
    ("Canal Disruption", "CRITICAL", "Suez Canal Hub", "Container vessel grounded in the Suez Canal; transit blocked in both directions.", HUB("Suez Canal Hub", 14), {"region": "Middle East"}),
    ("Canal Disruption", "MEDIUM", "Panama Colon Hub", "Drought restrictions cut Panama Canal daily transits by 40%.", HUB("Panama Colon Hub"), {"region": "Americas"}),
    ("Port Congestion", "MEDIUM", "Rotterdam Gateway", "Berth waiting times exceed 4 days after record import volumes.", HUB("Rotterdam Gateway"), {"region": "Europe"}),
    ("Port Strike", "HIGH", "Hamburg Port", "Dockworkers begin a 48-hour strike; container terminals halted.", HUB("Hamburg Port"), {"region": "Europe"}),
    ("Port Strike", "HIGH", "Long Beach Gateway", "Longshore labor action slows all vessel unloading at Long Beach.", HUB("Long Beach Gateway"), {"region": "Americas"}),
    ("Rail Strike", "HIGH", "Frankfurt Air Hub", "EuroRail Cargo locomotive drivers strike across Germany, Poland and Italy.", CAR("EuroRail Cargo"), {"region": "Europe", "carrier": "EuroRail Cargo"}),
    ("Airspace Closure", "HIGH", "Dubai Jebel Ali", "Regional airspace closure grounds all air freight through Dubai.", HUB("Dubai Jebel Ali", 10, "air"), {"region": "Middle East"}),
    ("Volcanic Ash", "MEDIUM", "London Thames Hub", "Ash cloud over the North Atlantic closes UK and Benelux air corridors.", HUB("London Thames Hub"), {"region": "Europe"}),
    ("Flooding", "HIGH", "Mumbai Nhava Sheva", "Monsoon flooding inundates road access to Nhava Sheva port.", HUB("Mumbai Nhava Sheva"), {"region": "South Asia"}),
    ("Earthquake", "CRITICAL", "Tokyo Bay Hub", "Magnitude 7.1 earthquake damages Tokyo Bay terminals; inspections underway.", HUB("Tokyo Bay Hub"), {"region": "Asia-Pacific"}),
    ("Cyber Attack", "CRITICAL", "Singapore Strait Hub", "Ransomware takes down the terminal operating system at Singapore Strait.", HUB("Singapore Strait Hub", 12), {"region": "Asia-Pacific"}),
    ("Cold Chain Failure", "HIGH", "Lagos Apapa Hub", "Grid outage knocks out cold storage at Apapa; temperature excursion risk for sensitive cargo.", HUB("Lagos Apapa Hub"), {"region": "Africa"}),
    ("Piracy Risk", "MEDIUM", "Mombasa Gateway", "Piracy advisory issued for the western Indian Ocean; insurers raising war-risk cover.", HUB("Mombasa Gateway"), {"region": "Africa"}),
    ("Customs Hold", "MEDIUM", "Santos Port Hub", "Customs inspection backlog at Santos holds containers for documentation review.", HUB("Santos Port Hub"), {"region": "Americas"}),
    ("Sanctions Hold", "HIGH", "Istanbul Gateway", "Compliance review freezes consignments linked to a newly sanctioned entity.", HUB("Istanbul Gateway"), {"region": "Europe"}),
    ("Driver Shortage", "MEDIUM", "Dallas Center", "Speedy Haul reports an acute driver shortage across the US South.", CAR("Speedy Haul"), {"region": "Americas", "carrier": "Speedy Haul"}),
    ("Fuel Shortage", "MEDIUM", "Cape Town Hub", "Diesel shortage limits long-haul road freight out of Cape Town.", HUB("Cape Town Hub"), {"region": "Africa"}),
    ("Wildfire", "HIGH", "Vancouver Gateway", "Wildfire closes the Trans-Canada corridor and Vancouver rail yards.", HUB("Vancouver Gateway"), {"region": "Americas"}),
    ("Hurricane", "HIGH", "Savannah Port", "Category 3 hurricane forces closure of Savannah port and coastal highways.", HUB("Savannah Port"), {"region": "Americas"}),
    ("Severe Storm", "LOW", "Anchorage Air Hub", "Heavy snow delays transpacific cargo flights at Anchorage.", HUB("Anchorage Air Hub"), {"region": "Americas"}),
    ("Customs Hold", "LOW", "Sydney Botany Hub", "Biosecurity inspection delays containers at Botany.", HUB("Sydney Botany Hub"), {"region": "Asia-Pacific"}),
    ("Carrier Insolvency", "CRITICAL", "Singapore Strait Hub", "TransOcean Freight files for insolvency; its vessels are held at anchor worldwide.", CAR("TransOcean Freight", 14), {"region": "Global", "carrier": "TransOcean Freight"}),
    ("IT System Failure", "HIGH", "Frankfurt Air Hub", "Cargo handling system outage at Frankfurt; manual sorting only.", HUB("Frankfurt Air Hub", 12), {"region": "Europe"}),
    ("Warehouse Congestion", "MEDIUM", "Hong Kong Air Hub", "Peak-season air cargo backlog delays processing by 10 hours.", HUB("Hong Kong Air Hub"), {"region": "Asia-Pacific"}),
    ("Vehicle Breakdown", "LOW", "Manzanillo Port", "Reefer truck broke down on Highway 200 near Manzanillo; recovery under way.", HUB("Manzanillo Port", 2), {"region": "Americas"}),
    ("Port Closure", "HIGH", "Shenzhen Yantian", "Terminal closed for 24 hours after a crane collapse at Yantian.", HUB("Shenzhen Yantian"), {"region": "Asia-Pacific"}),
]
INDIA_EVENTS = [
    ("Cyclone", "HIGH", "Chennai Port Hub", "Cyclone landfall expected near Chennai; port operations suspended and trucks held back.", HUB("Chennai Port Hub", 12), {"region": "South Asia"}),
    ("Cyclone", "CRITICAL", "Kolkata Haldia Hub", "Severe cyclonic storm in the Bay of Bengal closes Haldia and the Hooghly channel.", HUB("Kolkata Haldia Hub", 12), {"region": "South Asia"}),
    ("Flooding", "HIGH", "Kochi Vallarpadam Hub", "Heavy rain floods roads around Kochi; container trucks cannot reach Vallarpadam.", HUB("Kochi Vallarpadam Hub", 12), {"region": "South Asia"}),
    ("Port Congestion", "MEDIUM", "Mundra Port Hub", "Vessel queue at Mundra exceeds 3 days after a surge of export bookings.", HUB("Mundra Port Hub", 12), {"region": "South Asia"}),
    ("Port Congestion", "MEDIUM", "Mumbai Nhava Sheva", "Yard utilisation at Nhava Sheva above 95%; gate-in delays of 20 hours.", HUB("Mumbai Nhava Sheva", 12), {"region": "South Asia"}),
    ("Customs Hold", "MEDIUM", "Chennai Port Hub", "Customs examination backlog at Chennai holds export containers for document checks.", HUB("Chennai Port Hub", 12), {"region": "South Asia"}),
    ("Customs Hold", "HIGH", "Delhi Air Cargo Hub", "Pharmaceutical consignments held at Delhi air cargo pending clearance paperwork.", HUB("Delhi Air Cargo Hub", 12), {"region": "South Asia"}),
    ("Track Blockage", "HIGH", "Ahmedabad Logistics Hub", "Flooding and a washed-out embankment block the Western DFC near Vadodara.", HUB("Ahmedabad Logistics Hub", 12), {"region": "South Asia"}),
    ("Carrier Strike", "HIGH", "Delhi ICD Tughlakabad", "Truckers' strike over fuel prices keeps the Bharat Freightways fleet off the road.", CAR("Bharat Freightways", 14), {"region": "South Asia", "carrier": "Bharat Freightways"}),
    ("Cold Chain Failure", "HIGH", "Delhi ICD Tughlakabad", "Heatwave power cuts disrupt cold storage at the Tughlakabad ICD.", HUB("Delhi ICD Tughlakabad", 12), {"region": "South Asia"}),
    ("Airspace Closure", "MEDIUM", "Delhi Air Cargo Hub", "Dense fog shuts the Delhi runway for 14 hours; cargo flights cancelled.", HUB("Delhi Air Cargo Hub", 12, "air"), {"region": "South Asia"}),
    ("IT System Failure", "HIGH", "Bengaluru Air Cargo Hub", "Cargo community system outage at Bengaluru; manual manifesting only.", HUB("Bengaluru Air Cargo Hub", 12), {"region": "South Asia"}),
    ("Port Strike", "HIGH", "Kolkata Haldia Hub", "Dock workers at Haldia begin a 48-hour strike over wage talks.", HUB("Kolkata Haldia Hub", 12), {"region": "South Asia"}),
    ("Driver Shortage", "MEDIUM", "Ludhiana Dry Port", "IndiaLink Logistics reports a driver shortage during the harvest season in Punjab.", CAR("IndiaLink Logistics", 12), {"region": "South Asia", "carrier": "IndiaLink Logistics"}),
    ("Severe Storm", "MEDIUM", "Guwahati Gateway Hub", "Heavy monsoon rain and landslides cut NH27 into the North East.", HUB("Guwahati Gateway Hub", 12), {"region": "South Asia"}),
    ("Warehouse Congestion", "MEDIUM", "Pune Logistics Hub", "Festival-season peak overloads the Pune hub; processing delayed by 14 hours.", HUB("Pune Logistics Hub", 12), {"region": "South Asia"}),
    ("Fuel Shortage", "MEDIUM", "Nagpur Multimodal Hub", "Diesel supply disruption across central India limits long-haul trucking from Nagpur.", HUB("Nagpur Multimodal Hub", 12), {"region": "South Asia"}),
    ("Piracy Risk", "MEDIUM", "Mundra Port Hub", "Navy advisory for the northern Arabian Sea raises war-risk premiums for vessels from Mundra.", HUB("Mundra Port Hub", 12, "sea"), {"region": "South Asia"}),
    ("Flooding", "MEDIUM", "Jaipur Dry Port", "Flash flooding closes the Delhi-Jaipur expressway for 18 hours.", HUB("Jaipur Dry Port", 12), {"region": "South Asia"}),
    ("Vehicle Breakdown", "LOW", "Pune Logistics Hub", "Reefer truck breakdown on the Mumbai-Pune Expressway; recovery vehicle dispatched.", HUB("Pune Logistics Hub", 2), {"region": "South Asia"}),
    ("Cyber Attack", "HIGH", "Mumbai Nhava Sheva", "Ransomware disrupts the terminal operating system at Nhava Sheva.", HUB("Mumbai Nhava Sheva", 12), {"region": "South Asia"}),
]
EVENTS += INDIA_EVENTS
DURATION = {"LOW": 5, "MEDIUM": 8, "HIGH": 11, "CRITICAL": 14}


def build_events(shipments):
    base = [e for e in load("disaster_scenario.json") if int(e["event_id"][4:]) < 9000]
    loc = {"EVT-8001": "Denver Hub", "EVT-8002": "Dallas Center", "EVT-8008": "Atlanta Sort"}
    for e in base:
        e.setdefault("region", "Americas")
        if e["event_id"] in loc:
            e["location"] = loc[e["event_id"]]
        if e["event_id"] == "EVT-8003":
            e["carrier"] = "RouteMasters"
    out = list(base)
    for i, (typ, sev, location, desc, (kind, key, limit, mode), extra) in enumerate(EVENTS, start=1):
        if i > len(EVENTS) - len(INDIA_EVENTS):
            i = i - (len(EVENTS) - len(INDIA_EVENTS)) + 100  # India scenarios are EVT-9101+
        if kind == "hub":
            ids = [s for s in shipments if s["warehouse_checkpoint"] == key and (not mode or s["mode"] == mode)]
        else:
            ids = [s for s in shipments if s["carrier"] == key]
        ids = [s["shipment_id"] for s in ids if s["status"] != "DELIVERED"][:limit]
        if not ids:
            raise SystemExit(f"No shipments for {typ} @ {location}")
        out.append({"event_id": f"EVT-{9000 + i}", "type": typ, "affected_shipments": ids, "severity": sev,
                    "description": desc, "location": location, **extra})
    for e in out:
        e.setdefault("duration_ticks", DURATION[e["severity"]])
    return out


if __name__ == "__main__":
    ships = build_shipments()
    events = build_events(ships)
    (DATA / "shipment_data.json").write_text(json.dumps(ships, indent=2) + "\n")
    (DATA / "disaster_scenario.json").write_text(json.dumps(events, indent=2) + "\n")
    print(f"{len(ships)} shipments, {len(events)} scenarios")
