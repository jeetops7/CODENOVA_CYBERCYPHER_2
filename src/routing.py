"""
Surface routing for the globe.

    sea   A* over a 0.25 degree ocean mask (Natural Earth coastlines) with the
          Suez and Panama canals added as gates, then line-of-sight smoothing
    road  OSRM driving geometry (cached); falls back to a straight line offline
    rail  shortest path over hand-built corridors (Silk Road / Middle Corridor,
          Trans-European lines)
    air   no path: the UI draws a great-circle arc

``shipment_route`` returns the two legs (origin -> hub, hub -> destination)
for a shipment as ``[{"mode", "path": [[lat, lng], ...]}]``.
"""

from __future__ import annotations

import heapq
import json
import math
import threading
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .geo import CITIES, COASTAL_CITIES, HUBS, PORT_HUBS

ROOT = Path(__file__).resolve().parent.parent
BASE_CACHE = ROOT / "data" / "routes.json"
RUNTIME_CACHE = ROOT / ".cache" / "routes.json"
MASK_FILE = ROOT / "data" / "ocean_mask.npz"
GRID = 0.25
NY, NX = int(180 / GRID), int(360 / GRID)
Pt = Tuple[float, float]  # (lat, lng)

_lock = threading.Lock()
_cache: Dict[str, dict] = {}
_mask: Optional[np.ndarray] = None
_safe_mask: Optional[np.ndarray] = None


# ---------------------------------------------------------------- geometry
def _wrap(d: float) -> float:
    return ((d + 180) % 360) - 180


def gc_deg(a: Pt, b: Pt) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(_wrap(b[1] - a[1]))
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _vec(p: Pt):
    la, ln = math.radians(p[0]), math.radians(p[1])
    return np.array([math.cos(la) * math.cos(ln), math.cos(la) * math.sin(ln), math.sin(la)])


def interp(a: Pt, b: Pt, t: float) -> Pt:
    """Point at fraction t along the great circle a -> b."""
    va, vb = _vec(a), _vec(b)
    om = math.acos(max(-1.0, min(1.0, float(va @ vb))))
    if om < 1e-9:
        return a
    v = (math.sin((1 - t) * om) * va + math.sin(t * om) * vb) / math.sin(om)
    return (math.degrees(math.asin(max(-1.0, min(1.0, v[2])))), math.degrees(math.atan2(v[1], v[0])))


def densify(points: List[Pt], step: float = 1.5) -> List[List[float]]:
    out: List[List[float]] = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(gc_deg(a, b) / step))
        out += [list(interp(a, b, i / n)) for i in range(n)]
    out.append(list(points[-1]))
    return [[round(p[0], 4), round(p[1], 4)] for p in out]


# --------------------------------------------------------------- sea routing
SEA_GATES = [  # canals that are narrower than the grid: (name, entry a, exit b, polyline a -> b)
    {"name": "Suez", "a": (31.30, 32.33), "b": (29.93, 32.57),
     "via": [(31.20, 32.33), (30.90, 32.33), (30.46, 32.35), (30.00, 32.55)]},
    {"name": "Panama", "a": (9.37, -79.91), "b": (8.90, -79.53),
     "via": [(9.30, -79.92), (9.15, -79.78), (9.05, -79.63)]},
]
_VANCOUVER = [(49.29, -123.11), (49.20, -123.30), (49.00, -123.40), (48.75, -123.35), (48.50, -123.20), (48.35, -123.45),
              (48.30, -124.50), (48.45, -125.30)]
