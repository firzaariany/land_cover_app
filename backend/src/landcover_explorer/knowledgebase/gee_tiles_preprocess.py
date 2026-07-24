import math

import ee
import geopandas as gpd
from shapely.geometry import shape

from landcover_explorer.settings import Settings

# TODO: Clean up values import
settings = Settings()

tile_collection_resolution = settings.modis_collection_resolution

FOREST_COLLECTION = settings.modis_collection_id
FOREST_BAND_NAME = settings.modis_collection_band_name
FOREST_CODES = [int(x) for x in settings.modis_forest_codes.split(",")]
FOREST_COLOR_MAP = dict(zip(FOREST_CODES, settings.modis_forest_colors.split(",")))
FOREST_TYPE_LABELS = dict(zip(FOREST_CODES, settings.modis_forest_labels.split(",")))

FOREST_CHANGE_DATASET = settings.forest_change_collection_id
FOREST_CHANGE_BINARY = settings.forest_change_binary_band_name

BIOMASS_BAND_NAME = settings.biomass_collection_band_name

FOREST_RISK_SCORE = 3
MAX_DISTANCE_TO_LOSS_M = 3000

AGB_RISK_WEIGHT = 0.4
FOREST_RISK_WEIGHT = 0.2
DISTANCE_RISK_WEIGHT = 0.4


def load_image(
    collection_id: str,
    band_name: str,
    select_year: int,
    geometry: ee.Geometry | None = None,
) -> ee.Image | None:
    """Load a single band image for select_year from collection_id. Clipped to geometry
    if given, otherwise left at global extent.

    Returns None if collection_id has no image for select_year.
    """
    filtered = ee.ImageCollection(collection_id).select(band_name).filter(
        ee.Filter.calendarRange(select_year, select_year, "year")
    )
    if filtered.size().getInfo() == 0:
        return None
    image = filtered.first()
    return image.clip(geometry) if geometry is not None else image


def get_latest_available_year(collection_id: str) -> int:
    """Calendar year of the most recent image in collection_id."""
    latest_image = ee.ImageCollection(collection_id).sort("system:time_start", False).first()
    return ee.Date(latest_image.get("system:time_start")).get("year").getInfo()


def load_forest_change_image(band_name: str, geometry: ee.Geometry | None = None) -> ee.Image:
    """Load a single band from the Hansen Global Forest Change image. Clipped to geometry
    if given, otherwise left at global extent."""
    image = ee.Image(FOREST_CHANGE_DATASET).select(band_name)
    return image.clip(geometry) if geometry is not None else image


def loss_year_window(select_year: int) -> tuple[int, int]:
    """Map select_year to its deterministic 5-year Hansen loss-year bucket (years since
    2000): 2001-2005 -> (1, 5), 2006-2010 -> (6, 10), 2011-2015 -> (11, 15),
    2016-2020 -> (16, 20), 2021-2025 -> (21, 25)."""
    year = select_year - 2000
    window_max = math.ceil(year / 5) * 5
    window_min = window_max - 4
    return window_min, window_max


def load_recent_forest_loss(
    select_year: int,
    geometry: ee.Geometry | None = None,
    forest_mask: ee.Image | None = None,
) -> ee.Image:
    """Load Hansen binary forest loss masked to pixels whose loss year falls within
    select_year's 5-year bucket (see loss_year_window). Global extent unless geometry
    is given — pass None so the distance transform isn't truncated at a country border.
    If forest_mask is given (e.g. assign_forest_type_risk_score's output), loss is
    further restricted to pixels that were forest, so non-forest disturbance isn't
    counted as forest loss."""
    lossyear = load_forest_change_image(settings.forest_change_loss_year_band_name, geometry)
    loss = load_forest_change_image(FOREST_CHANGE_BINARY, geometry)
    window_min, window_max = loss_year_window(select_year)
    year_mask = lossyear.gte(window_min).And(lossyear.lte(window_max))
    loss = loss.updateMask(year_mask)
    if forest_mask is not None:
        loss = loss.updateMask(forest_mask.mask())
    return loss


def aggregate_for_resampling(image: ee.Image, max_pixels: int = 1024) -> ee.Image:
    """Mark image for mean-aggregation of its finer-resolution pixels whenever it is later
    implicitly resampled to a coarser projection — e.g. by combining with another image,
    by reduceRegion, or by tile rendering. Does not force an eager reprojection, so each
    caller resamples lazily at whatever scale it actually needs."""
    return image.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=max_pixels)


def assign_forest_type_risk_score(image: ee.Image) -> ee.Image:
    """Remap MODIS LC_Prop1 forest codes to a constant forest risk score of 3.
    Non-forest pixels are masked by remap's default behavior (any code not listed
    is masked when no defaultValue is given).
    """
    codes = list(FOREST_COLOR_MAP.keys())
    risk_scores = [FOREST_RISK_SCORE] * len(codes)
    return image.remap(codes, risk_scores)


