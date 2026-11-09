"""Build the static site in site/ from data/. No network, no dependencies.

    python3 tools/build.py

Inputs (all in data/):
  park-map-2020.json   the park's own trail geometry and suggested routes (Wayback Machine copy, Oct 2020)
  routes-en.json       English names and translated descriptions of the suggested routes
  osm-pois.json        named places, peaks, springs, huts, guideposts near the trails (tools/fetch_osm.py)
  osm-g6.json          OSM relation 7330532, used for G-6 (the park drew its approach as a straight line)
  elev-cache.json      SRTM elevations (tools/prep_elev.py)
"""
import html, json, math, os, re, shutil, sys
from datetime import date
from xml.sax.saxutils import escape as xesc

sys.path.insert(0, os.path.dirname(__file__))
from geo import hav, densify, dist_to_line
import elev

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D, SITE = os.path.join(ROOT, "data"), os.path.join(ROOT, "site")
BASE = "https://galicica.finereli.com"
REPO = "https://github.com/finereli/galicica-trails"
TODAY = date.today().isoformat()

KINDS = {
    "H": dict(name="H trails", one="H trail", what="easier and shorter hiking trails", color="#C8202F", gpx="Red"),
    "T": dict(name="T trails", one="T trail", what="harder and longer hiking trails, with more climbing", color="#1F7A3D", gpx="DarkGreen"),
    "G": dict(name="G trails", one="G trail", what="high ridge trails above 1,600 m", color="#D4A20B", gpx="Yellow"),
    "MTB": dict(name="MTB trails", one="MTB trail", what="mountain bike trails, some of them handy links between hiking routes", color="#24357F", gpx="DarkBlue"),
}
ORDER = ["H", "T", "G", "MTB"]

# ---------------------------------------------------------------- helpers

def esc(s):
    return html.escape(str(s), quote=True)

