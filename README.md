# Land Cover Visualization App

Land Cover Explorer is an interactive app for understanding which areas are at high risk of forest degradation. Degradation is inferred from two signals: a forest with low above-ground biomass at a given point in time, and its proximity to recent forest loss (distance to forest loss is precomputed in Google Earth Engine). This app is still under development.

Country coverage:

- Malaysia (MYS)
- Costa Rica (CRI)
- Norway (NOR)
- Indonesia (IDN)
- Democratic Republic of the Congo (COD)
- Japan (JPN)

## Features

- Interactive map with selectable country and year, recentering and zooming to the selected country's border.
- Forest cover, above-ground biomass risk, and aggregate degradation risk layers, rendered as tiles served directly from Google Earth Engine.
- Aggregate risk score combines forest type, biomass, and (where precomputed) distance-to-forest-loss into a single risk layer.
- Top 5 highest-risk regions highlighted on the map with rank badges, plus a matching ranked data table.
- Click-to-view popup showing forest cover percentage for the selected country/year.
- Forest loss by driver chart (stacked bar) sourced from Global Forest Watch data.

## Data sources

- [MODIS Land Cover Type (MCD12Q1)](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD12Q1) - forest cover and forest subtype classification.
- [Hansen Global Forest Change](https://developers.google.com/earth-engine/datasets/catalog/UMD_hansen_global_forest_change_2024_v1_12) - forest loss extent and loss year, used to derive distance to forest loss.
- [ESA CCI Above-Ground Biomass](https://developers.google.com/earth-engine/datasets/catalog/ESA_CCI_AboveGroundBiomass_V6_0) - above-ground biomass (Mg/ha) used for biomass risk scoring.
- [GADM](https://gadm.org/) - global administrative boundaries for country and region borders.
- [Global Forest Watch API](https://www.globalforestwatch.org/) - forest loss by driver statistics.

All Earth Engine datasets are accessed live via a Google Earth Engine service account; dataset IDs and credentials are configured in `backend/.env.example`.

## Getting started

1. Clone this repository

```
git clone https://github.com/firzaariany/land_cover_app.git
cd land_cover_app
```

2. All app code lives in `backend/` — see [backend/README.md](backend/README.md) for prerequisites, installation, and usage.

## Project structure

```
land_cover_app/backend/
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

## Notes

- This app is still under development.
- The aggregate risk score falls back to forest type + biomass only if the distance-to-forest-loss asset hasn't been exported yet for a given country/year.
- This app is designed for local use and development; adapt paths and hosting for production.

## Contact

Firza Riany (Geospatial Data Engineer)
Personal: firzariany2@gmail.com
Professional: firza@developmentseed.org
