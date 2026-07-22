"""
Helper for ranking admin1 (state/province) regions by highest-risk forest area.
Called from app.py — EE must already be initialised.
"""

import ee

from landcover_explorer.settings import Settings

settings = Settings()

ADMIN1_COLLECTION = "FAO/GAUL/2015/level1"
REDUCTION_SCALE = settings.modis_collection_resolution

# GAUL's ADM0_NAME uses spaced country names (e.g. "Costa Rica", "New Zealand"), unlike
# GADM's COUNTRY property which drops spaces ("CostaRica", "NewZealand") — so the two
# can't be used interchangeably as a join key. Keep this mapping explicit rather than
# reading it off the GADM feature.
# TODO: Can the function take the keys to shiny's reactive select_iso?
ISO_TO_ADM0_NAME = {
    "MYS": "Malaysia",
    "CRI": "Costa Rica",
    "NOR": "Norway",
    "IDN": "Indonesia",
    "COD": "Democratic Republic of the Congo",
    "JPN": "Japan",
}

MAX_RISK_SCORE = 3


def get_admin1_regions(iso: str) -> ee.FeatureCollection:
    """FAO GAUL admin1 (state/province) boundaries for iso, matched by ADM0_NAME
    via ISO_TO_ADM0_NAME rather than geometry, since GAUL and GADM boundaries don't
    align exactly and filterBounds could pull in slivers of neighboring countries."""
    adm0_name = ISO_TO_ADM0_NAME[iso]
    return ee.FeatureCollection(ADMIN1_COLLECTION).filter(
        ee.Filter.eq("ADM0_NAME", adm0_name)
    )


def _sorted_admin1_risk3_collection(
    iso: str,
    aggregate_risk_score: ee.Image,
    scale: int = REDUCTION_SCALE,
) -> ee.FeatureCollection:
    """admin1 regions within iso, each carrying a risk3_area_m2 property (highest-risk —
    rounded score == MAX_RISK_SCORE — forest area), sorted descending.

    round() guards against floating-point noise in aggregate_risk_score (weighted sums can
    land at e.g. 3.0000000000000004 rather than exactly 3.0). Stays on the EE side (no
    getInfo()) so callers can keep composing — e.g. .limit(n) — before paying for a
    round trip.
    """
    admin1_regions = get_admin1_regions(iso)

    risk3_mask = aggregate_risk_score.round().eq(MAX_RISK_SCORE)
    risk3_area_m2 = risk3_mask.multiply(ee.Image.pixelArea())

    admin1_risk3_area = risk3_area_m2.reduceRegions(
        collection=admin1_regions,
        reducer=ee.Reducer.sum().setOutputs(["risk3_area_m2"]),
        scale=scale,
        tileScale=4,
    )
    return admin1_risk3_area.sort("risk3_area_m2", False)


def rank_admin1_by_risk3_area(
    iso: str,
    aggregate_risk_score: ee.Image,
    scale: int = REDUCTION_SCALE,
) -> list[dict]:
    """Rank admin1 regions within iso by their highest-risk forest area, descending.

    Returns
    -------
    list of dicts, one per admin1 region, sorted by risk3_area_m2 descending:
        {"name": ADM1_NAME, "risk3_area_m2": float, "geometry": GeoJSON geometry dict}
    """
    ranked = _sorted_admin1_risk3_collection(iso, aggregate_risk_score, scale).getInfo()["features"]

    return [
        {
            "name": feature["properties"]["ADM1_NAME"],
            "risk3_area_m2": feature["properties"]["risk3_area_m2"],
            "geometry": feature["geometry"],
        }
        for feature in ranked
    ]


def top_n_admin1_by_risk3_area(
    iso: str,
    aggregate_risk_score: ee.Image,
    n: int = 5,
    scale: int = REDUCTION_SCALE,
) -> list[dict]:
    """Convenience wrapper over rank_admin1_by_risk3_area returning only the top n regions."""
    return rank_admin1_by_risk3_area(iso, aggregate_risk_score, scale=scale)[:n]


def top_n_admin1_collection_by_risk3_area(
    iso: str,
    aggregate_risk_score: ee.Image,
    n: int = 5,
    scale: int = REDUCTION_SCALE,
) -> ee.FeatureCollection:
    """EE-side top n admin1 regions by risk3_area_m2 — for building a highlight tile
    (see build_highlight_image) without paying for a getInfo() round trip."""
    return _sorted_admin1_risk3_collection(iso, aggregate_risk_score, scale).limit(n)


def build_highlight_image(collection: ee.FeatureCollection, color: str = "ff00ff") -> ee.Image:
    """Solid outline over collection's features, so they stand out against the admin1
    boundary/risk layers underneath (e.g. top-5 highest-risk regions)."""
    outline = ee.Image().byte().paint(featureCollection=collection, color=1, width=4)
    return outline.visualize(palette=[color])
