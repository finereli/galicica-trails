// Draws the trails on the page's map. The page puts its data in <script id="map-data">.
(function () {
  var el = document.getElementById("map"), src = document.getElementById("map-data");
  if (!el || !src || !window.L) return;
  var data = JSON.parse(src.textContent);
  var map = L.map(el, { scrollWheelZoom: false, zoomSnap: 0.25 });
  map.setView([41.02, 20.84], 11); // setView before layers, or polylines throw on first render
  L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17, subdomains: "abc",
    attribution: 'Map © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA), data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  var byKind = {}, bounds = L.latLngBounds([]);
  data.trails.forEach(function (t) {
    var main = t.role === "main";
    var halo = L.polyline(t.segs, { color: "#fff", weight: main ? 8 : 6, opacity: main ? 0.9 : 0.6, interactive: false });
    var line = L.polyline(t.segs, { color: t.color, weight: main ? 4.5 : 3, opacity: main ? 1 : 0.6, dashArray: t.kind === "MTB" ? "8 6" : null });
    var g = L.layerGroup([halo, line]).addTo(map);
    line.bindTooltip(t.code, { sticky: true, className: "tlabel", direction: "top" });
    line.on("tooltipopen", function (e) { e.tooltip.getElement().style.background = t.color; if (t.kind === "G") e.tooltip.getElement().style.color = "#18221F"; });
    line.bindPopup('<b>' + t.code + '</b><br>' + t.label + ', ' + t.km + ' km<br><a href="' + t.url + '">Map, profile and GPX</a>');
    (byKind[t.kind] = byKind[t.kind] || []).push(g);
    if (main) t.segs.forEach(function (s) { bounds.extend(s); });
  });
  (data.points || []).forEach(function (p) {
    var m = L.circleMarker([p.lat, p.lon], { radius: p.kind === "end" ? 6 : 5, color: "#18221F", weight: 1.5, fillColor: p.kind === "end" ? "#fff" : "#E9ECE7", fillOpacity: 1 }).addTo(map);
    m.bindPopup(p.url ? '<a href="' + p.url + '">' + p.name + '</a>' : p.name);
  });
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 15 });

  // Legend checkboxes on the index toggle a trail type.
  document.querySelectorAll("input[data-kind]").forEach(function (cb) {
    cb.addEventListener("change", function () {
      (byKind[cb.dataset.kind] || []).forEach(function (g) { cb.checked ? g.addTo(map) : map.removeLayer(g); });
    });
  });
  // Scroll-zoom only after the map is clicked, so the page still scrolls past it.
  map.on("click", function () { map.scrollWheelZoom.enable(); });
  map.on("mouseout", function () { map.scrollWheelZoom.disable(); });
})();