_HAMBURG = [(53.54, 9.97), (53.62, 9.50), (53.87, 8.75), (54.05, 8.10)]
_HALDIA = [(22.03, 88.07), (21.65, 88.12), (21.20, 88.25)]
_KOCHI = [(9.97, 76.26), (9.97, 76.23), (9.96, 76.19), (9.95, 76.05)]
_MUNDRA = [(22.74, 69.70), (22.65, 69.55), (22.45, 69.15), (22.25, 68.85)]
_TOKYO = [(35.62, 139.79), (35.40, 139.82), (35.20, 139.72), (34.90, 139.90)]
_YANTIAN = [(22.57, 114.28), (22.40, 114.35), (22.15, 114.40)]
_LONDON = [(51.50, 0.60), (51.48, 0.90), (51.55, 1.40), (51.60, 2.00)]
SEA_APPROACH = {  # river/bay ports whose approach is narrower than the grid (port -> open water)
    "Hamburg Port": _HAMBURG, "Hamburg, Germany": _HAMBURG,
    "Vancouver Gateway": _VANCOUVER, "Vancouver, Canada": _VANCOUVER,
    "Tokyo Bay Hub": _TOKYO, "Tokyo, Japan": _TOKYO,
    "Kolkata Haldia Hub": _HALDIA, "Kochi Vallarpadam Hub": _KOCHI, "Mundra Port Hub": _MUNDRA,
    "Shenzhen Yantian": _YANTIAN, "Shenzhen, China": _YANTIAN,
    "London Thames Hub": _LONDON, "London, UK": [(51.51, -0.10), (51.49, 0.30)] + _LONDON,
    "Seattle, WA": [(47.60, -122.36), (47.90, -122.45), (48.15, -122.70), (48.18, -123.10), (48.28, -123.80),
                    (48.40, -124.80), (48.45, -125.40)],
}


def _ocean() -> np.ndarray:
    global _mask
    if _mask is None:
        _mask = np.load(MASK_FILE)["ocean"]
    return _mask


def _safe() -> np.ndarray:
    """Ocean cells whose 8 neighbours are all ocean (keeps routes ~0.5 degrees off the coast)."""
    global _safe_mask
    if _safe_mask is None:
        m = _ocean()
        ok = m.copy()
        for _ in range(2):  # erode twice: ~0.5 degrees of clearance
            nxt = ok.copy()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    nxt &= np.roll(np.roll(ok, di, axis=0), dj, axis=1)
            ok = nxt
        ok[0, :] = ok[-1, :] = False
        _safe_mask = ok
    return _safe_mask


def _cell(p: Pt) -> Tuple[int, int]:
    return min(NY - 1, max(0, int((p[0] + 90) / GRID))), int(((p[1] + 180) % 360) / GRID) % NX


def _center(c: Tuple[int, int]) -> Pt:
    return (-90 + (c[0] + 0.5) * GRID, -180 + (c[1] + 0.5) * GRID)


def _nearest_ocean(p: Pt, max_cells: int = 120) -> Optional[Tuple[int, int]]:
    m = _ocean()
    i0, j0 = _cell(p)
    best, best_d = None, 1e9
    for r in range(0, max_cells):
        for i in range(max(0, i0 - r), min(NY - 1, i0 + r) + 1):
            for j in range(j0 - r, j0 + r + 1):
                if max(abs(i - i0), abs(j - j0)) != r:
                    continue
                jj = j % NX
                if m[i, jj]:
                    d = gc_deg(p, _center((i, jj)))
                    if d < best_d:
                        best, best_d = (i, jj), d
        if best is not None and r * GRID > best_d + 1:
            break
    return best


def _gate_links():
    links: Dict[Tuple[int, int], list] = {}
    for g in SEA_GATES:
        ca, cb = _nearest_ocean(g["a"]), _nearest_ocean(g["b"])
        length = sum(gc_deg(x, y) for x, y in zip([g["a"]] + g["via"], g["via"] + [g["b"]]))
        links.setdefault(ca, []).append((cb, length, g, False))
        links.setdefault(cb, []).append((ca, length, g, True))
    return links


_links: Optional[dict] = None


