/* Hotel Chain Map — static frontend, no build step, no trackers.
 * Loads meta.json plus one slim GeoJSON file per spider, groups them into
 * chains, and renders one circle layer per chain on a MapLibre map. */
"use strict";

const MAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

/** chain name -> {color, features, coordinates, layerId, visible, spiders} */
const chains = new Map();
let map;

init().catch((error) => {
  console.error(error);
  document.getElementById("chain-list").innerHTML =
    "<li style='padding:12px'>Failed to load data. Please try again later.</li>";
});

async function init() {
  const meta = await fetchJson("data/meta.json");

  map = new maplibregl.Map({
    container: "map",
    style: MAP_STYLE,
    center: [10, 25],
    zoom: 1.5,
    attributionControl: {
      customAttribution:
        'Hotel data: <a href="https://www.alltheplaces.xyz/" target="_blank" rel="noopener">All the Places</a> (CC0)',
    },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  // Attach the load listener synchronously: waiting until after the data
  // fetches could miss a "load" event that has already fired.
  const styleReady = new Promise((resolve) => map.on("load", resolve));

  const chainNames = Object.keys(meta.chains).sort();
  const loaded = await Promise.all(
    chainNames.map(async (name) => {
      const spiders = meta.chains[name].spiders;
      const features = [];
      for (const spider of spiders) {
        const collection = await fetchJson(`data/${spider}.geojson`);
        features.push(...collection.features);
      }
      return { name, features, spiders };
    })
  );
  // Fill the Map after all fetches so the legend order is deterministic.
  for (const { name, features, spiders } of loaded) {
    chains.set(name, {
      color: meta.chains[name].color,
      features,
      coordinates: features.map((f) => f.geometry.coordinates),
      layerId: `chain-${name.toLowerCase().replace(/\W+/g, "-")}`,
      visible: true,
      spiders: spiders.map((spider) => ({ name: spider, ...meta.spiders[spider] })),
    });
  }

  buildLegend(meta);
  wirePanels();

  await styleReady;
  for (const [name, chain] of chains) addChainLayer(name, chain);
  map.on("moveend", updateCounts);
  updateCounts();
}

function fetchJson(url) {
  return fetch(url).then((response) => {
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
  });
}

/* --- Map layers ---------------------------------------------------------- */

function addChainLayer(name, chain) {
  map.addSource(chain.layerId, {
    type: "geojson",
    data: { type: "FeatureCollection", features: chain.features },
  });
  // Insert below the basemap's labels so place names stay readable.
  const firstSymbol = map.getStyle().layers.find((layer) => layer.type === "symbol");
  map.addLayer(
    {
      id: chain.layerId,
      type: "circle",
      source: chain.layerId,
      paint: {
        "circle-color": chain.color,
        "circle-opacity": 0.85,
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 1.7, 5, 3.2, 10, 6],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0, 6, 1],
      },
    },
    firstSymbol && firstSymbol.id
  );

  map.on("click", chain.layerId, (event) => {
    const feature = event.features[0];
    new maplibregl.Popup({ closeButton: true, maxWidth: "280px" })
      .setLngLat(feature.geometry.coordinates)
      .setHTML(popupHtml(feature.properties, name))
      .addTo(map);
  });
  map.on("mouseenter", chain.layerId, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", chain.layerId, () => (map.getCanvas().style.cursor = ""));
}

function popupHtml(properties, chainName) {
  const parts = [];
  parts.push(`<div class="popup-name">${escapeHtml(properties.name || "(unnamed hotel)")}</div>`);
  const brandLine = [properties.brand, chainName]
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index);
  parts.push(`<div class="popup-chain">${escapeHtml(brandLine.join(" · "))}</div>`);
  if (properties.address) {
    parts.push(`<div class="popup-line">${escapeHtml(properties.address)}</div>`);
  }
  if (properties.website && /^https?:\/\//.test(properties.website)) {
    const url = escapeHtml(properties.website);
    parts.push(`<div class="popup-line"><a href="${url}" target="_blank" rel="noopener">Website</a></div>`);
  }
  return parts.join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/* --- Legend --------------------------------------------------------------- */

function buildLegend(meta) {
  const list = document.getElementById("chain-list");
  for (const [name, chain] of chains) {
    const item = document.createElement("li");
    const row = document.createElement("button");
    row.type = "button";
    row.className = "chain-row";
    row.setAttribute("aria-pressed", "true");
    row.innerHTML =
      `<span class="swatch" style="background:${chain.color}"></span>` +
      `<span class="chain-main">` +
      `<span class="chain-name">${escapeHtml(name)}</span>` +
      `<span class="chain-date">${chainDateLine(chain)}</span>` +
      `</span>` +
      `<span class="chain-counts">…</span>`;
    row.addEventListener("click", () => toggleChain(name, row));
    item.appendChild(row);
    list.appendChild(item);
    chain.countsElement = row.querySelector(".chain-counts");
  }

  const spiderList = document.getElementById("about-spiders");
  for (const [name, chain] of chains) {
    for (const spider of chain.spiders) {
      const item = document.createElement("li");
      item.textContent = `${name}: spider "${spider.name}"`;
      spiderList.appendChild(item);
    }
  }
}

function chainDateLine(chain) {
  const dates = chain.spiders
    .filter((spider) => !spider.no_data && spider.run_start_time)
    .map((spider) => spider.run_start_time.slice(0, 10));
  if (dates.length === 0) return "No recent data";
  const stale = chain.spiders.some((spider) => spider.stale);
  const oldest = dates.sort()[0];
  return `Data: ${oldest}${stale ? ' <span class="stale">⚠ held from an earlier week</span>' : ""}`;
}

function toggleChain(name, row) {
  const chain = chains.get(name);
  chain.visible = !chain.visible;
  row.classList.toggle("off", !chain.visible);
  row.setAttribute("aria-pressed", String(chain.visible));
  if (map.getLayer(chain.layerId)) {
    map.setLayoutProperty(chain.layerId, "visibility", chain.visible ? "visible" : "none");
  }
  updateCounts();
}

function updateCounts() {
  if (!map) return;
  const bounds = map.getBounds();
  const south = bounds.getSouth();
  const north = bounds.getNorth();
  const west = bounds.getWest();
  const east = bounds.getEast();
  const width = east - west;
  for (const chain of chains.values()) {
    if (!chain.countsElement) continue;
    if (!chain.visible) {
      chain.countsElement.textContent = "hidden";
      continue;
    }
    let visible = 0;
    for (const [lon, lat] of chain.coordinates) {
      if (lat < south || lat > north) continue;
      // Longitude test that tolerates a wrapped (panned-around) map.
      if (width >= 360 || (((lon - west) % 360) + 360) % 360 <= width) visible += 1;
    }
    chain.countsElement.textContent =
      `${visible.toLocaleString("en")} / ${chain.features.length.toLocaleString("en")}`;
  }
}

/* --- Panels ---------------------------------------------------------------- */

function wirePanels() {
  const backdrop = document.getElementById("about-backdrop");
  document.getElementById("about-open").addEventListener("click", () => {
    backdrop.hidden = false;
  });
  document.getElementById("about-close").addEventListener("click", () => {
    backdrop.hidden = true;
  });
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) backdrop.hidden = true;
  });

  const toggle = document.getElementById("legend-toggle");
  // Start collapsed on small screens so the map is not covered.
  if (window.matchMedia("(max-width: 640px)").matches) {
    document.body.classList.add("legend-collapsed");
    toggle.setAttribute("aria-expanded", "false");
  }
  toggle.addEventListener("click", () => {
    const collapsed = document.body.classList.toggle("legend-collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
  });
}
