from typing import Literal

from pathlib import Path

from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVEL = Literal[
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]

class Settings(BaseSettings):
    google_earth_service_account: str
    google_earth_key: Path
    google_earth_project_id: str

    # MODIS land cover collection
    modis_collection_id: str
    modis_collection_band_name: str
    modis_collection_resolution: int
    forest_only: bool = True
    modis_forest_codes: str
    modis_forest_colors: str
    modis_forest_labels: str
    modis_agriculture_codes: str | None
    modis_settlement_codes: str | None

    # Hansen Global Forest Change ("forest change") collection
    forest_change_collection_id: str = "UMD/hansen/global_forest_change_2025_v1_13"
    forest_change_binary_band_name: str = "loss"
    forest_change_loss_year_band_name: str = "lossyear"
    forest_change_collection_resolution: int = 30

    # ESA CCI Above Ground Biomass collection
    biomass_collection_id: str = "ESA/CCI/Above_Ground_Biomass/V6_0"
    biomass_collection_band_name: str = "agb"
    biomass_collection_resolution: int = 100
    biomass_collection_unit: str = "Mg/ha"

    gfw_api_key: str
    gfw_access_token: str
    gfw_dataset: str = "gadm__tcl__iso_change"
    gfw_dataset_version: str = "v20260407"
    gfw_api_url: HttpUrl = HttpUrl("https://www.globalforestwatch.org/api/data/dataset")
    gadm_path: Path = Path("data/global_adm_borders.geojson")
    distance_export_wait_cache_path: Path = Path("data/distance_export_wait_estimates.csv")
    annual_risk_csv_path: Path = Path("data/annual_risk_by_admin1.csv")

    model_config = SettingsConfigDict(env_file=".env", extra="allow")