def _astar(start, goal):
    global _links
    if _links is None:
        _links = _gate_links()
    m, safe = _ocean(), _safe()
    goal_c = _center(goal)
    heap = [(0.0, 0.0, start)]
    g_cost, came = {start: 0.0}, {}
    while heap:
        _, g, cur = heapq.heappop(heap)
        if cur == goal:
            break
        if g > g_cost.get(cur, 1e18):
            continue
        ci = _center(cur)
        steps = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = cur[0] + di, (cur[1] + dj) % NX
                if 0 <= ni < NY and m[ni, nj]:
                    if di and dj and not (m[cur[0] + di, cur[1]] and m[cur[0], (cur[1] + dj) % NX]):
                        continue  # no squeezing diagonally between two land corners
                    nc = _center((ni, nj))
                    cos = math.cos(math.radians((ci[0] + nc[0]) / 2))
                    steps.append(((ni, nj), math.hypot(nc[0] - ci[0], _wrap(nc[1] - ci[1]) * cos) * (1.0 if safe[ni, nj] else 2.2), None))
        for other, cost, gate, rev in _links.get(cur, []):
            steps.append((other, cost, (gate, rev)))
        for nxt, cost, via in steps:
            ng = g + cost
            if ng < g_cost.get(nxt, 1e18):
                g_cost[nxt], came[nxt] = ng, (cur, via)
                heapq.heappush(heap, (ng + gc_deg(_center(nxt), goal_c), ng, nxt))
    if goal not in g_cost:
        return None
    path, cur = [], goal
    while cur != start:
        prev, via = came[cur]
        path.append((cur, via))
        cur = prev
    path.append((start, None))
    return list(reversed(path)), g_cost[goal]


def _clear(a: Pt, b: Pt, free: List[Pt]) -> bool:
    m = _safe()
    n = max(2, int(gc_deg(a, b) / 0.1))
    for k in range(1, n):
        p = interp(a, b, k / n)
        if any(gc_deg(p, f) < 0.9 for f in free):
            continue
        if not m[_cell(p)]:
            return False
    return True


