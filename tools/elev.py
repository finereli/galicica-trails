"""SRTM 30 m elevations from opentopodata.org, cached in data/elev-cache.json so builds work offline."""
import json, os, time, urllib.request
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "elev-cache.json")
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

def key(a, b):
    return f"{a:.5f},{b:.5f}"

def elevations(pts):
    keys = [key(a, b) for a, b in pts]
    need = [k for k in dict.fromkeys(keys) if k not in cache]
    for i in range(0, len(need), 100):
        chunk = need[i:i + 100]
        u = "https://api.opentopodata.org/v1/srtm30m?locations=" + "|".join(chunk)
        for t in range(6):
            try:
                r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "galicica-trails/1.0"}), timeout=60)); break
            except Exception as e:
                print("retry", e); time.sleep(5 * (t + 1))
        else:
            raise SystemExit("opentopodata failed")
        for k, res in zip(chunk, r["results"]): cache[k] = res["elevation"]
        json.dump(cache, open(CACHE, "w"), separators=(",", ":")); time.sleep(1.1)
        print(f"elevations {i + len(chunk)}/{len(need)}", flush=True)
    return [cache[k] for k in keys]