CYR = dict(zip("абвгдѓежзѕијклљмнњопрстќуфхцчџш",
               ["a", "b", "v", "g", "d", "gj", "e", "zh", "z", "dz", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p", "r", "s", "t", "kj", "u", "f", "h", "c", "ch", "dzh", "sh"]))

def translit(s):
    out = ""
    for ch in s:
        lo = ch.lower()
        if lo in CYR:
            t = CYR[lo]; out += t.capitalize() if ch != lo else t
        else:
            out += ch
    return out

def fmt_km(m):
    return f"{m / 1000:.1f}"

def fmt_int(n):
    return f"{int(round(n)):,}"

def climb(eles, hyst=5):
    """Total ascent/descent with hysteresis, after light smoothing (SRTM is noisy)."""
    sm = [sum(eles[max(0, i - 1):i + 2]) / len(eles[max(0, i - 1):i + 2]) for i in range(len(eles))]
    up = down = 0; ref = sm[0]
    for e in sm[1:]:
        if e - ref >= hyst: up += e - ref; ref = e
        elif ref - e >= hyst: down += ref - e; ref = e
    return up, down

def write(path, text):
    p = os.path.join(SITE, path); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)

# ---------------------------------------------------------------- data

def load():
    park = json.load(open(os.path.join(D, "park-map-2020.json")))
    en = json.load(open(os.path.join(D, "routes-en.json")))
    pois_raw = json.load(open(os.path.join(D, "osm-pois.json")))
    g6 = json.load(open(os.path.join(D, "osm-g6.json")))

    # G-6 from OSM: stitch the relation's ways into lines.
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in g6 if e["type"] == "node"}
    ways = {e["id"]: e for e in g6 if e["type"] == "way"}
    rel = next(e for e in g6 if e["type"] == "relation")
    lines = [[nodes[n] for n in ways[m["ref"]]["nodes"]] for m in rel["members"] if m["type"] == "way" and m["ref"] in ways]
    g6_lines = stitch(lines)
    # Start G-6 at the pass (Lipova Livada guidepost), so it reads pass -> Magaro like the park's route 5.
    pass_pt = (40.95378, 20.82872)
    g6_lines.sort(key=lambda l: min(hav(pass_pt, l[0]), hav(pass_pt, l[-1])))
    if hav(pass_pt, g6_lines[0][-1]) < hav(pass_pt, g6_lines[0][0]): g6_lines[0] = g6_lines[0][::-1]

    trails = []
    for t in park["tracks"]:
        code = t["code"]; kind = code.split("-")[0]
        if kind not in KINDS: continue  # ASVALT = asphalt roads
        if code == "G-6":
            segs, src = g6_lines, "osm"
        else:
            segs, src = [[tuple(p) for p in t["coords"]]], "park"
        trails.append(dict(code=code, kind=kind, n=int(code.split("-")[1]), segs=segs, src=src,
                           slug=code.lower()))
    trails.sort(key=lambda t: (ORDER.index(t["kind"]), t["n"]))

    pois = []
    for p in pois_raw:
        tg = p["tags"]
        cls = classify(tg)
        if not cls: continue
        nm = tg.get("name:en") or tg.get("int_name") or tg.get("name:latin") or ""
        mk = tg.get("name:mk") or tg.get("name", "")
        if not nm:
            nm = translit(tg.get("name", "")) if re.search("[а-яА-Яѓќљњџѕј]", tg.get("name", "")) else tg.get("name", "")
        if cls == "guidepost":
            nm = " ".join(x for x in (tg.get("ref"), tg.get("name")) if x) or "(no number)"
        pois.append(dict(lat=p["lat"], lon=p["lon"], cls=cls, name=nm.strip(), mk=mk if mk != nm else "",
                         ele=tg.get("ele"), note=tg.get("note", ""), ref=tg.get("ref", ""), osm=p["id"]))
    for x in json.load(open(os.path.join(D, "places-extra.json")))["places"]:
        if any(p["cls"] not in ("guidepost", "board") and hav((p["lat"], p["lon"]), (x["lat"], x["lon"])) < 150 for p in pois): continue
        pois.append(dict(lat=x["lat"], lon=x["lon"], cls="extra", name=x["name"], mk=x["mk"], ele=None, note="", ref="", osm=""))
    return park, en, trails, pois

def classify(t):
    if t.get("tourism") == "information":
        return {"guidepost": "guidepost", "board": "board", "map": "board"}.get(t.get("information"))
    if not t.get("name"): return None
    if t.get("place") in ("town", "village", "hamlet", "isolated_dwelling"): return "village"
    if t.get("place") == "locality": return "locality"
    n = t.get("natural")
    if n in ("peak", "saddle", "spring", "cave_entrance"): return n
    if t.get("mountain_pass") == "yes": return "saddle"
    if t.get("tourism") in ("alpine_hut", "wilderness_hut"): return "hut"
    if t.get("tourism") in ("viewpoint", "camp_site", "picnic_site"): return t["tourism"]
    if t.get("amenity") == "place_of_worship": return "church"
    if t.get("amenity") in ("drinking_water",): return "spring"
    if t.get("historic"): return "historic"
    return None

def stitch(lines):
    lines = [l[:] for l in lines if len(l) > 1]; out = []
    while lines:
        cur = lines.pop(0); joined = True
        while joined:
            joined = False
            for i, l in enumerate(lines):
                if l[0] == cur[-1]: cur += l[1:]
                elif l[-1] == cur[-1]: cur += l[::-1][1:]
                elif l[-1] == cur[0]: cur = l + cur[1:]
                elif l[0] == cur[0]: cur = l[::-1] + cur[1:]
                else: continue
                lines.pop(i); joined = True; break
        out.append(cur)
    return out

CLASS_WORD = {"village": "", "locality": "", "peak": "peak", "saddle": "pass", "spring": "spring", "cave_entrance": "cave",
              "hut": "", "viewpoint": "viewpoint", "camp_site": "campsite", "picnic_site": "picnic site", "church": "", "historic": ""}

def place_label(p):
    w = CLASS_WORD.get(p["cls"], "")
    nm = p["name"]
    if w and w.lower() not in nm.lower(): nm = f"{nm} {w}"
    nm = re.sub(r"\bSt\.\s*", "St ", nm); nm = re.sub(r"^Saint ", "St ", nm)
    return nm

def enrich(trails, pois, routes_en, park):
    named = [p for p in pois if p["cls"] not in ("guidepost", "board")]
    for t in trails:
        line = [p for s in t["segs"] for p in s]
        dense = [p for s in t["segs"] for p in densify(s)]
        t["line"], t["dense"] = line, dense
        t["length"] = sum(hav(s[i], s[i + 1]) for s in t["segs"] for i in range(len(s) - 1))
        eles = elev.elevations(dense)
        t["eles"] = eles
        # profile distances
        d = [0.0]
        for i in range(1, len(dense)): d.append(d[-1] + (hav(dense[i - 1], dense[i]) if dense[i - 1] != dense[i] else 0))
        t["dist"] = d
        t["up"] = t["down"] = 0
        for sg in t["segs"]:
            u, dn = climb(elev.elevations(densify(sg))); t["up"] += u; t["down"] += dn
        t["min"], t["max"] = min(eles), max(eles)
        t["start"], t["end"] = line[0], line[-1]
        t["loop"] = hav(line[0], line[-1]) < 200
        along = []
        for p in named:
            if p["cls"] in ("village", "locality"): continue
            dd = dist_to_line((p["lat"], p["lon"]), dense)
            if dd < 120: along.append((nearest_index(dense, p), p))
        along.sort(key=lambda x: x[0])
        seen = set(); t["along"] = []
        for _, p in along:
            if p["name"] in seen: continue
            seen.add(p["name"]); t["along"].append(p)
        t["guideposts"] = [p for p in pois if p["cls"] == "guidepost" and dist_to_line((p["lat"], p["lon"]), dense) < 60]
        t["boards"] = [p for p in pois if p["cls"] == "board" and dist_to_line((p["lat"], p["lon"]), dense) < 150]
        # bounding box
        la = [p[0] for p in line]; lo = [p[1] for p in line]
        t["bbox"] = (min(la), min(lo), max(la), max(lo))
    for t in trails:
        t["start_name"] = name_near(t["start"], named, t["eles"][0], trails, t)
        t["end_name"] = name_near(t["end"], named, t["eles"][-1], trails, t)
    notes = json.load(open(os.path.join(D, "trail-notes.json")))
    for t in trails:
        n = notes.get(t["code"], {})
        t["walked"] = n.get("walked", ""); t["loop_note"] = n.get("loop_note", "")
        if "start" in n: t["start_name"] = dict(label=n["start"], mk="", poi=None)
        if "end" in n: t["end_name"] = dict(label=n["end"], mk="", poi=None)
    # connections
    for t in trails:
        t["links"] = []
        for o in trails:
            if o is t: continue
            ends_t = [t["start"], t["end"]]; ends_o = [o["start"], o["end"]]
            if any(dist_to_line(e, o["dense"]) < 60 for e in ends_t) or any(dist_to_line(e, t["dense"]) < 60 for e in ends_o):
                t["links"].append(o)
    # routes
    routes = []
    for r in park["routes"]:
        rid = r["id"]; e = routes_en["routes"][rid]
        codes = r["tracks"] or (["H-13"] if rid == "10" else [])
        variants = []
        fix = routes_en.get("start_fix", {}).get(rid, {})
        for vi, v in enumerate(r["variants"]):
            if str(vi) in fix: v = dict(v, start=fix[str(vi)])
            variants.append(dict(
                frm=routes_en["places"].get(v["starting_point"], v["starting_point"]),
                to=routes_en["places"].get(v["final_point"], v["final_point"]),
                frm_alt=num(v["starting_point_altitude"]), to_alt=num(v["final_point_altitude"]),
                km=num(v["total_length"]) / 1000, time=hours(v["average_time_pass_tour"]),
                diff=routes_en["difficulty"].get(v["route_difficulty"], v["route_difficulty"]),
                start=v.get("start")))
        routes.append(dict(id=rid, slug=e["slug"], name=e["name"], name_mk=title_mk(r["name"]), text=e["text"],
                           text_mk=r["variants"][0]["trail_position"] if r["variants"] else "",
                           codes=codes, variants=variants))
    by_code = {t["code"]: t for t in trails}
    for t in trails: t["routes"] = []
    for r in routes:
        r["trails"] = [by_code[c] for c in r["codes"] if c in by_code]
        for t in r["trails"]: t["routes"].append(r)
    return routes

def title_mk(s):
    # The park writes route names in capitals. Sentence-case them for display, keeping place names capitalised.
    return " ".join(w if w in ("–", "-") else w[:1] + w[1:].lower() for w in s.split())

def num(s):
    return int("".join(c for c in s if c.isdigit()) or 0)

def hours(s):
    m = re.match(r"\s*(\d+)\s*часа?(?:\s*и\s*(\d+)\s*минути)?", s)
    if not m: return s
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return f"{h} h {mi} min" if mi else f"{h} h"

def nearest_index(line, p):
    return min(range(len(line)), key=lambda i: (line[i][0] - p["lat"]) ** 2 + (line[i][1] - p["lon"]) ** 2)

def name_near(pt, named, ele, trails, me):
    """Name a trail end: a named place close by, else the junction with another trail, else relative to the nearest village."""
    best = None
    for p in named:
        d = hav(pt, (p["lat"], p["lon"]))
        lim = {"village": 900, "locality": 500, "hut": 400, "extra": 400}.get(p["cls"], 300)
        if d < lim and (best is None or d < best[0]): best = (d, p)
    if best:
        p = best[1]; lab = place_label(p)
        if p["cls"] == "village" and best[0] > 250: lab = f"near {lab}"
        return dict(label=lab, mk=p["mk"], poi=p)
    joins = [o for o in trails if o is not me and o["kind"] != "MTB" and dist_to_line(pt, o["dense"]) < 60]
    joins = joins or [o for o in trails if o is not me and dist_to_line(pt, o["dense"]) < 60]
    if joins:
        o = sorted(joins, key=lambda o: (ORDER.index(o["kind"]), o["n"]))[0]
        return dict(label=f"the {o['code']} junction", mk="", poi=None)
    vs = sorted((hav(pt, (p["lat"], p["lon"])), p) for p in named if p["cls"] == "village")
    if vs and vs[0][0] < 4000:
        v = vs[0][1]; vele = elev.elevations([(v["lat"], v["lon"])])[0]
        rel = "above" if ele - vele > 80 else "below" if vele - ele > 80 else "near"
        return dict(label=f"{rel} {place_label(v)} ({fmt_int(ele)} m)", mk=v["mk"], poi=None)
    return dict(label=f"a point at {fmt_int(ele)} m", mk="", poi=None)

# ---------------------------------------------------------------- outputs: GPX / GeoJSON / KML

def gpx_track(t, ele=True):
    desc = trail_summary(t)
    x = [f'<trk><name>{xesc(t["code"])}: {xesc(t["start_name"]["label"])} to {xesc(t["end_name"]["label"])}</name>'
         f'<desc>{xesc(desc)}</desc><type>{t["kind"]}</type>'
         f'<extensions><gpxx:TrackExtension><gpxx:DisplayColor>{KINDS[t["kind"]]["gpx"]}</gpxx:DisplayColor></gpxx:TrackExtension>'
         f'<gpx_style:line><gpx_style:color>{KINDS[t["kind"]]["color"][1:]}</gpx_style:color><gpx_style:width>4</gpx_style:width></gpx_style:line></extensions>']
    for s in t["segs"]:
        pts = []
        for a, b in s:
            e = elev.cache.get(elev.key(a, b)) if ele else None
            pts.append(f'<trkpt lat="{a:.6f}" lon="{b:.6f}">' + (f"<ele>{e:.0f}</ele>" if e is not None else "") + "</trkpt>")
        x.append("<trkseg>" + "".join(pts) + "</trkseg>")
    x.append("</trk>")
    return "".join(x)

def gpx_doc(name, desc, wpts, tracks):
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="galicica.finereli.com" xmlns="http://www.topografix.com/GPX/1/1"'
         ' xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3"'
         ' xmlns:gpx_style="http://www.topografix.com/GPX/gpx_style/0/2">',
         f'<metadata><name>{xesc(name)}</name><desc>{xesc(desc)}</desc>'
         f'<link href="{BASE}/"><text>galicica.finereli.com</text></link>'
         f'<copyright author="NP Galičica (trail lines), OpenStreetMap contributors (places, G-6)"><license>{BASE}/about/#license</license></copyright></metadata>']
    for w in wpts:
        x.append(f'<wpt lat="{w["lat"]:.6f}" lon="{w["lon"]:.6f}"><name>{xesc(w["name"])}</name>'
                 + (f'<desc>{xesc(w["desc"])}</desc>' if w.get("desc") else "") + f'<sym>{w.get("sym", "Flag")}</sym></wpt>')
    x += tracks
    x.append("</gpx>")
    return "\n".join(x) + "\n"

