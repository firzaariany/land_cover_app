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
import pandas as pd

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.distance_risk_assets import (
    LOSS_WINDOWS,
    distance_asset_exists,
    get_distance_asset_id,
    get_export_wait_seconds,
    load_distance_risk_score,
    start_distance_risk_export,
)
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    FOREST_BAND_NAME,
    FOREST_COLLECTION,
    aggregate_for_resampling,
    assign_biomass_risk_score,
    assign_forest_type_risk_score,
    compute_aggregate_risk_score,
    get_latest_available_year,
    load_image,
)
from landcover_explorer.knowledgebase.risk_stats import ISO_TO_ADM0_NAME, rank_admin1_by_risk3_area

settings = Settings()

POLL_INTERVAL_SECONDS = 30
ANNUAL_RISK_CSV_PATH = Path(__file__).parents[1] / "data" / "annual_risk_by_admin1.csv"
ANNUAL_FOREST_COVER_CSV_PATH = Path(__file__).parents[1] / "data" / "annual_forest_cover_by_admin1.csv"


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


def _load_forest_risk_score(
    iso: str, label: str, select_year: int, forest_year: int, geometry: ee.Geometry
) -> ee.Image | None:
    """MODIS forest cover for forest_year, remapped to a forest risk score. forest_year
    falls back from select_year when MODIS hasn't caught up yet (see callers); label is
    just what to print (a loss-year window or a single year). Returns None, after
    printing a [skip] message, if forest_year has no MODIS image at all.
    """
    forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, forest_year, geometry)
    if forest_dataset is None:
        print(f"[skip] {iso} {label}: no MODIS forest data for {forest_year}")
        return None
    if forest_year != select_year:
        print(
            f"[fallback] {iso} {label}: using {forest_year} forest cover "
            f"(no MODIS data for {select_year} yet)"
        )
    return assign_forest_type_risk_score(forest_dataset)


def compute_annual_risk_dataframe(
    iso: str, geometry: ee.Geometry, latest_forest_year: int
) -> pd.DataFrame:
    """Per-admin1 forest area at the highest aggregated risk score (3) for iso, for every
    year AGB has an image. AGB is the limiting input (MODIS forest cover and the distance
    risk assets both cover 2001+, but AGB only starts in 2007), so the year loop is driven
    off it. If an AGB year outruns the latest available MODIS forest cover, that latest
    MODIS year is reused rather than skipping the year entirely.

    Parameters
    ----------
    iso : str
        GADM ISO3 country code (must be a key of ISO_TO_ADM0_NAME).
    geometry : ee.Geometry
        Country boundary to clip forest/AGB imagery and rank admin1 regions within.
    latest_forest_year : int
        Most recent calendar year with a MODIS forest-cover image (see
        get_latest_available_year), used as the fallback forest year for any AGB
        year beyond it.

    Returns
    -------
    pd.DataFrame
        One row per (year, admin1 region) with columns:
        iso : str, year : int, region : str, risk3_area_km2 : float,
        distance_risk_available : bool (whether that year's distance risk asset had
        already been exported, vs. AGB/forest risk renormalized on their own).
    """
    agb_years = (
        ee.ImageCollection(settings.biomass_collection_id)
        .aggregate_array("system:time_start")
        .map(lambda t: ee.Date(t).get("year"))
        .distinct()
        .sort()
        .getInfo()
    )

    records = []
    for year in agb_years:
        forest_year = min(year, latest_forest_year)
        forest_risk_score_year = _load_forest_risk_score(iso, str(year), year, forest_year, geometry)
        if forest_risk_score_year is None:
            continue

        agb_100m_year = load_image(
            settings.biomass_collection_id, settings.biomass_collection_band_name, year, geometry
        )
        agb_aligned_year = aggregate_for_resampling(agb_100m_year)
        agb_risk_score_year = assign_biomass_risk_score(agb_aligned_year)

        # Reads back the asset exported above for year's 5-year Hansen loss window;
        # None if that (iso, window) hasn't been exported yet.
        distance_risk_score_year = load_distance_risk_score(iso, year)

        aggregate_risk_score_year = compute_aggregate_risk_score(
            agb_risk_score_year, forest_risk_score_year, distance_risk_score_year
        )

        for region in rank_admin1_by_risk3_area(iso, aggregate_risk_score_year):
            records.append({
                "iso": iso,
                "year": year,
                "region": region["name"],
                "risk3_area_km2": region["risk3_area_m2"] / 1e6,
                "distance_risk_available": distance_risk_score_year is not None,
            })

    return pd.DataFrame(records)


