import ee
import geopandas as gpd
from shapely.geometry import shape

from landcover_explorer.settings import Settings

settings = Settings()

tile_collection_resolution = settings.modis_collection_resolution

FOREST_COLLECTION = settings.modis_collection_id
FOREST_BAND_NAME = settings.modis_collection_band_name
FOREST_CODES = [int(x) for x in settings.modis_forest_codes.split(",")]
FOREST_COLOR_MAP = dict(zip(FOREST_CODES, settings.modis_forest_colors.split(",")))
FOREST_TYPE_LABELS = dict(zip(FOREST_CODES, settings.modis_forest_labels.split(",")))

FOREST_CHANGE_DATASET = settings.forest_change_collection_id
FOREST_CHANGE_BAND_NAME = settings.forest_change_collection_band_name

BIOMASS_BAND_NAME = settings.biomass_collection_band_name

FOREST_RISK_SCORE = 3


def load_image(
    collection_id: str, band_name: str, select_year: int, geometry: ee.Geometry
) -> ee.Image | None:
    """Load a single band image for select_year from collection_id, clipped to geometry.

    Returns None if collection_id has no image for select_year.
    """
    filtered = ee.ImageCollection(collection_id).select(band_name).filter(
        ee.Filter.calendarRange(select_year, select_year, "year")
    )
    if filtered.size().getInfo() == 0:
        return None
    return filtered.first().clip(geometry)


def reproject_to_reference(
    image: ee.Image,
    reference_image: ee.Image,
    max_pixels: int = 1024,
) -> ee.Image:
    """Aggregate image's finer-resolution pixels with reducer and reproject to
    reference_image's projection."""
    return image.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=max_pixels).reproject(
        crs=reference_image.projection()
    )


def assign_forest_type_risk_score(image: ee.Image) -> ee.Image:
    """Remap MODIS LC_Prop1 forest codes to a constant forest risk score of 3.
    Non-forest pixels are masked by remap's default behavior (any code not listed
    is masked when no defaultValue is given).
    """
    codes = list(FOREST_COLOR_MAP.keys())
    risk_scores = [FOREST_RISK_SCORE] * len(codes)
    return image.remap(codes, risk_scores)


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
