# Backend for Land Cover Explorer

## Prerequisites

You will need the following installed:

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [docker](https://www.docker.com/) (Optional, for building and running `docker compose`)

## Installation

1. Install the dependencies:

   ```bash
   scripts/install
   ```

2. Copy `.env.example` to `.env` and fill in the values:

   ```bash
   cp .env.example .env
   ```

   This includes your Google Earth Engine service account credentials, the Earth Engine collections used (MODIS land cover, Hansen Global Forest Change, ESA CCI biomass), and your Global Forest Watch API credentials.

3. Prepare the distance-risk-score assets by running:

   ```bash
   scripts/export-distance-risk-assets
   ```

   This precomputes, for every supported country and forest-loss-year window, a raster of distance-to-forest-loss risk scores, and exports each one as an asset to your Earth Engine account. It runs against the GEE backend, so each export consumes your Earth Engine compute credits/quota — the script skips any asset that already exists, so it's safe to re-run and only pays for what's missing.

4. Start the Shiny app:

   ```bash
   scripts/shiny
   ```

### Usage

- Select a country from the drop-down and a year from the slider to update the map, the border re-centers on the selected country and click it to see its forest coverage for that year.
- Use the layer control to toggle between four map layers: forest cover, above-ground biomass risk, aggregate degradation risk, and the top 5 highest-risk regions (numbered badges).
- The aggregate risk score combines the biomass risk score with the forest-type risk score and the precomputed distance-to-forest-loss risk score (from step 3 above) into a single 0-9 scale, where 0 is low risk of degradation and 9 is high risk. If the distance-risk asset hasn't been exported yet for that country/year, a warning is shown and the aggregate score falls back to forest type + biomass only.
- The table below the map lists the top 5 country regions by highest-risk area for the selected year; the bar chart shows forest loss by driver over time for the selected country, sourced from Global Forest Watch.

## Project structure

```
backend/
├── data/
│   └── global_adm_borders.geojson   # Global administration boundaries for supported countries
├── scripts/
│   ├── install                      # Installs dependencies (uv sync)
│   ├── export-distance-risk-assets  # Precomputes distance-risk-score assets to Earth Engine
│   └── shiny                        # Launches the Shiny app
├── src/landcover_explorer/
│   ├── knowledgebase/                # Earth Engine & GFW preprocessing, land cover / biomass / degradation-risk stats
│   ├── settings/                     # App configuration, loaded from .env
│   └── shiny/
│       ├── app.py                    # Main Shiny app server and UI code
│       └── app_helpers.py            # Helper functions for the Shiny app
├── .env.example                      # Template for environment variables
└── pyproject.toml                    # Python dependencies
```

## Contact

Firza Riany (Geospatial Data Engineer)
Personal: firzariany2@gmail.com
Professional: firza@developmentseed.org
