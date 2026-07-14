"""
Helper for calculating land cover category coverage statistics.
Called from app.py — EE must already be initialised.
"""

import ee

from landcover_explorer.settings import Settings

settings = Settings()

REDUCTION_SCALE = settings.modis_collection_resolution

# Land area per country is constant across years — cache to avoid recomputing.
_land_area_cache: dict[str, float] = {}


def calculate_coverage(
    iso: str,
    year: int,
    country_geometry: ee.Geometry,
    forest_cover: ee.Image,
) -> dict:
    """
    Returns coverage statistics for a selected land cover category.

    Parameters
    ----------
    iso : str
        3-letter ISO country code.
    year : int
        Year of the land cover image.
    country_geometry : ee.Geometry
        Country boundary used for area reduction.
    forest_cover : ee.Image
        Masked EE image (unmasked = category present, masked elsewhere). Pixel
        values are ignored — coverage is derived from counting unmasked pixels,
        not summing pixel values, since values like a constant risk score are
        not area weights.

    Returns
    -------
    dict with keys: iso, year, category_area_ha, land_area_ha, coverage_pct
    """

    pixel_area_m2 = REDUCTION_SCALE**2

    if iso in _land_area_cache:
        # Land area already known — single GEE call for category pixel count only.
        category_pixel_count = (
            forest_cover
            .reduceRegion(
                reducer=ee.Reducer.count(),
                geometry=country_geometry,
                scale=REDUCTION_SCALE,
                maxPixels=1e9,
            )
            .get("remapped")
            .getInfo()
        )
        land_area_m2 = _land_area_cache[iso]
    else:
        # First visit for this country — combine both into one round trip.
        combined = ee.Image.cat([
            forest_cover.rename("category_pixels"),
            ee.Image(1).rename("land_pixels"),
        ])

        result = combined.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=country_geometry,
            scale=REDUCTION_SCALE,
            maxPixels=1e9,
        ).getInfo()
        category_pixel_count = result["category_pixels"]
        land_area_m2 = result["land_pixels"] * pixel_area_m2
        _land_area_cache[iso] = land_area_m2

    category_area_m2 = category_pixel_count * pixel_area_m2

    category_area_ha = category_area_m2 / 10_000
    land_area_ha = land_area_m2 / 10_000
    coverage_pct = (category_area_ha / land_area_ha * 100) if land_area_ha > 0 else 0.0

    return {
        "iso": iso,
        "year": year,
        "category_area_ha": round(category_area_ha, 2),
        "land_area_ha": round(land_area_ha, 2),
        "coverage_pct": round(coverage_pct, 2),
    }
