"""
Offline precompute of distance-to-forest-loss risk score assets for every supported
country x loss-year window, so the app never has to run a fastDistanceTransform export
inline. Safe to re-run: existing assets are left untouched.

Usage: uv run python scripts/export_distance_risk_assets.py
"""

import json
import time
from pathlib import Path

import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.distance_risk_assets import (
    LOSS_WINDOWS,
    distance_asset_exists,
    get_distance_asset_id,
    start_distance_risk_export,
)
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    FOREST_BAND_NAME,
    FOREST_COLLECTION,
    assign_forest_type_risk_score,
    load_image,
)
from landcover_explorer.knowledgebase.risk_stats import ISO_TO_ADM0_NAME

settings = Settings()

POLL_INTERVAL_SECONDS = 30


def _load_geometries() -> dict[str, ee.Geometry]:
    geojson_path = Path(__file__).parents[1] / settings.gadm_path
    with open(geojson_path) as f:
        gadm = json.load(f)

    isos = set(ISO_TO_ADM0_NAME)
    return {
        feature["properties"]["GID_0"]: ee.Geometry(feature["geometry"])
        for feature in gadm["features"]
        if feature["properties"]["GID_0"] in isos
    }


def main():
    credentials = ee.ServiceAccountCredentials(
        settings.google_earth_service_account, str(settings.google_earth_key)
    )
    ee.Initialize(credentials)

    geometries = _load_geometries()
    pending: list[tuple[str, int, int, ee.batch.Task]] = []

    for iso, geometry in geometries.items():
        for window_min, window_max in LOSS_WINDOWS:
            asset_id = get_distance_asset_id(iso, window_min, window_max)
            if distance_asset_exists(asset_id):
                print(f"[skip] {iso} {window_min}-{window_max}: asset already exists")
                continue

            # A representative year within the window — any year in it maps to the
            # same window via loss_year_window, and MODIS forest data covers window_max.
            select_year = window_max + 2000

            forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, select_year, geometry)
            if forest_dataset is None:
                print(f"[skip] {iso} {window_min}-{window_max}: no MODIS forest data for {select_year}")
                continue
            forest_mask = assign_forest_type_risk_score(forest_dataset)

            task = start_distance_risk_export(iso, select_year, geometry, forest_mask)
            print(f"[export] {iso} {window_min}-{window_max}: started task {task.id}")
            pending.append((iso, window_min, window_max, task))

    if not pending:
        print("Nothing to export — all assets already exist.")
        return

    print(f"\nWaiting on {len(pending)} export task(s)...")
    while any(task.active() for _, _, _, task in pending):
        for iso, window_min, window_max, task in pending:
            if task.active():
                print(f"  {iso} {window_min}-{window_max}: {task.status()['state']}")
        time.sleep(POLL_INTERVAL_SECONDS)

    print("\nDone:")
    for iso, window_min, window_max, task in pending:
        print(f"  {iso} {window_min}-{window_max}: {task.status()['state']}")


if __name__ == "__main__":
    main()