def poi_wpt(p):
    if p["cls"] == "guidepost":
        return dict(lat=p["lat"], lon=p["lon"], name=p["name"], desc="Park guidepost. " + (f"Trails here: {p['note']}." if p["note"] else ""), sym="Flag")
    if p["cls"] == "board":
        return dict(lat=p["lat"], lon=p["lon"], name="Trail map board", desc="Park board with the map and table of trails.", sym="Information")
    return dict(lat=p["lat"], lon=p["lon"], name=place_label(p), desc=(p["mk"] + ". " if p["mk"] else "") + (f"{p['ele']} m" if p["ele"] else ""), sym="Summit" if p["cls"] == "peak" else "Flag")

def trail_summary(t):
    k = KINDS[t["kind"]]
    s = (f"{t['code']} is one of Galičica National Park's {k['what']}. "
         + ("It's a loop of " if t["loop"] else "It's ") + f"{fmt_km(t['length'])} km "
         + (f"from {t['start_name']['label']}" if t["loop"] else f"from {t['start_name']['label']} to {t['end_name']['label']}")
         + f", with about {fmt_int(t['up'])} m of climbing and {fmt_int(t['down'])} m of descent in the direction drawn, between {fmt_int(t['min'])} m and {fmt_int(t['max'])} m.")
    return s

def geojson_feature(t):
    return {"type": "Feature",
            "properties": {"code": t["code"], "kind": t["kind"], "name": f"{t['start_name']['label']} to {t['end_name']['label']}",
                           "length_km": round(t["length"] / 1000, 2), "ascent_m": round(t["up"]), "descent_m": round(t["down"]),
                           "min_ele_m": round(t["min"]), "max_ele_m": round(t["max"]), "color": KINDS[t["kind"]]["color"],
                           "url": f"{BASE}/trails/{t['slug']}/", "gpx": f"{BASE}/gpx/{t['slug']}.gpx",
                           "source": "OpenStreetMap relation 7330532" if t["src"] == "osm" else "NP Galičica trail map, 2020 archive"},
            "geometry": {"type": "MultiLineString", "coordinates": [[[round(b, 6), round(a, 6)] for a, b in s] for s in t["segs"]]}}

def kml_doc(trails):
    x = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
         '<name>Galičica National Park marked trails</name>']
    for k in ORDER:
        c = KINDS[k]["color"][1:]
        x.append(f'<Style id="{k}"><LineStyle><color>ff{c[4:6]}{c[2:4]}{c[0:2]}</color><width>4</width></LineStyle></Style>')
    for t in trails:
        x.append(f'<Placemark><name>{xesc(t["code"])}</name><description>{xesc(trail_summary(t))} {BASE}/trails/{t["slug"]}/</description>'
                 f'<styleUrl>#{t["kind"]}</styleUrl><MultiGeometry>')
        for s in t["segs"]:
            x.append("<LineString><coordinates>" + " ".join(f"{b:.6f},{a:.6f}" for a, b in s) + "</coordinates></LineString>")
        x.append("</MultiGeometry></Placemark>")
    x.append("</Document></kml>")
    return "\n".join(x) + "\n"

# ---------------------------------------------------------------- HTML

def plate(code, big=False, link=True):
    k = code.split("-")[0]
    cls = f"plate plate-{k.lower()}" + (" plate-big" if big else "")
    inner = f'<span class="{cls}">{esc(code)}</span>'
    return f'<a class="plate-link" href="/trails/{code.lower()}/">{inner}</a>' if link else inner

