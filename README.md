# Galičica trails

**Every marked trail in Galičica National Park (Галичица), North Macedonia, with maps, elevation profiles and free GPX files.** Live at **https://galicica.finereli.com**.

- All 38 numbered trails on the signposts: H (easier, 14 trails, 52 km), T (harder, 8 trails, 57 km), G (ridges above 1,600 m, 7 trails, 29 km) and MTB (bike, 9 trails, 56 km).
- The park's 10 suggested day routes, with its official length, walking time and difficulty in each direction, translated from Macedonian.
- Downloads: one GPX per trail, one per route, one with everything ([galicica-all-trails.gpx](https://galicica.finereli.com/gpx/galicica-all-trails.gpx)), plus [GeoJSON](https://galicica.finereli.com/data/galicica-trails.geojson) and [KML](https://galicica.finereli.com/data/galicica-trails.kml). On a phone we recommend [Organic Maps](https://organicmaps.app) (free, open source, offline); the files also work in AlpineQuest, OsmAnd, Gaia GPS, Locus, Google Earth and Garmin devices.
- Free, no account, no tracking, no ads.

## Why this exists

Until about 2021 the park's website (galicica.org.mk) drew every trail on an interactive map. After a redesign the map's data feed disappeared and the trail pages were left with an empty box. As far as we could find, the full set of trail lines wasn't published anywhere else, and OpenStreetMap had only 7 of them.

The Wayback Machine had kept a copy of the feed (`/wp-json/wp/v2/tracks` and `/wp-json/wp/v2/maps/`) from October 2020. This repo is built from that copy.

## How good is the data

- Totals match the park's 2021-2030 management plan (about 52 km H, 60 km T, 30 km G).
- Where OSM also maps a trail, the park line and the OSM line agree within 50 m for 95-100% of their length.
- Our own GPS track of T-3 above Velestovo (October 2026) sits a median 2 m from the park's line.
- G-6 (Magaro) uses the OSM route instead, because the park drew its approach as a straight line.
- The lines were drawn by hand by the park, not GPS-recorded: expect 20-50 m of error in places. They show the network as of 2020; paths overgrow and markings fade.
- Length and climb are computed on the lines with SRTM 30 m elevations.

## Repository layout

```
data/park-map-2020.json   the park's trail geometry and suggested routes (Wayback copy, Oct 2020)
data/routes-en.json       English names and translations of the route descriptions, and fixes for misplaced park markers
data/places-extra.json    named trail points OSM lacks (each with its source)
data/trail-notes.json     what we found walking a trail, and naming overrides
data/osm-pois.json        named places, guideposts and boards from OSM (tools/fetch_osm.py)
data/osm-g6.json          OSM relation 7330532, used for G-6
data/elev-cache.json      SRTM elevations (tools/prep_elev.py)
static/                   CSS, map script, fonts, Leaflet, icons
tools/build.py            builds site/ from data/, offline, no dependencies
site/                     the generated site (deployed to Cloudflare as static assets)
```

Build: `python3 tools/build.py`. Refresh OSM data: `python3 tools/fetch_osm.py`. Share image: `.venv/bin/python tools/og.py` (needs Pillow). Deploy: `npx wrangler deploy`.

## Help

Walked one of these trails and found something wrong, or a new sign? [Open an issue](https://github.com/finereli/galicica-trails/issues), ideally with your GPX. Notes from the ground go in `data/trail-notes.json`.

If you can, record your walks and add them to OpenStreetMap. The park's lines can't be copied into OSM without the park's permission, but your own GPS tracks can.

## Licensing

- Trail lines and route descriptions: NP Galičica (public institution), republished with credit because they were made for the public and had vanished. If you represent the park, please get in touch through an issue.
- Place names, guideposts and G-6: © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).
- Map tiles on the site: [OpenTopoMap](https://opentopomap.org) (CC-BY-SA).
- Our additions (translations, stats, notes): CC-BY 4.0. Code: MIT.

Made by Eli Finer while hiking around Ohrid in autumn 2026. Family-sized hikes: https://ohridhikes.finereli.com
