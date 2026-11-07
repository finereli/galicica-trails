"""Fetch OSM data the build needs and cache it in data/: named places near the trails, the park guideposts,
and the G-6 route relation (the one trail where OSM beats the park's own line).

    python3 tools/fetch_osm.py
"""
import json, os, time, urllib.request, urllib.parse
D = os.path.join(os.path.dirname(__file__), "..", "data")
UA = {"User-Agent": "galicica-trails/1.0 (https://galicica.finereli.com)", "Accept": "*/*"}
BBOX = "40.89,20.72,41.15,21.0"  # s,w,n,e around every park trail

def overpass(q):
    for i in range(6):
        for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(), headers=UA)
                return json.load(urllib.request.urlopen(req, timeout=180))["elements"]
            except Exception as e:
                print("retry", url, e); time.sleep(5 * (i + 1))
    raise SystemExit("Overpass failed")

def osm_api(path):
    for i in range(5):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request("https://api.openstreetmap.org/api/0.6/" + path, headers=UA), timeout=60))["elements"]
        except Exception as e:
            print("retry", path, e); time.sleep(3 * (i + 1))
    raise SystemExit("OSM API failed: " + path)

def main():
    q = f"""[out:json][timeout:170];
(
  node[place~"^(town|village|hamlet|locality|isolated_dwelling)$"][name]({BBOX});
  node[natural~"^(peak|saddle|spring|cave_entrance)$"][name]({BBOX});
  node[mountain_pass=yes][name]({BBOX});
  nwr[tourism~"^(alpine_hut|wilderness_hut|viewpoint|camp_site|picnic_site)$"][name]({BBOX});
  nwr[amenity~"^(place_of_worship|shelter|drinking_water)$"][name]({BBOX});
  nwr[historic][name]({BBOX});
  node[tourism=information][information~"^(guidepost|board|map)$"]({BBOX});
);
out center tags;"""
    els = overpass(q)
    pois = []
    for e in els:
        lat = e.get("lat", e.get("center", {}).get("lat")); lon = e.get("lon", e.get("center", {}).get("lon"))
        if lat is None: continue
        pois.append({"id": f"{e['type']}/{e['id']}", "lat": lat, "lon": lon, "tags": e.get("tags", {})})
    json.dump(pois, open(os.path.join(D, "osm-pois.json"), "w"), ensure_ascii=False, indent=0)
    print(len(pois), "POIs")
    rel = osm_api("relation/7330532/full.json")
    json.dump(rel, open(os.path.join(D, "osm-g6.json"), "w"), ensure_ascii=False)
    print("G-6 relation", len(rel), "elements")

if __name__ == "__main__":
    main()
