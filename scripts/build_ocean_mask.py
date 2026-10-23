"""
Build data/ocean_mask.npz (0.25 degree ocean grid) from Natural Earth 50m land.

    python scripts/build_ocean_mask.py path/to/ne_50m_land.geojson

Needs shapely (build-time only). Land is shrunk by ~8 km so narrow straits
(Gibraltar, Dover, Malacca...) stay navigable at grid resolution.
"""

import json
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.ops import unary_union

GRID = 0.25
OUT = Path(__file__).resolve().parent.parent / "data" / "ocean_mask.npz"

geo = json.loads(Path(sys.argv[1]).read_text())
land = unary_union([shape(f["geometry"]) for f in geo["features"]])
land = land.buffer(-0.07)  # open narrow straits
shapely.prepare(land)

lats = -90 + (np.arange(int(180 / GRID)) + 0.5) * GRID
lngs = -180 + (np.arange(int(360 / GRID)) + 0.5) * GRID
LG, LT = np.meshgrid(lngs, lats)
is_land = shapely.contains_xy(land, LG.ravel(), LT.ravel()).reshape(LT.shape)
ocean = ~is_land
ocean[lats > 80] = False   # no polar shipping
ocean[lats < -68] = False  # Antarctic coast
np.savez_compressed(OUT, ocean=ocean)
print(OUT, ocean.shape, f"{ocean.mean():.0%} ocean")
