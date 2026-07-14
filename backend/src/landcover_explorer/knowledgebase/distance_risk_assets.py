"""
Distance-to-forest-loss risk score is expensive to compute (a fastDistanceTransform
over the whole country), so it's precomputed offline as a GEE asset per (iso, loss-year
window) — see scripts/export_distance_risk_assets.py. This module is the shared
read/write surface for those assets: naming, existence checks, historical export
duration, and the export itself (reused by both the offline script and any on-demand
fallback in the app).
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    assign_distance_risk_score,
    aggregate_for_resampling,
    compute_distance_to_loss,
    load_recent_forest_loss,
    loss_year_window,
)

settings = Settings()

ASSET_DESCRIPTION_PREFIX = "distance_risk_score"
DEFAULT_EXPORT_WAIT_SECONDS = 300.0  # fallback estimate when no export history exists yet

# Wait-time estimates are cached per iso here since querying EE operation history is a
# one-off cost per country, not something every request should pay for.
EXPORT_WAIT_CACHE_PATH = Path(__file__).parents[3] / settings.distance_export_wait_cache_path
_EXPORT_WAIT_CACHE_FIELDS = ["iso", "estimated_wait_seconds", "computed_at"]

# Every select_year in 2001-2025 falls into one of these 5 fixed windows (see
# loss_year_window) — this is the full set of assets export_distance_risk_assets.py
# needs to produce per country.
LOSS_WINDOWS = sorted({loss_year_window(year) for year in range(2001, 2026)})


def get_distance_asset_id(iso: str, window_min: int, window_max: int) -> str:
    """Asset path for iso's distance risk score over Hansen loss-year window
    [window_min, window_max] (years since 2000, as returned by loss_year_window)."""
    return (
        f"projects/{settings.google_earth_project_id}/assets/"
        f"{ASSET_DESCRIPTION_PREFIX}_{iso}_{window_min}_{window_max}"
    )


def distance_asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def load_distance_risk_score(iso: str, select_year: int) -> ee.Image | None:
    """Read the precomputed distance risk score asset for select_year's loss-year
    window, or None if it hasn't been exported yet (see export_distance_risk_assets.py)."""
    window_min, window_max = loss_year_window(select_year)
    asset_id = get_distance_asset_id(iso, window_min, window_max)
    return ee.Image(asset_id) if distance_asset_exists(asset_id) else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def estimate_export_wait_seconds(
    iso: str, default: float = DEFAULT_EXPORT_WAIT_SECONDS
) -> float:
    """Average wall-clock duration of past successful distance risk score exports for
    iso, from this account's EE operation history. Falls back to `default` if there's
    no prior export for iso to learn from (e.g. first-ever run for that country).

    This is the expensive, uncached calculation — prefer get_export_wait_seconds(iso),
    which only calls this once per country and reuses the CSV-cached result after that.
    """
    description_prefix = f"{ASSET_DESCRIPTION_PREFIX}_{iso}_"
    durations = []
    for operation in ee.data.listOperations():
        metadata = operation.get("metadata", {})
        description = metadata.get("description", "")
        if not description.startswith(description_prefix):
            continue
        if metadata.get("state") != "SUCCEEDED":
            continue

        start = _parse_timestamp(metadata.get("startTime") or metadata.get("createTime"))
        end = _parse_timestamp(metadata.get("endTime") or metadata.get("updateTime"))
        if start is None or end is None:
            continue
        durations.append((end - start).total_seconds())

    if not durations:
        return default
    return sum(durations) / len(durations)


def _read_export_wait_cache() -> dict[str, float]:
    if not EXPORT_WAIT_CACHE_PATH.exists():
        return {}
    with open(EXPORT_WAIT_CACHE_PATH, newline="") as f:
        return {row["iso"]: float(row["estimated_wait_seconds"]) for row in csv.DictReader(f)}


def _append_export_wait_cache(iso: str, wait_seconds: float) -> None:
    EXPORT_WAIT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not EXPORT_WAIT_CACHE_PATH.exists()
    with open(EXPORT_WAIT_CACHE_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_EXPORT_WAIT_CACHE_FIELDS)
        if is_new_file:
            writer.writeheader()
        writer.writerow({
            "iso": iso,
            "estimated_wait_seconds": round(wait_seconds, 1),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        })


def get_export_wait_seconds(iso: str) -> float:
    """Estimated export wait time for iso, cached in EXPORT_WAIT_CACHE_PATH so the EE
    operation history only gets queried once per country. Every call after the first
    for a given iso is a plain CSV read — call this rather than
    estimate_export_wait_seconds directly.
    """
    cached = _read_export_wait_cache()
    if iso in cached:
        return cached[iso]

    wait_seconds = estimate_export_wait_seconds(iso)
    _append_export_wait_cache(iso, wait_seconds)
    return wait_seconds


def start_distance_risk_export(
    iso: str,
    select_year: int,
    geometry: ee.Geometry,
    forest_mask: ee.Image,
    scale: int = settings.modis_collection_resolution,
) -> ee.batch.Task:
    """Compute and start an async export of the distance risk score for select_year's
    loss-year window, aligned to `scale` (the forest dataset's resolution). Caller is
    responsible for polling task.status() until state is COMPLETED/FAILED, then reading
    the asset back via load_distance_risk_score.

    forest_mask should be the same-year assign_forest_type_risk_score output used
    elsewhere, so loss is restricted to pixels that were actually forest.
    """
    window_min, window_max = loss_year_window(select_year)
    asset_id = get_distance_asset_id(iso, window_min, window_max)

    loss_recent = load_recent_forest_loss(select_year, geometry=geometry, forest_mask=forest_mask)
    distance_m = compute_distance_to_loss(loss_recent, geometry=geometry)
    distance_risk_score = assign_distance_risk_score(distance_m)
    aligned = aggregate_for_resampling(distance_risk_score)

    task = ee.batch.Export.image.toAsset(
        image=aligned,
        description=f"{ASSET_DESCRIPTION_PREFIX}_{iso}_{window_min}_{window_max}",
        assetId=asset_id,
        region=geometry,
        scale=scale,
        maxPixels=1e10,
    )
    task.start()
    return task