def profile_svg(t, w=720, h=170):
    d, e = t["dist"], t["eles"]
    if len(d) < 2: return ""
    L = d[-1] or 1
    lo = math.floor((min(e) - 20) / 100) * 100; hi = math.ceil((max(e) + 20) / 100) * 100
    if hi - lo < 200: hi = lo + 200
    pl, pr, pt, pb = 46, 10, 10, 26
    X = lambda v: pl + (w - pl - pr) * v / L
    Y = lambda v: pt + (h - pt - pb) * (1 - (v - lo) / (hi - lo))
    pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(d, e))
    area = f"{X(0):.1f},{Y(lo):.1f} {pts} {X(L):.1f},{Y(lo):.1f}"
    step = 100 if hi - lo <= 600 else 200 if hi - lo <= 1200 else 500
    grid = "".join(f'<line x1="{pl}" x2="{w - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="g"/><text x="{pl - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:,}</text>'
                   for v in range(lo, hi + 1, step))
    kstep = 0.5 if L <= 3000 else 1 if L <= 8000 else 2 if L <= 16000 else 5
    xt = "".join(f'<text x="{X(k * 1000):.1f}" y="{h - 8}" text-anchor="middle">{k:g} km</text>'
                 for k in [i * kstep for i in range(int(L / 1000 / kstep) + 1)])
    return (f'<svg class="profile" viewBox="0 0 {w} {h}" role="img" aria-label="Elevation profile of {esc(t["code"])}: '
            f'from {fmt_int(e[0])} m to {fmt_int(e[-1])} m, highest {fmt_int(max(e))} m">'
            f'{grid}<polygon points="{area}" class="a" style="fill:{KINDS[t["kind"]]["color"]}"/>'
            f'<polyline points="{pts}" class="l" style="stroke:{KINDS[t["kind"]]["color"]}"/>{xt}</svg>')

FONT_PRELOAD = ('<link rel="preload" href="/fonts/golos-text-400-latin.woff2" as="font" type="font/woff2" crossorigin>'
                '<link rel="preload" href="/fonts/fira-sans-condensed-600-latin.woff2" as="font" type="font/woff2" crossorigin>')

def page(path, title, desc, body, jsonld=None, map_data=None, canonical=None, og_image="/og.png"):
    url = BASE + (canonical or "/" + path.replace("index.html", ""))
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    md = (f'<script id="map-data" type="application/json">{json.dumps(map_data, separators=(",", ":"))}</script>'
          '<link rel="stylesheet" href="/vendor/leaflet.css"><script src="/vendor/leaflet.js" defer></script><script src="/map.js" defer></script>') if map_data else ""
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}{og_image}"><meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#134B63">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="text/plain" href="/llms.txt" title="Plain-text summary for AI assistants">
{FONT_PRELOAD}
<link rel="stylesheet" href="/style.css">
{ld}{md}
</head>
<body>
<header class="top"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span>Galičica trails</a>
<nav><a href="/#trails">Trails</a><a href="/#routes">Routes</a><a href="/#phone">On your phone</a><a href="/about/">About</a></nav></header>
{body}
<footer class="foot"><div class="wrap">
<p>Trail lines are from the Galičica National Park trail map (NP Galičica), as it stood in 2020. Places, guideposts and G-6 are from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors. Map tiles from <a href="https://opentopomap.org">OpenTopoMap</a>. Elevations from SRTM. Trails change; check conditions locally and carry a map.</p>
<p><a href="/about/">About and licensing</a> · <a href="{REPO}">Source and data on GitHub</a> · <a href="{REPO}/issues">Report a problem with a trail</a> · <a href="/llms.txt">llms.txt</a></p>
</div></footer>
</body>
</html>
"""
    write(path, doc)

def trail_row(t):
    k = KINDS[t["kind"]]
    return (f'<tr><td>{plate(t["code"])}</td>'
            f'<td><a href="/trails/{t["slug"]}/">{esc(t["start_name"]["label"])}{" loop" if t["loop"] else " to " + esc(t["end_name"]["label"])}</a></td>'
            f'<td class="n">{fmt_km(t["length"])}<span class="u"> km</span></td>'
            f'<td class="n">{fmt_int(t["up"])}<span class="u"> m</span></td>'
            f'<td class="n hide-s">{fmt_int(t["max"])}<span class="u"> m</span></td>'
            f'<td class="dl"><a href="/gpx/{t["slug"]}.gpx" download aria-label="GPX for {esc(t["code"])}">GPX</a></td></tr>')

def map_feature(t, role="main"):
    # Thin the line for the web map: keep every point closer than 15 m apart out.
    out = []
    for s in t["segs"]:
        th = [s[0]]
        for p in s[1:-1]:
            if hav(th[-1], p) > 15: th.append(p)
        th.append(s[-1]); out.append([[round(a, 5), round(b, 5)] for a, b in th])
    return dict(code=t["code"], kind=t["kind"], color=KINDS[t["kind"]]["color"], url=f"/trails/{t['slug']}/", role=role, segs=out,
                label=f"{t['start_name']['label']}{' loop' if t['loop'] else ' to ' + t['end_name']['label']}", km=fmt_km(t["length"]))

def build_index(trails, routes, pois):
    total = {k: sum(t["length"] for t in trails if t["kind"] == k) for k in ORDER}
    legend = "".join(
        f'<label class="lg"><input type="checkbox" checked data-kind="{k}"> {plate(k, link=False)}'
        f'<span>{esc(KINDS[k]["what"].capitalize())}. {sum(1 for t in trails if t["kind"] == k)} trails, {total[k] / 1000:.0f} km.</span></label>' for k in ORDER)
    sections = ""
    for k in ORDER:
        rows = "".join(trail_row(t) for t in trails if t["kind"] == k)
        sections += (f'<section class="kind" id="{k.lower()}"><h3>{plate(k, link=False)} {esc(KINDS[k]["name"])}</h3>'
                     f'<p class="kind-what">{esc(KINDS[k]["what"].capitalize())}.</p>'
                     f'<table class="trails"><thead><tr><th>Code</th><th>Where</th><th class="n">Length</th><th class="n">Climb</th><th class="n hide-s">Top</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>')
    rrows = ""
    for r in routes:
        v = r["variants"][0]
        diffs = sorted(set(x["diff"] for x in r["variants"]), key=["easy", "moderate", "hard", "very hard"].index)
        rrows += (f'<li class="route"><a href="/routes/{r["slug"]}/"><span class="rn">{esc(r["name"])}</span></a>'
                  f'<span class="rmeta">{v["km"]:.1f} km, {esc(" or ".join(sorted(set(x["time"] for x in r["variants"]))))}, {esc(" / ".join(diffs))}</span>'
                  f'<span class="rplates">{"".join(plate(c) for c in r["codes"])}</span></li>')
    body = f"""
