import ee

from landcover_explorer.settings import Settings

settings = Settings()

FOREST_CODES = [int(x) for x in settings.forest_codes_in_collection.split(",")]

def compute_forest_mask(land_cover_dataset, geometry, select_year):
    
    image = land_cover_dataset.filter(
        ee.Filter.calendarRange(select_year, select_year, "year")
    ).first()

    forest = (
        image.remap(FOREST_CODES, [1] * len(FOREST_CODES), 0)
        .selfMask()
        .clip(geometry)
    )

    return forest