def compute_distance_to_loss(
    loss: ee.Image,
    max_distance_m: int = MAX_DISTANCE_TO_LOSS_M,
    geometry: ee.Geometry | None = None,
) -> ee.Image:
    """Compute each pixel's distance (in meters) to the nearest binary forest-loss pixel,
    via a single fastDistanceTransform over the neighborhood implied by max_distance_m.
    fastDistanceTransform doesn't inherit loss's footprint, so pass geometry to clip the
    output — otherwise distances render/export beyond loss's clipped extent."""
    neighborhood_pixels = math.ceil(max_distance_m / settings.forest_change_collection_resolution)
    distance_m = (
        loss.selfMask()
        .fastDistanceTransform(neighborhood=neighborhood_pixels, units="pixels")
        .sqrt()
        .multiply(settings.forest_change_collection_resolution)
        .setDefaultProjection(loss.projection())
    )
    return distance_m.clip(geometry) if geometry is not None else distance_m


def assign_distance_risk_score(
    distance_m: ee.Image, max_distance_m: int = MAX_DISTANCE_TO_LOSS_M
) -> ee.Image:
    """Reclassify distance-to-loss (meters) into a 0-3 risk score: <500m -> 3,
    500-1000m -> 2, 1000-2000m -> 1, 2000-max_distance_m -> 0. Pixels farther than
    max_distance_m are masked out."""
    return (
        ee.Image(0)
        .where(distance_m.gte(1000).And(distance_m.lt(2000)), 1)
        .where(distance_m.gte(500).And(distance_m.lt(1000)), 2)
        .where(distance_m.lt(500), 3)
        .updateMask(distance_m.lte(max_distance_m))
        .setDefaultProjection(distance_m.projection())
    )


def assign_biomass_risk_score(image: ee.Image) -> ee.Image:
    """Map AGB values to a risk score: 0 -> 0, (0, 50] -> 1, (50, 200] -> 2,
    (200, 500] -> 3. Masked/NaN input pixels remain masked in the output."""
    return (
        ee.Image(0)
        .where(image.gt(0).And(image.lte(50)), 1)
        .where(image.gt(50).And(image.lte(200)), 2)
        .where(image.gt(200).And(image.lte(500)), 3)
        .updateMask(image.mask())
    )


def compute_aggregate_risk_score(
    agb_risk_score: ee.Image,
    forest_risk_score: ee.Image,
    distance_risk_score: ee.Image | None,
) -> ee.Image:
    """Combine the 0-3 risk score layers into a single weighted 0-3 risk score.

    Aggregate = AGB_RISK_WEIGHT*AGB + FOREST_RISK_WEIGHT*Forest + DISTANCE_RISK_WEIGHT*Distance.
    All inputs must already share a projection/resolution (e.g. via
    aggregate_for_resampling), since this is a plain pixel-wise combination.

    Pass distance_risk_score=None when it isn't available yet (e.g. its asset hasn't
    been exported — see distance_risk_assets.py) rather than substituting a 0 image:
    a 0 contribution still caps the weighted sum below 3 (0.4*3 + 0.2*3 = 1.8), so
    round(aggregate) would never reach the max risk score. Instead, the remaining
    weights are renormalized so the same 0-3 scale — and thus any MAX_RISK_SCORE-based
    thresholding downstream (see risk_stats.py) — still holds.
    """
    if distance_risk_score is not None:
        return (
            agb_risk_score.multiply(AGB_RISK_WEIGHT)
            .add(forest_risk_score.multiply(FOREST_RISK_WEIGHT))
            .add(distance_risk_score.multiply(DISTANCE_RISK_WEIGHT))
        )

    active_weight_total = AGB_RISK_WEIGHT + FOREST_RISK_WEIGHT
    return agb_risk_score.multiply(AGB_RISK_WEIGHT / active_weight_total).add(
        forest_risk_score.multiply(FOREST_RISK_WEIGHT / active_weight_total)
    )


### START: TO BE DELETED ###
# def _compute_loss_fraction(reference_image, select_year, geometry):
#     """Hansen cumulative loss fraction (0–1) per pixel, reprojected to reference_image's scale."""
#     lossyear = ee.Image(FOREST_CHANGE_DATASET).select(FOREST_CHANGE_BAND_NAME).clip(geometry)
#     cumulative_loss_30m = lossyear.lte(select_year - 2000).And(lossyear.gt(0)).selfMask()
#     return cumulative_loss_30m.updateMask(reference_image)


# def _compute_mask(land_cover_dataset, geometry, select_year, codes):
#     image = land_cover_dataset.filter(
#         ee.Filter.calendarRange(select_year, select_year, "year")
#     ).first()
#     return image.remap(codes, [1] * len(codes), 0).selfMask().clip(geometry)


# def compute_modis_forest_mask(land_cover_dataset, geometry, select_year):
#     """Raw MODIS forest pixels for select_year, with no Hansen loss adjustment."""
#     return _compute_mask(land_cover_dataset, geometry, select_year, FOREST_CODES)


# def compute_forest_type_mask(land_cover_dataset, geometry, select_year):
#     """MODIS forest pixels for select_year, remapped via assign_forest_type_risk_score."""
#     image = land_cover_dataset.filter(
#         ee.Filter.calendarRange(select_year, select_year, "year")
#     ).first()
#     return assign_forest_type_risk_score(image).clip(geometry)