<main>
<section class="hero">
  <div id="map" class="map map-hero" role="region" aria-label="Map of all marked trails in Galičica National Park"></div>
  <div class="hero-card">
    <h1>Every marked trail in Galičica National Park</h1>
    <p class="lede">This is the full map of the {len(trails)} numbered trails between Lake Ohrid and Lake Prespa. The park's trail map has been missing from its website since 2021, and the trails were impossible to find in digital form. This is that map, rebuilt from a copy the Internet Archive saved in 2020 and thoroughly checked against OpenStreetMap. GPX files for your map app are available for download below.</p>
    <div class="legend" aria-label="Trail types (tick to show on the map)">{legend}</div>
    <p class="cta"><a class="btn" href="/gpx/galicica-all-trails.gpx" download>Download all trails (GPX)</a> <a class="quiet" href="#phone">How to use it on your phone</a></p>
    <p class="note">On a phone, open the file in <a href="https://organicmaps.app/">Organic Maps</a>: it's free and open source, and you can use it offline, which matters because there's no signal on most of the mountain.</p>
  </div>
</section>

<div class="wrap">
<section class="intro">
  <p>Galičica (Галичица) is the limestone mountain between Ohrid and Prespa, a national park since 1958. The park marks its trails with codes you'll see painted on the signposts: <b>H</b> for the easier ones, <b>T</b> for the longer and steeper, <b>G</b> for the ridges above 1,600 m, and <b>MTB</b> for bike trails. The codes on this site are the ones on the signs.</p>
  <p class="mk" lang="mk">Сите обележани патеки на Националниот парк Галичица (H, T, G и MTB), со карта, висински профил и GPX за секоја патека. Податоците се од картата на патеки на Паркот од 2020 година.</p>
</section>

<section id="trails" class="block">
  <h2>The trails</h2>
  <p class="note">Length and climb are measured on the line as the park drew it, from one end to the other. Climb is from SRTM elevation data, so treat it as a good estimate rather than gospel. Tap a trail for its map, profile, guideposts and connections.</p>
  {sections}
</section>

<section id="routes" class="block">
  <h2>The park's suggested routes</h2>
  <p class="note">The park strings trails together into ten day routes, with its own length, walking time and difficulty for each direction. Descriptions are translated from the park's Macedonian text.</p>
  <ul class="routes">{rrows}</ul>
</section>

<section id="phone" class="block">
  <h2>On your phone</h2>
  <p class="note">We recommend <a href="https://organicmaps.app/">Organic Maps</a>. It's free and open source, has no ads or tracking, and needs no signal once you've downloaded the map. Its map is OpenStreetMap, which has most of the paths on Galičica already. With the park's trail lines on top, you can tell which path is which.</p>
  <ol class="steps">
    <li>Install Organic Maps from the <a href="https://apps.apple.com/app/organic-maps/id1567437057">App Store</a> or <a href="https://play.google.com/store/apps/details?id=app.organicmaps">Google Play</a> (or <a href="https://f-droid.org/packages/app.organicmaps/">F-Droid</a>).</li>
    <li>While you're on wifi, open the app, find North Macedonia and download its map. Albania too if you'll walk near the border on the high ridge.</li>
    <li>On this site, tap a trail's <b>GPX</b> button, or download all trails at once. Open the file with Organic Maps: on iPhone, from the Files app or the share sheet; on Android, tap the downloaded file or share it to Organic Maps. You'll find the trail under Bookmarks and Tracks, with its guideposts as places.</li>
    <li>On the mountain, you'll see where you are on the trail with no signal at all. Tap the track for its length and elevation.</li>
  </ol>
  <p class="note">If you already use AlpineQuest, OsmAnd, Gaia GPS, Locus or a Garmin, you can open the same files there.</p>
</section>

<section id="downloads" class="block">
  <h2>Downloads</h2>
  <ul class="downloads">
    <li><a href="/gpx/galicica-all-trails.gpx" download>galicica-all-trails.gpx</a>: every trail as its own track, colored by type, with elevations, plus the park guideposts, map boards and route trailheads as waypoints. You can open it in Organic Maps, AlpineQuest, OsmAnd, Gaia GPS, Locus or on a Garmin.</li>
    <li><a href="/data/galicica-trails.geojson" download>galicica-trails.geojson</a>: the same trails with their stats as properties, for QGIS, uMap or your own map.</li>
    <li><a href="/data/galicica-trails.kml" download>galicica-trails.kml</a>: for Google Earth and Google My Maps.</li>
    <li>One GPX per trail and per route, linked from each trail's page and from the table above.</li>
  </ul>
  <p class="note">Free to use. Please credit NP Galičica for the trail lines and OpenStreetMap contributors for the places. See <a href="/about/#license">licensing</a>.</p>
