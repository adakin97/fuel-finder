# Petrol Price Tracker

A mobile-first interactive built from the government's [Fuel Finder](https://www.gov.uk/government/collections/fuel-finder) data. It shows how far unleaded (E10) prices have risen since February 2026, includes a postcode tool that finds the cheapest forecourts nearby, and compares prices by brand and region.

**Live page:** https://adakin97.github.io/fuel-finder/

`index.html` is the finished page. It is a single self-contained file: the data is inlined as JSON blocks and D3 comes from cdnjs with an integrity hash. It opens straight from disk or from GitHub Pages.

## Run it

```
pip install duckdb pandas numpy
python pipeline.py path/to/folder-with-e10.csv-and-stations.csv
```

This writes `data/*.json` and rebuilds `index.html` from `src/template.html`. On the full extract (347,612 price records, 8,148 stations) it takes about ten seconds once the postcode cache exists.

## What the pipeline does

1. **Prices.** Drops four pre-2026 dates and keeps one report where a forecourt has two at the same timestamp. Also drops prices outside 0.75x to 1.40x of that day's national median, which catches prices entered in pounds rather than pence, 999.9 placeholders and two prices of about 290p.
2. **Stations.** Normalises brand spelling and merges site-named variants ("SHELL ABRIDGE" counts as Shell). Checks every forecourt's coordinates against its own postcode via the postcodes.io bulk endpoint, cached in `data/postcode_cache.json`. 103 longitudes had lost their minus sign and 64 points were more than 5 km from their postcode; both are corrected. Costco sites are flagged as members only.
3. **Daily panel.** Each forecourt's last price of the day is carried forward until its next report, for at most 30 days. Averages are taken across forecourts per day, not across raw rows. A plain average of rows would over-weight the forecourts that change price most often.
4. **Snapshot.** Prices as at 1 October 2026 for the 7,774 forecourts that reported in the previous 30 days, with each price's age. A forecourt only reports when its price changes, and prices were rising, so an old price looks cheap. The tool's "cheapest near you" line therefore uses only prices from the last seven days, and older prices are marked.

## Checks

- The RAC published 132.83p for 1 March and 152.83p for 31 March. Our averages are 132.94p and 153.66p.
- Most forecourts joined in the last week of January. On the 4,688 forecourts with a price on both 1 February and 1 October, the rise is 43.0p; the headline uses 42p.
- The 1 October average is 174.23p with no carry-forward limit and 174.83p with a seven-day limit. The page uses the 30-day figure, 174.68p.
- Station prices on the page were spot-checked against the raw CSV.

## Mobile

- One column, 640px maximum, system fonts and no web-font download. Charts redraw to the container width, deferred with `requestAnimationFrame`.
- Every interaction works by tap: the crosshair on the line chart, the per-bar tooltips and nearest-dot lookup on the map (a d3 quadtree). On touch, a tooltip stays up until the next tap elsewhere.
- The map is drawn to a canvas, so 7,774 dots do not become 7,774 DOM nodes.
- The postcode tool and all three tables work without D3. Postcode lookups time out after five seconds. If postcodes.io is unreachable, outward codes fall back to district centres built from the geocoded stations.
- Light and dark themes follow the device setting.
- Page weight is about 230 KB gzipped plus D3 (90 KB gzipped). In production the station list would be lazy-loaded or served from an API refreshed daily.

## Data

Fuel Finder, Department for Energy Security and Net Zero, Open Government Licence v3.0. Postcode locations from postcodes.io (ONS data, Open Government Licence). The raw CSVs are not included in this repository.

## AI use

Built working with Claude Code (Anthropic, Claude Opus 5.5). I gave it the brief, with the mobile app as the main constraint. It profiled and cleaned the data, ran the analysis, proposed the angle and the postcode tool, and wrote the code. A separate set of AI reviewers then checked the work, and the problems they found, including a misleading news line and stale prices in the tool, were fixed. I reviewed the final page, figures and method.
