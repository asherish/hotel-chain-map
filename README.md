# Hotel Chain Map

An interactive world map of major hotel chains — IHG, Marriott, Hilton, Accor,
Best Western and Hyatt — rebuilt automatically every week from open data and
served as a static site on GitHub Pages:
**<https://asherish.github.io/hotel-chain-map/>**

## Data source and credits

All hotel locations come from **[All the Places](https://www.alltheplaces.xyz/)**
([GitHub](https://github.com/alltheplaces/alltheplaces)), a volunteer-run
open-data project that runs web spiders against brand websites and publishes
the results weekly under [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
This project would not exist without the contributors who write and maintain
those spiders — thank you.

Basemap tiles are served by [OpenFreeMap](https://openfreemap.org/) from
[OpenStreetMap](https://www.openstreetmap.org/copyright) data.

## Scope

This repository does exactly one thing: it selects a healthy weekly run per
spider from All the Places, trims each spider's output down to the fields the
map needs, and publishes the result as a static map.

It deliberately does **not**:

- scrape hotel or brand websites — neither the All the Places spiders nor any
  custom scraper runs here;
- fix, complete or geocode the source data — data errors should be reported
  to All the Places, not patched here;
- include booking, pricing, availability, reviews, loyalty-program
  information, or brand logos;
- guarantee accuracy or completeness of any chain's property list;
- cover chains beyond the configured list in `config.json` — adding one is an
  intentional, separate change.

## How weekly updates work

A GitHub Actions workflow runs once a week (and on demand). For each spider it:

1. reads the All the Places run history and per-run statistics;
2. accepts a run only if its feature count is at least **70%** of the median
   of the last 8 non-zero counts from *older* runs (so a degraded run cannot
   validate itself after an outage) — both numbers live in `config.json`;
3. uses the newest acceptable run among the last 8. If none qualifies, the
   previously published data is kept unchanged and marked as stale in
   `site/data/meta.json` — a degraded snapshot never overwrites good data.

The chosen GeoJSON is trimmed to `lon`, `lat`, `name`, `brand`, `address`,
`country` and `website`; features without a usable location are dropped and
non-point geometries are represented by their centroid. Because the
`marriott_hotels` spider also emits some Ritz-Carlton properties, features
from the `ritz_carlton` spider are dropped when a Ritz-branded
`marriott_hotels` feature lies within ~500 m. Output is deterministic
(fixed ordering and rounding), so an unchanged week produces no diff and no
commit. `site/data/meta.json` records, per spider, which run was used and why.

## Limitations and accuracy

Locations originate from each brand's own website, collected via All the
Places. They may be incomplete, imprecise or out of date — some spiders break
for weeks at a time (the map marks chains whose data is held from an earlier
week, or currently has no healthy data at all). Nothing here is verified.

This project is **not affiliated with, or endorsed by, any hotel company**.

## Reporting problems

- **Wrong or missing hotel data** → report upstream on the
  [All the Places issue tracker](https://github.com/alltheplaces/alltheplaces/issues).
  Mention the spider involved: the map's "About the data" panel and
  `site/data/meta.json` list the spider behind each chain, and the spider
  sources live under
  [`locations/spiders/`](https://github.com/alltheplaces/alltheplaces/tree/master/locations/spiders)
  in the All the Places repository.
- **Problems with this map or pipeline** → open an issue
  [here](https://github.com/asherish/hotel-chain-map/issues).

## Local development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync            # install dependencies
uv run pytest      # run the unit tests (no network access needed)

uv run python -m pipeline   # fetch data and rebuild site/data/ (network access)

# Serve the site locally, then open http://localhost:8765/
uv run python -m http.server 8765 -d site
```

The frontend is plain HTML/CSS/JS with no build step; MapLibre GL JS is
loaded from a CDN at a pinned version.

## License

- **Code** in this repository: [MIT](LICENSE).
- **Hotel data** (`site/data/`): from All the Places, dedicated to the public
  domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
  Attribution is not legally required by CC0, but this project credits
  All the Places prominently and asks that you do the same.