def _simplify(pts: List[Tuple[Pt, bool]], free: List[Pt]) -> List[Pt]:
    """Line-of-sight smoothing that never drops pinned points (canals, approaches)."""
    out: List[Pt] = [pts[0][0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1:
            if all(not pinned for _, pinned in pts[i + 1:j]) and _clear(pts[i][0], pts[j][0], free):
                break
            j -= 1
        out.append(pts[j][0])
        i = j
    return out


def _sea_options(p: Pt, name: Optional[str], role: str):
    """Ways to attach an endpoint to the water graph: (anchor cell, points, extra cost)."""
    if name in SEA_APPROACH:
        pts = SEA_APPROACH[name] if role == "start" else SEA_APPROACH[name][::-1]
        cell = _nearest_ocean(pts[-1] if role == "start" else pts[0])
        return [(cell, pts, 0.0)]
    for g in SEA_GATES:  # endpoint sits inside a canal: enter via either end
        chain = [g["a"]] + g["via"] + [g["b"]]
        k = min(range(len(chain)), key=lambda x: gc_deg(chain[x], p))
        if gc_deg(chain[k], p) < 0.15:
            to_a, to_b = chain[:k + 1][::-1], chain[k:]
            opts = []
            for seg, end in ((to_a, g["a"]), (to_b, g["b"])):
                seg = [p] + seg[1:] if seg else [p]
                cost = sum(gc_deg(x, y) for x, y in zip(seg, seg[1:]))
                opts.append((_nearest_ocean(end), seg if role == "start" else seg[::-1], cost))
            return opts
    return [(_nearest_ocean(p), [p], 0.0)]


def sea_route(a: Pt, b: Pt, a_name: Optional[str] = None, b_name: Optional[str] = None) -> Optional[List[List[float]]]:
    best = None
    for sc, spts, sc_cost in _sea_options(a, a_name, "start"):
        for gc_, gpts, gc_cost in _sea_options(b, b_name, "goal"):
            if sc is None or gc_ is None:
                continue
            res = _astar(sc, gc_)
            if res and (best is None or res[1] + sc_cost + gc_cost < best[0]):
                best = (res[1] + sc_cost + gc_cost, spts, res[0], gpts)
    if best is None:
        return None
    _, spts, cells, gpts = best
    seq: List[Tuple[Pt, bool]] = [(p, i > 0 or len(spts) > 1) for i, p in enumerate(spts)]
    seq[0] = (spts[0], False)
    for k, (cell, via) in enumerate(cells):
        if via:
            gate, rev = via
            chain = [gate["a"]] + gate["via"] + [gate["b"]]
            seq += [(p, True) for p in (chain[::-1] if rev else chain)]
        seq.append((_center(cell), False))
    seq += [(p, len(gpts) > 1 and i < len(gpts) - 1) for i, p in enumerate(gpts)]
    out = _simplify(seq, [a, b])
    return densify(out, 1.2)


# --------------------------------------------------------------- rail routing
RAIL_NODES: Dict[str, Pt] = {
    "Shanghai": (31.23, 121.47), "Nanjing": (32.06, 118.80), "Zhengzhou": (34.75, 113.65), "Xi'an": (34.27, 108.95),
    "Lanzhou": (36.06, 103.83), "Urumqi": (43.83, 87.62), "Khorgos": (44.20, 80.40), "Almaty": (43.24, 76.89),
    "Aktau": (43.65, 51.15), "Baku": (40.40, 49.87), "Tbilisi": (41.72, 44.80), "Kars": (40.60, 43.10),
    "Ankara": (39.93, 32.86), "Istanbul": (41.00, 28.97), "Sofia": (42.70, 23.32), "Belgrade": (44.80, 20.46),
    "Budapest": (47.50, 19.04), "Vienna": (48.21, 16.37), "Munich": (48.14, 11.58), "Frankfurt": (50.11, 8.68),
    "Shenzhen": (22.54, 114.06), "Guangzhou": (23.13, 113.26), "Changsha": (28.20, 112.97), "Wuhan": (30.59, 114.30),
    "Prague": (50.08, 14.44), "Berlin": (52.52, 13.40), "Hamburg": (53.55, 9.99), "Milan": (45.46, 9.19),
    "Como": (45.81, 9.08), "Lugano": (46.00, 8.95), "Lucerne": (47.05, 8.31), "Basel": (47.56, 7.59),
    "Karlsruhe": (49.01, 8.40), "Cologne": (50.94, 6.96), "Duisburg": (51.43, 6.76), "Rotterdam": (51.92, 4.48),
    "Madrid": (40.42, -3.70), "Zaragoza": (41.65, -0.89), "Barcelona": (41.39, 2.17), "Perpignan": (42.70, 2.90),
    "Lyon": (45.76, 4.84), "Strasbourg": (48.58, 7.75), "Hannover": (52.37, 9.73), "Paris": (48.86, 2.35),
    "Reims": (49.26, 4.03), "Metz": (49.12, 6.18), "Saarbrucken": (49.23, 7.00), "Mannheim": (49.49, 8.47),
    # India
    "Mumbai": (19.08, 72.88), "Surat": (21.17, 72.83), "Vadodara": (22.31, 73.18), "Ahmedabad": (23.02, 72.57),
    "Palanpur": (24.17, 72.43), "Gandhidham": (23.08, 70.13), "Radhanpur": (23.83, 71.60), "Jaipur": (26.91, 75.79),
    "Alwar": (27.56, 76.60), "Delhi": (28.61, 77.21), "Agra": (27.18, 78.01), "Ambala": (30.38, 76.78),
    "Ludhiana": (30.90, 75.86), "Kanpur": (26.45, 80.33), "Lucknow": (26.85, 80.95), "Prayagraj": (25.43, 81.85),
    "Mughalsarai": (25.28, 83.12), "Gaya": (24.80, 85.00), "Dhanbad": (23.80, 86.43), "Asansol": (23.68, 86.98),
    "Kolkata": (22.57, 88.36), "Jhansi": (25.45, 78.57), "Bhopal": (23.26, 77.41), "Itarsi": (22.61, 77.76),
    "Nagpur": (21.15, 79.09), "Balharshah": (19.85, 79.35), "Warangal": (17.97, 79.59), "Hyderabad": (17.39, 78.49),
    "Vijayawada": (16.51, 80.65), "Chennai": (13.08, 80.27), "Visakhapatnam": (17.69, 83.22), "Bhubaneswar": (20.30, 85.82),
    "Kharagpur": (22.34, 87.31), "Raipur": (21.25, 81.63), "Pune": (18.52, 73.86), "Solapur": (17.66, 75.91),
    "Guntakal": (15.17, 77.37), "Bengaluru": (12.97, 77.59), "Coimbatore": (11.02, 76.96), "Kochi": (9.93, 76.27),
    "Siliguri": (26.72, 88.43), "Guwahati": (26.14, 91.74),
}
RAIL_LINES = [
    ["Shanghai", "Nanjing", "Zhengzhou", "Xi'an", "Lanzhou", "Urumqi", "Khorgos", "Almaty", "Aktau", "Baku", "Tbilisi",
     "Kars", "Ankara", "Istanbul", "Sofia", "Belgrade", "Budapest", "Vienna", "Munich", "Frankfurt"],
    ["Shenzhen", "Guangzhou", "Changsha", "Wuhan", "Zhengzhou"],
    ["Vienna", "Prague", "Berlin", "Hamburg"],
    ["Milan", "Como", "Lugano", "Lucerne", "Basel", "Karlsruhe", "Frankfurt", "Cologne", "Duisburg", "Rotterdam"],
    ["Madrid", "Zaragoza", "Barcelona", "Perpignan", "Lyon", "Strasbourg", "Mannheim", "Frankfurt", "Hannover", "Hamburg"],
    ["Paris", "Reims", "Metz", "Saarbrucken", "Mannheim"],
    ["Duisburg", "Hannover"],
    # India: Western DFC, Mundra spur, Eastern DFC, Grand Trunk, southern and east-coast lines
    ["Mumbai", "Surat", "Vadodara", "Ahmedabad", "Palanpur", "Jaipur", "Alwar", "Delhi"],
    ["Gandhidham", "Radhanpur", "Palanpur"],
    ["Ludhiana", "Ambala", "Delhi", "Agra", "Kanpur", "Prayagraj", "Mughalsarai", "Gaya", "Dhanbad", "Asansol", "Kolkata"],
    ["Delhi", "Agra", "Jhansi", "Bhopal", "Itarsi", "Nagpur", "Balharshah", "Warangal", "Vijayawada", "Chennai"],
    ["Warangal", "Hyderabad", "Vijayawada"],
    ["Mumbai", "Pune", "Solapur", "Guntakal", "Bengaluru", "Chennai"],
    ["Chennai", "Vijayawada", "Visakhapatnam", "Bhubaneswar", "Kharagpur", "Kolkata"],
    ["Nagpur", "Raipur", "Kharagpur"],
    ["Bengaluru", "Coimbatore", "Kochi"],
    ["Kolkata", "Siliguri", "Guwahati"],
    ["Kanpur", "Lucknow"],
]


def rail_route(a: Pt, b: Pt) -> List[List[float]]:
    adj: Dict[str, List[Tuple[str, float]]] = {}
    for line in RAIL_LINES:
        for x, y in zip(line, line[1:]):
            d = gc_deg(RAIL_NODES[x], RAIL_NODES[y])
            adj.setdefault(x, []).append((y, d))
            adj.setdefault(y, []).append((x, d))
    near = lambda p: min(RAIL_NODES, key=lambda n: gc_deg(RAIL_NODES[n], p))
    s, g = near(a), near(b)
    dist, prev, heap = {s: 0.0}, {}, [(0.0, s)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == g:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, w in adj.get(u, []):
            if d + w < dist.get(v, 1e18):
                dist[v], prev[v] = d + w, u
                heapq.heappush(heap, (d + w, v))
    chain, cur = [g], g
    while cur != s and cur in prev:
        cur = prev[cur]
        chain.append(cur)
    pts = [a] + [RAIL_NODES[n] for n in reversed(chain)] + [b]
    return densify(pts, 0.6)


# --------------------------------------------------------------- road routing
ROAD_ANCHOR = {"Singapore Strait Hub": (1.29, 103.85)}


def road_route(a: Pt, b: Pt) -> Tuple[List[List[float]], bool]:
    url = (f"https://router.project-osrm.org/route/v1/driving/{a[1]:.5f},{a[0]:.5f};{b[1]:.5f},{b[0]:.5f}"
           "?overview=simplified&geometries=geojson")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
        coords = data["routes"][0]["geometry"]["coordinates"]
        pts = [(c[1], c[0]) for c in coords]
        return densify(pts, 0.25), False
    except Exception:
        return densify([a, b], 0.5), True  # offline / unroutable: straight line, flagged approximate


# ------------------------------------------------------------------- legs
def point_of(name: str) -> Pt:
    return CITIES.get(name) or HUBS[name]


def _water(name: str) -> bool:
    return name in PORT_HUBS or name in COASTAL_CITIES


def leg_mode(mode: str, a: str, b: str) -> str:
    if mode == "sea":
        return "sea" if _water(a) and _water(b) else "road"  # inland feeder legs go by road
    return mode


def _load_cache() -> None:
    if _cache:
        return
    for f in (BASE_CACHE, RUNTIME_CACHE):
        if f.exists():
            try:
                _cache.update(json.loads(f.read_text()))
            except Exception:
                pass


def _save_runtime(key: str, value: dict) -> None:
    RUNTIME_CACHE.parent.mkdir(exist_ok=True)
    try:
        existing = json.loads(RUNTIME_CACHE.read_text()) if RUNTIME_CACHE.exists() else {}
        existing[key] = value
        RUNTIME_CACHE.write_text(json.dumps(existing))
    except Exception:
        pass


def _km(path, a: Pt, b: Pt) -> int:
    pts = [tuple(p) for p in path] if path else [a, b]
    return int(sum(gc_deg(x, y) for x, y in zip(pts, pts[1:])) * 111.19)


def leg(mode: str, a_name: str, b_name: str) -> dict:
    """One leg between two named nodes; cached."""
    _load_cache()
    m = leg_mode(mode, a_name, b_name)
    key = f"{m}|{a_name}|{b_name}"
    with _lock:
        if key in _cache:
            return _cache[key]
    a, b = point_of(a_name), point_of(b_name)
    approx = False
    if m == "air":
        path = None
    elif m == "sea":
        path = sea_route(a, b, a_name, b_name)
        if path is None:
            path, approx = densify([a, b], 1.0), True
    elif m == "rail":
        path = rail_route(a, b)
    else:
        path, approx = road_route(ROAD_ANCHOR.get(a_name, a), ROAD_ANCHOR.get(b_name, b))
    value = {"mode": m, "path": path, "approx": approx, "km": _km(path, a, b)}
    with _lock:
        _cache[key] = value
        if not approx:
            _save_runtime(key, value)
    return value


FEEDER_PORT = {"Sao Paulo, Brazil": "Santos Port Hub", "Kolkata, India": "Kolkata Haldia Hub"}  # inland city -> the port it ships through


def shipment_route(origin: str, hub: str, dest: str, mode: str) -> List[dict]:
    """Legs origin -> hub -> destination; inland ends of sea freight get a road feeder to their port."""
    stops = [origin, hub, dest]
    if mode == "sea":
        if FEEDER_PORT.get(origin) not in (None, hub):
            stops.insert(1, FEEDER_PORT[origin])
        if FEEDER_PORT.get(dest) not in (None, hub):
            stops.insert(-1, FEEDER_PORT[dest])
    legs = []
    for a, b in zip(stops, stops[1:]):
        v = leg(mode, a, b)
        if "km" not in v:  # entries from older caches
            v = {**v, "km": _km(v.get("path"), point_of(a), point_of(b))}
        legs.append({**v, "from": a, "to": b})
    return legs
