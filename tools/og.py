"""Render site/og.png (1200x630): the whole trail network over OpenTopoMap, for link previews. Tiles cache in tools/tiles/ (not committed)."""
import json, math, os, requests
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
CACHE = os.path.join(HERE, "tiles"); os.makedirs(CACHE, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "galicica-trails/1.0 (+https://galicica.finereli.com)"

def px(lat, lon, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n

def tile(z, x, y):
    p = f"{CACHE}/{z}_{x}_{y}.png"
    if not os.path.exists(p):
        r = S.get(f"https://a.tile.opentopomap.org/{z}/{x}/{y}.png", timeout=30); r.raise_for_status(); open(p, "wb").write(r.content)
    return Image.open(p).convert("RGB")

def main():
    gj = json.load(open(os.path.join(ROOT, "site", "data", "galicica-trails.geojson")))
    W, H, z = 1200, 630, 11
    # Centre on the network, leave the left 470 px for the title panel.
    cx, cy = px(41.02, 20.855, z)
    x0, y0 = cx - 470 - (W - 470) / 2, cy - H / 2
    img = Image.new("RGB", (W, H))
    for tx in range(int(x0 // 256), int((x0 + W) // 256) + 1):
        for ty in range(int(y0 // 256), int((y0 + H) // 256) + 1):
            img.paste(tile(z, tx, ty), (int(tx * 256 - x0), int(ty * 256 - y0)))
    d = ImageDraw.Draw(img)
    order = {"MTB": 0, "H": 1, "T": 2, "G": 3}
    for f in sorted(gj["features"], key=lambda f: order[f["properties"]["kind"]]):
        for seg in f["geometry"]["coordinates"]:
            xy = [(px(la, lo, z)[0] - x0, px(la, lo, z)[1] - y0) for lo, la in seg]
            d.line(xy, fill="white", width=5, joint="curve")
            d.line(xy, fill=f["properties"]["color"], width=3, joint="curve")
    d.rectangle((0, 0, 470, H), fill="#134B63")
    fdir = os.path.join(ROOT, "static", "fonts")
    big = ImageFont.truetype(os.path.join(HERE, "og-font.ttf"), 64) if os.path.exists(os.path.join(HERE, "og-font.ttf")) else ImageFont.load_default(64)
    small = ImageFont.truetype(os.path.join(HERE, "og-body.ttf"), 28)
    plate_f = ImageFont.truetype(os.path.join(HERE, "og-font.ttf"), 24)
    d.text((44, 70), "Galičica\ntrails", font=big, fill="white", spacing=6)
    d.text((44, 250), "Every marked trail in\nGaličica National Park,\nwith maps and free GPX.", font=small, fill="#DCEBF1", spacing=10)
    y = 420
    for k, c, ink in (("H", "#C8202F", "white"), ("T", "#1F7A3D", "white"), ("G", "#D4A20B", "#18221F"), ("MTB", "#24357F", "white")):
        w = 46 if k != "MTB" else 76
        d.rounded_rectangle((44 + (0 if k == "H" else {"T": 62, "G": 124, "MTB": 186}[k]), y, 44 + {"H": 0, "T": 62, "G": 124, "MTB": 186}[k] + w, y + 40), 4, fill=c, outline="white", width=2)
        d.text((44 + {"H": 0, "T": 62, "G": 124, "MTB": 186}[k] + w / 2, y + 20), k, font=plate_f, fill=ink, anchor="mm")
    d.text((44, 545), "galicica.finereli.com", font=small, fill="white")
    img.save(os.path.join(ROOT, "static", "og.png"), optimize=True)
    print("saved static/og.png")

if __name__ == "__main__":
    main()
