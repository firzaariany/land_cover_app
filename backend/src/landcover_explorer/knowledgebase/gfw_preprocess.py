import pandas as pd
import requests

from landcover_explorer.settings import Settings

settings = Settings()

_GFW_QUERY = (
    f"{settings.gfw_api_url}/{settings.gfw_dataset}/{settings.gfw_dataset_version}/query"
)

_DRIVER_CLASS_MAP = {
    "Hard commodities":             "Deforestation",
    "Permanent agriculture":        "Deforestation",
    "Settlements & Infrastructure": "Deforestation",
    "Logging":                      "Temporary disturbances",
    "Other natural disturbances":   "Temporary disturbances",
    "Wildfire":                     "Temporary disturbances",
    "Shifting cultivation":         "Temporary disturbances",
}

_SQL_TEMPLATE = """
SELECT
    wri_google_tree_cover_loss_drivers__driver,
    umd_tree_cover_loss__year,
    SUM(umd_tree_cover_loss__ha) AS umd_tree_cover_loss__ha,
    SUM("gfw_gross_emissions_co2e_all_gases__Mg") AS gfw_gross_emissions_co2e_all_gases__Mg
FROM data
WHERE iso = '{iso}'
    AND umd_tree_cover_density_2000__threshold = 30
    AND wri_google_tree_cover_loss_drivers__driver IS NOT NULL
GROUP BY
    wri_google_tree_cover_loss_drivers__driver,
    umd_tree_cover_loss__year
"""


def fetch_forest_loss_by_driver(iso: str) -> pd.DataFrame:
    """Fetch tree cover loss by driver from the GFW API for a given country ISO code.

    Adds a ``large_driver_class`` column grouping sub-drivers into
    ``"Deforestation"`` or ``"Temporary disturbances"``.
    """
    headers = {
        "Authorization": f"Bearer {settings.gfw_access_token}",
        "x-api-key": settings.gfw_api_key,
    }
    response = requests.get(
        _GFW_QUERY,
        headers=headers,
        params={"sql": _SQL_TEMPLATE.format(iso=iso)},
    )
    if not response.ok:
        raise RuntimeError(
            f"GFW API error {response.status_code} for {iso}: {response.text[:200]}"
        )

    df = pd.DataFrame(response.json()["data"])
    df["large_driver_class"] = df["wri_google_tree_cover_loss_drivers__driver"].map(
        _DRIVER_CLASS_MAP
    )
    return df