# def compute_forest_loss_mask(geometry, select_year):
#     lossyear = ee.Image(FOREST_CHANGE_DATASET).select(FOREST_CHANGE_BAND_NAME)
#     return (
#         lossyear.lte(select_year - 2000).And(lossyear.gt(0)).selfMask().clip(geometry)
#     )


# def compute_forest_mask(land_cover_dataset, geometry, select_year, loss_threshold=0.5):
#     """MODIS forest pixels in select_year, excluding pixels where >loss_threshold fraction
#     of their area shows cumulative Hansen loss up to select_year."""
#     forest = compute_modis_forest_mask(land_cover_dataset, geometry, select_year)
#     loss_fraction = _compute_loss_fraction(forest, select_year)
#     return forest.updateMask(loss_fraction.lte(loss_threshold))


# def compute_agriculture_mask(land_cover_dataset, geometry, select_year):
#     return _compute_mask(land_cover_dataset, geometry, select_year, AGRICULTURE_CODES)


# def compute_settlement_mask(land_cover_dataset, geometry, select_year):
#     return _compute_mask(land_cover_dataset, geometry, select_year, SETTLEMENT_CODES)


# def aggregate_forest_loss_area_by_admin1(country_name, forest_loss_mask):
#     """Sum cumulative forest loss area (m²) for each admin-1 region within a country.

#     Multiplies each loss pixel by its pixel area and reduces over FAO GAUL level-1
#     boundaries, producing a FeatureCollection where every feature carries a
#     ``loss_area_m2`` property.
#     """
#     admin1_regions = ee.FeatureCollection("FAO/GAUL/2015/level1").filter(
#         ee.Filter.eq("ADM0_NAME", country_name)
#     )
#     admin1_loss_areas = (
#         forest_loss_mask.multiply(ee.Image.pixelArea())
#         .reduceRegions(
#             collection=admin1_regions,
#             reducer=ee.Reducer.sum().setOutputs(["loss_area_m2"]),
#             scale=tile_collection_resolution,
#             tileScale=4,
#         )
#     )
#     return admin1_loss_areas


# def extract_admin1_metric_centroids(admin1_collection, value_property):
#     """Convert an admin-1 FeatureCollection into a list of centroid records.

#     Computes the geometric centroid of each admin-1 polygon and returns only
#     those regions where ``value_property`` is a positive number, keyed under
#     its own name so callers (e.g. ``build_loss_markers``) can pass it through.
#     """
#     admin1_features = admin1_collection.getInfo()["features"]
#     state_centroids = []
#     for feature in admin1_features:
#         value = feature["properties"].get(value_property) or 0
#         if value > 0:
#             state_centroids.append({
#                 "lat": shape(feature["geometry"]).centroid.y,
#                 "lon": shape(feature["geometry"]).centroid.x,
#                 value_property: value,
#                 "name": feature["properties"].get("ADM1_NAME", ""),
#             })
#     return state_centroids


# def compute_state_forest_loss_in_settlements(
#     land_cover_dataset, geometry, select_year, select_country
# ):
#     """MODIS pixels (forest 2001 → settlement select_year) confirmed by Hansen loss.

#     Returns
#     -------
#     mask : ee.Image
#         Binary MODIS mask of converted pixels where loss_fraction > loss_threshold.
#     points : list[dict]
#         200 randomly sampled loss points as {lat, lon, loss_fraction}.
#     """
#     # was_forest = _compute_mask(land_cover_dataset, geometry, 2001, FOREST_CODES)
#     is_settlement = _compute_mask(land_cover_dataset, geometry, select_year, SETTLEMENT_CODES)
#     # converted = was_forest.updateMask(is_settlement)
#     loss_fraction = _compute_loss_fraction(is_settlement, select_year, geometry=geometry)

#     loss_in_settlement_by_state = aggregate_forest_loss_area_by_admin1(select_country, loss_fraction)
#     loss_in_settlement_centroid = extract_admin1_metric_centroids(loss_in_settlement_by_state, "loss_area_m2")

#     return loss_fraction, loss_in_settlement_centroid


# def compute_state_forest_loss_in_agriculture(
#     land_cover_dataset, geometry, select_year, select_country
# ):
#     """MODIS pixels (forest 2001 → settlement select_year) confirmed by Hansen loss.

#     Returns
#     -------
#     mask : ee.Image
#         Binary MODIS mask of converted pixels where loss_fraction > loss_threshold.
#     points : list[dict]
#         200 randomly sampled loss points as {lat, lon, loss_fraction}.
#     """
#     is_agriculture = _compute_mask(land_cover_dataset, geometry, select_year, AGRICULTURE_CODES)
#     loss_fraction = _compute_loss_fraction(is_agriculture, select_year, geometry=geometry)

#     loss_in_agriculture_by_state = aggregate_forest_loss_area_by_admin1(select_country, loss_fraction)
#     loss_in_agriculture_centroid = extract_admin1_metric_centroids(loss_in_agriculture_by_state, "loss_area_m2")

#     return loss_fraction, loss_in_agriculture_centroid
### END: TO BE DELETED ###