def compute_annual_forest_cover_dataframe(
    iso: str, geometry: ee.Geometry, latest_forest_year: int
) -> pd.DataFrame:
    """Per-admin1 forest area for iso, for every year MODIS forest cover has an image
    (2001+). Unlike compute_annual_risk_dataframe, this isn't gated on AGB or distance
    risk availability — it's driven directly off MODIS's own year list, since
    _load_forest_risk_score's forest risk score is a constant 3 wherever a pixel is
    forest (see assign_forest_type_risk_score) and masked otherwise, rank_admin1_by_risk3_area's
    round()==3 area sum over that image is exactly each admin1 region's forest area.

    Parameters
    ----------
    iso : str
        GADM ISO3 country code (must be a key of ISO_TO_ADM0_NAME).
    geometry : ee.Geometry
        Country boundary to clip forest imagery and rank admin1 regions within.
    latest_forest_year : int
        Most recent calendar year with a MODIS forest-cover image (see
        get_latest_available_year); years beyond this aren't expected in MODIS's own
        year list, so it's only used to sanity-cap the loop.

    Returns
    -------
    pd.DataFrame
        One row per (year, admin1 region) with columns:
        iso : str, year : int, region : str, forest_area_km2 : float.
    """
    forest_years = (
        ee.ImageCollection(FOREST_COLLECTION)
        .aggregate_array("system:time_start")
        .map(lambda t: ee.Date(t).get("year"))
        .distinct()
        .sort()
        .getInfo()
    )

    records = []
    for year in forest_years:
        if year > latest_forest_year:
            continue
        forest_risk_score_year = _load_forest_risk_score(iso, str(year), year, year, geometry)
        if forest_risk_score_year is None:
            continue

        for region in rank_admin1_by_risk3_area(iso, forest_risk_score_year):
            records.append({
                "iso": iso,
                "year": year,
                "region": region["name"],
                "forest_area_km2": region["risk3_area_m2"] / 1e6,
            })

    return pd.DataFrame(records)


def main():
    credentials = ee.ServiceAccountCredentials(
        settings.google_earth_service_account, str(settings.google_earth_key)
    )
    ee.Initialize(credentials)

    geometries = _load_geometries()
    latest_available_year = get_latest_available_year(FOREST_COLLECTION)
    pending: list[tuple[str, int, int, ee.batch.Task]] = []

    for iso, geometry in geometries.items():
        for window_min, window_max in LOSS_WINDOWS:
            asset_id = get_distance_asset_id(iso, window_min, window_max)
            if distance_asset_exists(asset_id):
                print(f"[skip] {iso} {window_min}-{window_max}: asset already exists")
                continue

            select_year = window_max + 2000
            forest_year = min(select_year, latest_available_year)

            forest_mask = _load_forest_risk_score(
                iso, f"{window_min}-{window_max}", select_year, forest_year, geometry
            )
            if forest_mask is None:
                continue

            wait_seconds = get_export_wait_seconds(iso, window_min, window_max)
            task = start_distance_risk_export(iso, select_year, geometry, forest_mask)
            print(
                f"[export] {iso} {window_min}-{window_max}: started task {task.id} "
                f"(est. wait ~{wait_seconds:.0f}s)"
            )
            pending.append((iso, window_min, window_max, task))

    if not pending:
        print("Nothing to export — all assets already exist.")
    else:
        print(f"\nWaiting on {len(pending)} export task(s)...")
        while any(task.active() for _, _, _, task in pending):
            for iso, window_min, window_max, task in pending:
                if task.active():
                    print(f"  {iso} {window_min}-{window_max}: {task.status()['state']}")
            time.sleep(POLL_INTERVAL_SECONDS)

        print("\nDone:")
        for iso, window_min, window_max, task in pending:
            print(f"  {iso} {window_min}-{window_max}: {task.status()['state']}")

    # TODO: Check unique years in CSV against data. If there are new years in the raw data, the computation can be appended to existed CSV
    if ANNUAL_RISK_CSV_PATH.exists():
        print(f"\n[skip] annual risk-by-admin1 dataframe already exists at {ANNUAL_RISK_CSV_PATH}")
    else:
        print("\nComputing annual risk-by-admin1 dataframe...")
        annual_risk_df = pd.concat(
            [
                compute_annual_risk_dataframe(iso, geometry, latest_available_year)
                for iso, geometry in geometries.items()
            ],
            ignore_index=True,
        )
        ANNUAL_RISK_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        annual_risk_df.to_csv(ANNUAL_RISK_CSV_PATH, index=False)
        print(f"Saved annual risk dataframe to {ANNUAL_RISK_CSV_PATH} ({len(annual_risk_df)} rows)")

    if ANNUAL_FOREST_COVER_CSV_PATH.exists():
        print(f"\n[skip] annual forest cover dataframe already exists at {ANNUAL_FOREST_COVER_CSV_PATH}")
    else:
        print("\nComputing annual forest cover dataframe...")
        annual_forest_cover_df = pd.concat(
            [
                compute_annual_forest_cover_dataframe(iso, geometry, latest_available_year)
                for iso, geometry in geometries.items()
            ],
            ignore_index=True,
        )
        ANNUAL_FOREST_COVER_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        annual_forest_cover_df.to_csv(ANNUAL_FOREST_COVER_CSV_PATH, index=False)
        print(
            f"Saved annual forest cover dataframe to {ANNUAL_FOREST_COVER_CSV_PATH} "
            f"({len(annual_forest_cover_df)} rows)"
        )


if __name__ == "__main__":
    main()
