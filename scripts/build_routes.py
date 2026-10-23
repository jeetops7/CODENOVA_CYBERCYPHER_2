"""
Precompute surface routes for every shipment lane into data/routes.json.

    python scripts/build_routes.py                      # build
    python scripts/build_routes.py --check land.geojson # also report sea legs that cross land

Road legs call the public OSRM demo server once per leg (results are cached in
the output file, so the app itself needs no network for the base lanes).
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import routing  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
ap = argparse.ArgumentParser()
ap.add_argument("--check", help="Natural Earth land GeoJSON to validate sea legs against")
args = ap.parse_args()

routing._cache.clear()
routing._load_cache = lambda: None  # build from scratch, ignore existing caches
ships = json.loads((DATA / "shipment_data.json").read_text())
lanes = sorted({(s["origin"], s["warehouse_checkpoint"], s["destination"], s["mode"]) for s in ships})
pairs = sorted({(routing.leg_mode(m, a, b), a, b, m) for o, h, d, m in lanes for a, b in ((o, h), (h, d))})
print(f"{len(lanes)} lanes -> {len(pairs)} legs")


def build(item):
    _, a, b, m = item
    routing.leg(m, a, b)


routing._save_runtime = lambda *a, **k: None
with ThreadPoolExecutor(6) as pool:
    list(pool.map(build, pairs))

out = {k: v for k, v in sorted(routing._cache.items())}
(DATA / "routes.json").write_text(json.dumps(out, separators=(",", ":")))
approx = [k for k, v in out.items() if v["approx"]]
print(f"wrote {len(out)} legs ({(DATA / 'routes.json').stat().st_size // 1024} KB); approximate: {len(approx)}")
for k in approx:
    print("  approx:", k)

if args.check:
    import shapely
    from shapely.affinity import translate
    from shapely.geometry import LineString, shape
    from shapely.ops import unary_union

    land = unary_union([shape(f["geometry"]) for f in json.loads(Path(args.check).read_text())["features"]])
    canals = unary_union([LineString([(p[1], p[0]) for p in [g["a"]] + g["via"] + [g["b"]]]).buffer(0.08) for g in routing.SEA_GATES])
    land = unary_union([land.difference(canals), translate(land.difference(canals), 360), translate(land.difference(canals), -360)])
    shapely.prepare(land)
    bad = []
    for k, v in out.items():
        if v["mode"] != "sea" or v["approx"] or len(v["path"]) < 4:
            continue
        lngs, prev = [], None
        for p in v["path"]:  # unwrap longitudes so antimeridian crossings stay continuous
            x = p[1]
            if prev is not None:
                while x - prev > 180:
                    x -= 360
                while x - prev < -180:
                    x += 360
            lngs.append(x)
            prev = x
        pts = [(x, p[0]) for x, p in zip(lngs, v["path"])]
        inner = LineString(pts[2:-2] if len(pts) > 6 else pts[1:-1])  # skip port approaches
        on_land = inner.intersection(land).length
        if on_land > 0.1:
            bad.append((round(on_land, 2), k))
    print(f"sea legs crossing land (>0.1 deg): {len(bad)} of {sum(1 for v in out.values() if v['mode'] == 'sea')}")
    for d, k in sorted(bad, reverse=True):
        print(f"  {d:5.2f} deg  {k}")