</section>
</div>
</main>"""
    feats = [map_feature(t) for t in trails]
    starts = [dict(lat=v["start"][0], lon=v["start"][1], name=f"Start of route: {r['name']}", url=f"/routes/{r['slug']}/")
              for r in routes for v in r["variants"] if v.get("start")]
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "Galičica trails", "url": BASE + "/",
           "description": "Every marked hiking trail in Galičica National Park, North Macedonia, with maps and GPX files.", "inLanguage": "en"},
          {"@context": "https://schema.org", "@type": "Dataset",
           "name": "Galičica National Park marked trails (H, T, G, MTB)",
           "description": f"Geometry and statistics for all {len(trails)} numbered trails in Galičica National Park, North Macedonia, between Lake Ohrid and Lake Prespa, plus the park's 10 suggested routes. Recovered from the park's own web map (archived October 2020) and cross-checked with OpenStreetMap.",
           "url": BASE + "/", "keywords": ["Galičica", "Galicica", "Галичица", "national park", "hiking", "trails", "GPX", "Ohrid", "Prespa", "North Macedonia"],
           "license": BASE + "/about/#license", "isAccessibleForFree": True, "creator": {"@type": "Person", "name": "Eli Finer"},
           "isBasedOn": "https://web.archive.org/web/20201022172016/http://galicica.org.mk/wp-json/wp/v2/tracks",
           "spatialCoverage": {"@type": "Place", "name": "Galičica National Park, North Macedonia", "geo": {"@type": "GeoShape", "box": "40.90 20.74 41.14 20.99"}},
           "distribution": [{"@type": "DataDownload", "encodingFormat": "application/gpx+xml", "contentUrl": BASE + "/gpx/galicica-all-trails.gpx"},
                            {"@type": "DataDownload", "encodingFormat": "application/geo+json", "contentUrl": BASE + "/data/galicica-trails.geojson"},
                            {"@type": "DataDownload", "encodingFormat": "application/vnd.google-earth.kml+xml", "contentUrl": BASE + "/data/galicica-trails.kml"}],
           "dateModified": TODAY}]
    page("index.html", "Galičica National Park trails: all marked hiking trails with maps and GPX",
         f"All {len(trails)} marked trails in Galičica National Park (Галичица), North Macedonia, between Lake Ohrid and Lake Prespa: H, T, G and MTB codes from the park signposts, with maps, elevation profiles and free GPX downloads.",
         body, jsonld=ld, map_data=dict(mode="all", trails=feats, points=starts))

def build_trail(t, trails, pois):
    k = KINDS[t["kind"]]
    title = f"{t['code']}: {t['start_name']['label']}{' loop' if t['loop'] else ' to ' + t['end_name']['label']}"
    mk_bits = [x for x in (t["start_name"]["mk"], t["end_name"]["mk"]) if x]
    facts = (f'<dl class="facts"><div><dt>Length</dt><dd>{fmt_km(t["length"])} km</dd></div>'
             f'<div><dt>Climb</dt><dd>{fmt_int(t["up"])} m up, {fmt_int(t["down"])} m down</dd></div>'
             f'<div><dt>Elevation</dt><dd>{fmt_int(t["min"])} to {fmt_int(t["max"])} m</dd></div>'
             f'<div><dt>Type</dt><dd>{esc(k["what"].capitalize())}</dd></div></dl>')
    along = ""
    if t["along"] or t["guideposts"] or t["boards"]:
        items = "".join(f'<li>{esc(place_label(p))}{" (" + esc(p["mk"]) + ")" if p["mk"] else ""}{", " + esc(p["ele"]) + " m" if p["ele"] else ""}</li>' for p in t["along"])
        items += "".join(f'<li>Guidepost {esc(p["name"])}{": signed for " + esc(p["note"].replace(";", ",")) if p["note"] else ""}</li>' for p in t["guideposts"])
        items += "".join('<li>Park map board with the full trail table</li>' for p in t["boards"])
        along = f'<h2>On or near the trail</h2><ul class="along">{items}</ul>'
    links = ""
    if t["links"]:
        links = ("<h2>Connecting trails</h2><ul class=\"links\">" + "".join(
            f'<li>{plate(o["code"])} <a href="/trails/{o["slug"]}/">{esc(o["start_name"]["label"])}{" loop" if o["loop"] else " to " + esc(o["end_name"]["label"])}</a>, {fmt_km(o["length"])} km</li>'
            for o in t["links"]) + "</ul>")
    rts = ""
    if t["routes"]:
        rts = ("<h2>Part of the park's suggested routes</h2><ul class=\"links\">" + "".join(
            f'<li><a href="/routes/{r["slug"]}/">{esc(r["name"])}</a>, {r["variants"][0]["km"]:.1f} km</li>' for r in t["routes"]) + "</ul>")
    src = ("The line is from OpenStreetMap (relation 7330532). On the park's own map the climb from the pass is a straight 1.4 km line, so we used the mapped path instead."
           if t["src"] == "osm" else
           "The line is from the park's own trail map as archived in October 2020. It was drawn by hand on a map, not recorded on the ground, so expect it to be off by 20 to 50 m in places.")
    nav_prev = trails[trails.index(t) - 1] if trails.index(t) > 0 else None
    nav_next = trails[trails.index(t) + 1] if trails.index(t) + 1 < len(trails) else None
    body = f"""
<main class="wrap trail">
<p class="crumbs"><a href="/">All trails</a> / <a href="/#{t['kind'].lower()}">{esc(k['name'])}</a></p>
<h1>{plate(t['code'], big=True, link=False)} <span>{esc(t['start_name']['label'])}{' loop' if t['loop'] else ' to ' + esc(t['end_name']['label'])}</span></h1>
<p class="lede">{esc(trail_summary(t))}{' In Macedonian: ' + esc(', '.join(mk_bits)) + '.' if mk_bits else ''}</p>
{facts}
<p class="cta"><a class="btn" href="/gpx/{t['slug']}.gpx" download>Download GPX for {esc(t['code'])}</a> <a class="quiet" href="/gpx/galicica-all-trails.gpx" download>or all trails in one file</a></p>
<p class="note">On a phone, open it in <a href="https://organicmaps.app/">Organic Maps</a> (free, open source, offline). <a href="/#phone">How</a>.</p>
<div id="map" class="map map-trail" role="region" aria-label="Map of {esc(t['code'])}"></div>
<h2>Elevation</h2>
{profile_svg(t)}
<p class="note">From {esc(t['start_name']['label'])} ({fmt_int(t['eles'][0])} m) to {esc(t['end_name']['label'])} ({fmt_int(t['eles'][-1])} m). You can walk it either way; the climb figures swap.</p>
{rts}{links}{along}
{('<h2>What we found on the ground</h2><p>' + esc(t['walked']) + '</p>') if t['walked'] else ''}
<h2>About this line</h2>
<p>{esc(t['loop_note']) + ' ' if t['loop_note'] else ''}{src} Most of the park's trails are marked on the ground with paint blazes and numbered guideposts, but markings fade and paths get overgrown. Carry an offline map and turn back if you lose the path.</p>
<nav class="prevnext">{f'<a href="/trails/{nav_prev["slug"]}/">{plate(nav_prev["code"], link=False)} previous</a>' if nav_prev else '<span></span>'}{f'<a href="/trails/{nav_next["slug"]}/">next {plate(nav_next["code"], link=False)}</a>' if nav_next else ''}</nav>
</main>"""
    feats = [map_feature(t)] + [map_feature(o, "link") for o in t["links"]]
    pts = [dict(lat=p["lat"], lon=p["lon"], name=f"Guidepost {p['name']}" + (f": {p['note']}" if p["note"] else "")) for p in t["guideposts"]]
    pts += [dict(lat=t["start"][0], lon=t["start"][1], name=f"{t['code']} start: {t['start_name']['label']}", kind="end")]
    if not t["loop"]: pts.append(dict(lat=t["end"][0], lon=t["end"][1], name=f"{t['code']} end: {t['end_name']['label']}", kind="end"))
    mid = t["dense"][len(t["dense"]) // 2]
    ld = {"@context": "https://schema.org", "@type": ["TouristAttraction", "Place"], "name": f"{t['code']} trail, Galičica National Park",
          "alternateName": title, "description": trail_summary(t), "url": f"{BASE}/trails/{t['slug']}/",
          "geo": {"@type": "GeoCoordinates", "latitude": round(mid[0], 5), "longitude": round(mid[1], 5)},
          "containedInPlace": {"@type": "Park", "name": "Galičica National Park", "alternateName": ["Galicica", "Галичица"]},
          "isAccessibleForFree": False, "touristType": "Hikers" if t["kind"] != "MTB" else "Mountain bikers",
          "additionalProperty": [{"@type": "PropertyValue", "name": "length", "value": round(t["length"] / 1000, 1), "unitText": "km"},
                                 {"@type": "PropertyValue", "name": "ascent", "value": round(t["up"]), "unitText": "m"},
                                 {"@type": "PropertyValue", "name": "highest point", "value": round(t["max"]), "unitText": "m"}]}
    page(f"trails/{t['slug']}/index.html", f"{title} | Galičica National Park trail {t['code']}",
         f"{trail_summary(t)} Map, elevation profile and free GPX.", body, jsonld=ld,
         map_data=dict(mode="trail", trails=feats, points=pts))
    # GPX for this trail: the track plus waypoints on it
    w = [dict(lat=t["start"][0], lon=t["start"][1], name=f"{t['code']} start", desc=t["start_name"]["label"], sym="Trail Head")]
    if not t["loop"]: w.append(dict(lat=t["end"][0], lon=t["end"][1], name=f"{t['code']} end", desc=t["end_name"]["label"], sym="Trail Head"))
    w += [poi_wpt(p) for p in t["guideposts"] + t["boards"] + t["along"]]
    write(f"gpx/{t['slug']}.gpx", gpx_doc(f"Galičica trail {t['code']}", trail_summary(t) + f" {BASE}/trails/{t['slug']}/", w, [gpx_track(t)]))

def build_route(r, routes):
    dirs = "".join(
        f'<tr><td>{esc(v["frm"])} to {esc(v["to"])}</td><td class="n">{v["km"]:.1f} km</td><td class="n">{esc(v["time"])}</td><td>{esc(v["diff"])}</td></tr>'
        for v in r["variants"])
    alts = r["variants"][0]
    body = f"""
