import ee

from landcover_explorer.settings import Settings

settings = Settings()

FOREST_CODES = [int(x) for x in settings.forest_codes_in_collection.split(",")]
AGRICULTURE_CODES = [int(x) for x in settings.agriculture_codes_in_collection.split(",")]
SETTLEMENT_CODES = [int(x) for x in settings.settlements_codes_in_collection.split(",")]
HANSEN_DATASET = settings.hansen_dataset


def _compute_mask(land_cover_dataset, geometry, select_year, codes):
    image = land_cover_dataset.filter(
        ee.Filter.calendarRange(select_year, select_year, "year")
    ).first()
    return (
        image.remap(codes, [1] * len(codes), 0)
        .selfMask()
        .clip(geometry)
    )


def compute_modis_forest_mask(land_cover_dataset, geometry, select_year):
    """Raw MODIS forest pixels for select_year, with no Hansen loss adjustment."""
    return _compute_mask(land_cover_dataset, geometry, select_year, FOREST_CODES)


def compute_forest_mask(land_cover_dataset, geometry, select_year, loss_threshold=0.5):
    """MODIS forest pixels in select_year, excluding pixels where >loss_threshold fraction
    of their area shows cumulative Hansen loss up to select_year."""
    forest = compute_modis_forest_mask(land_cover_dataset, geometry, select_year)

    lossyear = ee.Image(HANSEN_DATASET).select("lossyear")
    cumulative_loss_30m = lossyear.lte(select_year - 2000).And(lossyear.gt(0)).toFloat()

    # Average Hansen 30m sub-pixels within each 500m MODIS cell
    loss_fraction = (
        cumulative_loss_30m
        .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
        .reproject(crs=forest.projection(), scale=forest.projection().nominalScale())
    )

    return forest.updateMask(loss_fraction.lte(loss_threshold))


def compute_agriculture_mask(land_cover_dataset, geometry, select_year):
    return _compute_mask(land_cover_dataset, geometry, select_year, AGRICULTURE_CODES)


def compute_settlement_mask(land_cover_dataset, geometry, select_year):
    return _compute_mask(land_cover_dataset, geometry, select_year, SETTLEMENT_CODES)


def compute_forest_loss_mask(geometry, select_year):
    lossyear = ee.Image(HANSEN_DATASET).select("lossyear")
    return (
        lossyear.lte(select_year - 2000)
        .And(lossyear.gt(0))
        .selfMask()
        .clip(geometry)
    )
