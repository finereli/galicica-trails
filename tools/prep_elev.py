"""Fill the elevation cache for every trail (densified to 50 m). Run once; the build then works offline."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from elev import elevations
from geo import densify
D = os.path.join(os.path.dirname(__file__), "..", "data")
park = json.load(open(os.path.join(D, "park-map-2020.json")))
pts = []
for t in park["tracks"]:
    if t["code"] != "ASVALT": pts += densify(t["coords"])
els = json.load(open(os.path.join(D, "osm-g6.json")))
pts += [(e["lat"], e["lon"]) for e in els if e["type"] == "node"]
print(len(pts), "points"); elevations(pts); print("done")