<main class="wrap trail">
<p class="crumbs"><a href="/">All trails</a> / <a href="/#routes">Suggested routes</a></p>
<h1><span>{esc(r['name'])}</span></h1>
<p class="lede">One of the ten day routes suggested by Galičica National Park, made up of {', '.join(plate(c) for c in r['codes'])}. Start at {fmt_int(alts['frm_alt'])} m, finish at {fmt_int(alts['to_alt'])} m.</p>
<table class="dirs"><thead><tr><th>Direction</th><th class="n">Length</th><th class="n">Time</th><th>Park rating</th></tr></thead><tbody>{dirs}</tbody></table>
<p class="cta"><a class="btn" href="/gpx/route-{r['slug']}.gpx" download>Download GPX for this route</a></p>
<p class="note">On a phone, open it in <a href="https://organicmaps.app/">Organic Maps</a> (free, open source, offline). <a href="/#phone">How</a>.</p>
<div id="map" class="map map-trail" role="region" aria-label="Map of the route"></div>
<h2>What the park says</h2>
<p>{esc(r['text'])}</p>
<details><summary>Original text in Macedonian</summary><p lang="mk">{esc(r['text_mk'])}</p><p class="note" lang="mk">{esc(r['name_mk'])}</p></details>
<h2>Trails on this route</h2>
<ul class="links">{''.join(f'<li>{plate(t["code"])} <a href="/trails/{t["slug"]}/">{esc(t["start_name"]["label"])}{" loop" if t["loop"] else " to " + esc(t["end_name"]["label"])}</a>, {fmt_km(t["length"])} km</li>' for t in r['trails'])}</ul>
<p class="note">In the GPX each trail is a separate track, drawn in full. Some trails go on past the point where you leave them for the next one, so the tracks add up to more than the park's route length. Go by the trailheads and the park's distance.</p>
</main>"""
    feats = [map_feature(t) for t in r["trails"]]
    pts = [dict(lat=v["start"][0], lon=v["start"][1], name=f"Start, going {v['frm']} to {v['to']}", kind="end") for v in r["variants"] if v.get("start")]
    ld = {"@context": "https://schema.org", "@type": "TouristTrip", "name": r["name"], "description": r["text"], "url": f"{BASE}/routes/{r['slug']}/",
          "touristType": "Hikers", "provider": {"@type": "Park", "name": "Galičica National Park"},
          "itinerary": {"@type": "ItemList", "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{BASE}/trails/{t['slug']}/", "name": t["code"]} for i, t in enumerate(r["trails"])]}}
    page(f"routes/{r['slug']}/index.html", f"{r['name']}: Galičica National Park suggested route",
         f"{r['name']}. {alts['km']:.1f} km, {alts['time']}, rated {alts['diff']} by the park. {r['text'][:180]}", body, jsonld=ld,
         map_data=dict(mode="route", trails=feats, points=pts))
    w = [dict(lat=v["start"][0], lon=v["start"][1], name=f"Start: {v['frm']}", desc=f"{v['frm']} to {v['to']}: {v['km']:.1f} km, {v['time']}, {v['diff']}", sym="Trail Head") for v in r["variants"] if v.get("start")]
    write(f"gpx/route-{r['slug']}.gpx", gpx_doc(r["name"], r["text"] + f" {BASE}/routes/{r['slug']}/", w, [gpx_track(t) for t in r["trails"]]))

def build_about(trails):
    body = f"""
