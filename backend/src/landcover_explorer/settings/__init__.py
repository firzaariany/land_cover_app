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
    collection_id: str
    collection_band_name: str
    collection_resolution: int
    forest_only: bool = True
    forest_codes_in_collection: str
    agriculture_codes_in_collection: str 
    settlements_codes_in_collection: str
    hansen_dataset: str = "UMD/hansen/global_forest_change_2025_v1_13"
    gfw_api_key: str
    gfw_access_token: str
    gfw_dataset: str = "gadm__tcl__iso_change"
    gfw_dataset_version: str = "v20260407"
    gfw_api_url: HttpUrl = HttpUrl("https://www.globalforestwatch.org/api/data/dataset")
    gadm_path: Path = Path("data/global_adm_borders.geojson")

    model_config = SettingsConfigDict(env_file=".env", extra="allow")
