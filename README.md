# Petrol Price Tracker

A mobile-first interactive built from the government's [Fuel Finder](https://www.gov.uk/government/collections/fuel-finder) data: how far unleaded (E10) prices have risen since February 2026, a postcode tool that finds the cheapest forecourts near you, and a comparison by brand and region.

`index.html` is the finished page. It is a single self-contained file (data inlined, D3 from cdnjs), so it opens straight from disk or from GitHub Pages.

## Run it

```
pip install duckdb pandas numpy
python pipeline.py path/to/folder-with-e10.csv-and-stations.csv
```

This writes `data/*.json` and rebuilds `index.html` from `src/template.html`. It takes under ten seconds on the full extract (347,612 price records, 8,148 stations).

## What the pipeline does

1. **Prices.** Drops four pre-2026 dates (1964, 2006, 2020, 2025), 32 exact duplicates and 127 prices outside 0.75x to 1.40x of that day's national median. That band catches prices typed in pounds (1.5, 1.6), 999.9 placeholders and a 290p typo, while keeping real island prices of 200p to 210p.
2. **Stations.** Normalises brand spelling, flips 92 longitudes entered without their minus sign, moves 53 points that were more than 30 km from their postcode district to the district centre, and drops 12 that could not be placed. Costco sites are flagged as members only.
3. **Daily panel.** Each forecourt's last price of the day is carried forward until its next report, for at most 30 days. Averages are taken across forecourts per day, not across raw rows. A plain average of rows would over-weight the forecourts that change price most often.
4. **Snapshot.** Prices as at 1 October 2026 for the 7,765 forecourts that reported in the previous 30 days, plus the cheapest rival within three miles of each one.

## Checks

- The pipeline's average for 1 March (132.94p) is 0.1p from the RAC's published 132.83p.
- An independent pandas recomputation of the 1 October average (last price per forecourt, no carry-forward logic) gives 174.68p, the same as the pipeline.
- Station prices on the page were spot-checked against the raw CSV.

## Mobile

- One column, 640px maximum, system fonts (no web-font download), with charts that redraw to the container width.
- Every interaction works by tap: crosshair on the line chart, per-bar tooltips, and nearest-dot lookup on the map (a d3 quadtree).
- The map is drawn to a canvas, so 7,765 dots do not become 7,765 DOM nodes.
- The postcode input is 18px, so iOS does not zoom when it is tapped. Tap targets are at least 44px.
- Light and dark themes follow the device setting.
- Postcode lookup uses postcodes.io. Most outward codes (for example "LS1") also work offline, from district centres derived from the station data.
- Page weight is 236 KB gzipped plus D3 (90 KB gzipped). In production the station list would be split out and lazy-loaded, or served from an API that is refreshed daily.

## Data

Fuel Finder, Department for Energy Security and Net Zero, Open Government Licence v3.0. The raw CSVs are not included in this repository.

## AI use

Built with Claude Code (Anthropic, Claude Opus 5.5) at my direction. It profiled and cleaned the data, wrote `pipeline.py` and the front end, tested the page in a headless browser and drafted this README. The accompanying commentary has the full breakdown.