<main class="wrap prose">
<h1>About this site</h1>
<p>Galičica National Park has one of the best-marked trail networks in North Macedonia: {len(trails)} numbered trails with painted blazes and guideposts. Until about 2021 the park had every one of them on an interactive map on its website. Then the park redesigned the site, the map's data was left behind, and the trail pages have had an empty box where the map used to be ever since. As far as we could find, nobody else had published the full set of lines. Mappers had added 7 of the trails to OpenStreetMap.</p>
<p>The Internet Archive's Wayback Machine had saved a copy of the map's data feed in October 2020, and we built this site from it. The copy has the line of every H, T, G and MTB trail, and the park's ten suggested routes with their official length, time and difficulty.</p>
<h2>How we checked it</h2>
<ul>
<li>The trail totals are the same as in the park's 2021 to 2030 management plan: about 52 km of H, 57 km of T and 30 km of G trails.</li>
<li>Where OpenStreetMap also has a trail (H-6, H-7, T-3, T-7, G-2, G-5 and G-6), the park's line and the OSM line are within 50 m of each other for 95 to 100% of their length.</li>
<li>G-6 to Magaro was the exception. The park drew the climb from the pass as a straight line, so for G-6 we used the OSM route instead.</li>
<li>We walked T-3 above Velestovo with GPS on in October 2026. Our track is a median 2 m from the park's line, and 90% of it is within 30 m. That's better than we expected from a line drawn on a map.</li>
</ul>
<h2>What to keep in mind</h2>
<ul>
<li>The park's lines were drawn on a map, not recorded with GPS. Expect them to be 20 to 50 m off in places, especially in forest.</li>
<li>They're the network as it was in 2020. Paths get overgrown and markings fade. A few trails, like the shore path toward St Zaum, are much harder to follow on the ground than on the map.</li>
<li>Length and climb are measured on the lines with SRTM elevation data. Climb on steep slopes can be overstated.</li>
<li>The park charges an entry fee per car on the Galičica pass road, and parts of the high ridge are a strict protection zone where you must stay on the trail.</li>
</ul>
<h2 id="license">Licensing and credit</h2>
<p>The trail lines and route descriptions are the work of the public institution NP Galičica. We republish them, with credit, because the park made them for the public and nobody else had published them. If you represent the park and would like them presented differently, or want to host them again yourselves, please <a href="{REPO}/issues">open an issue</a> and we'll do whatever helps.</p>
<p>Place names, guideposts and the G-6 line are from OpenStreetMap, © OpenStreetMap contributors, available under the <a href="https://opendatacommons.org/licenses/odbl/">Open Database License</a>. Map tiles are from <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA). The site's code is MIT licensed. Our own additions (translations, stats, write-ups) are CC-BY 4.0.</p>
<p>Because the trail lines come from the park rather than from a survey, they can't be copied into OpenStreetMap without the park's permission. If you walk a trail with GPS on, though, your own track can be added to OSM, and that's the best way to make these trails permanent.</p>
<h2>Help keep it right</h2>
<p>If you walk one of these trails and find the line wrong, a sign different, or the path gone, please <a href="{REPO}/issues">open an issue on GitHub</a> with what you found, and a GPX if you recorded one. All the data and the code for this site are in <a href="{REPO}">the repository</a>.</p>
<p>Made by Eli Finer, who spent autumn 2026 hiking around Ohrid with his family. Our family-sized hikes are at <a href="https://ohridhikes.finereli.com">ohridhikes.finereli.com</a>.</p>
</main>"""
    page("about/index.html", "About the Galičica trails site: where the data comes from",
         "Where this map of Galičica National Park's marked trails comes from, how it was checked, and how it's licensed.", body)

def build_llms(trails, routes):
    lines = [f"# Galičica trails ({BASE})", "",
             f"> Every marked trail in Galičica National Park (Галичица, also spelled Galicica or Galichica), North Macedonia, between Lake Ohrid and Lake Prespa. All {len(trails)} numbered trails (H easier, T harder, G ridges above 1,600 m, MTB bike) with maps, elevation profiles and free GPX, GeoJSON and KML downloads, plus the park's 10 suggested day routes.",
             "", "Key facts:",
             "- Free, no account, no ads. Open data and open source: " + REPO,
             "- Source: the park's own web trail map (NP Galičica), archived by the Wayback Machine in October 2020, before the park took the map down in a site redesign. Cross-checked against OpenStreetMap (within 50 m where both exist). The G-6 line is from OSM.",
             "- Trail codes are the ones on the park's signposts and guideposts.",
             "- Lines were drawn by hand by the park, not GPS-recorded; expect 20 to 50 m error. Conditions are as of 2020.",
             f"- All trails in one GPX: {BASE}/gpx/galicica-all-trails.gpx (for AlpineQuest, OsmAnd, Gaia GPS, Locus, Organic Maps, Garmin)",
             "- Recommended phone app: Organic Maps (https://organicmaps.app), free and open source, usable offline (no signal on most of the mountain). Download the North Macedonia map on wifi, then open a trail's GPX with Organic Maps.",
             f"- GeoJSON: {BASE}/data/galicica-trails.geojson   KML: {BASE}/data/galicica-trails.kml",
             "", "## Trails (code: from - to, length, ascent in the drawn direction, highest point)"]
    for t in trails:
        lines.append(f"- {t['code']}: {t['start_name']['label']}{' (loop)' if t['loop'] else ' - ' + t['end_name']['label']}, {fmt_km(t['length'])} km, +{fmt_int(t['up'])} m, top {fmt_int(t['max'])} m. {BASE}/trails/{t['slug']}/ GPX: {BASE}/gpx/{t['slug']}.gpx")
    lines += ["", "## Park suggested routes (official length, time, difficulty per direction)"]
    for r in routes:
        vs = "; ".join(f"{v['frm']} to {v['to']}: {v['km']:.1f} km, {v['time']}, {v['diff']}" for v in r["variants"])
        lines.append(f"- {r['name']} (trails {', '.join(r['codes'])}). {vs}. {BASE}/routes/{r['slug']}/")
    lines += ["", "## Related", "- Family-sized hikes around Ohrid: https://ohridhikes.finereli.com", f"- Report problems: {REPO}/issues", ""]
    write("llms.txt", "\n".join(lines))

def build_misc(trails, routes):
    urls = ["/", "/about/"] + [f"/trails/{t['slug']}/" for t in trails] + [f"/routes/{r['slug']}/" for r in routes]
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"<url><loc>{BASE}{u}</loc><lastmod>{TODAY}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    bots = ["OAI-SearchBot", "GPTBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended"]
    write("robots.txt", "User-agent: *\nAllow: /\n\n" + "".join(f"User-agent: {b}\nAllow: /\n\n" for b in bots) + f"Sitemap: {BASE}/sitemap.xml\n")
    write("404.html", '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Not found | Galičica trails</title><link rel="stylesheet" href="/style.css"></head><body><main class="wrap prose"><h1>No such page</h1><p>There\'s no trail or route at that address. <a href="/">See all Galičica trails</a>.</p></main></body></html>')

def main():
    park, en, trails, pois = load()
    routes = enrich(trails, pois, en, park)
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "static"), SITE, ignore=shutil.ignore_patterns("main.css", "fonts.css"))
    write("style.css", open(os.path.join(ROOT, "static", "fonts.css")).read() + open(os.path.join(ROOT, "static", "main.css")).read())
    build_index(trails, routes, pois)
    for t in trails: build_trail(t, trails, pois)
    for r in routes: build_route(r, routes)
    build_about(trails)
    build_llms(trails, routes)
    build_misc(trails, routes)
    # everything files
    wp = [poi_wpt(p) for p in pois if p["cls"] in ("guidepost", "board")]
    wp += [dict(lat=v["start"][0], lon=v["start"][1], name=f"Route start: {v['frm']}", desc=f"{r['name']}. {v['frm']} to {v['to']}: {v['km']:.1f} km, {v['time']}, {v['diff']}. {BASE}/routes/{r['slug']}/", sym="Trail Head")
           for r in routes for v in r["variants"] if v.get("start")]
    write("gpx/galicica-all-trails.gpx", gpx_doc("Galičica National Park: all marked trails",
          f"All {len(trails)} marked trails in Galičica National Park: H (red, easier), T (green, harder), G (gold, ridges above 1600 m), MTB (navy, bike). From the park's trail map (2020 archive); G-6 from OpenStreetMap. {BASE}/",
          wp, [gpx_track(t) for t in trails]))
    write("data/galicica-trails.geojson", json.dumps({"type": "FeatureCollection", "features": [geojson_feature(t) for t in trails]}, ensure_ascii=False))
    write("data/galicica-trails.kml", kml_doc(trails))
    for t in trails:
        print(f"{t['code']:6} {fmt_km(t['length']):>5} km +{fmt_int(t['up']):>5} {t['start_name']['label']} -> {t['end_name']['label']}  links {[o['code'] for o in t['links']]}")
    print(f"built {len(trails)} trails, {len(routes)} routes")

if __name__ == "__main__":
    main()
