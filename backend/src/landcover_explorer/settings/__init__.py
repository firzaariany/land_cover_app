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
    collection_id: str = "MODIS/061/MCD12C1"
    collection_band_name: str = "Majority_Land_Cover_Type_1"
    forest_only: bool = True
    forest_codes_in_collection: str = "1,2,3,4,5"
    gfw_api_key: str
    gfw_access_token: str
    gfw_dataset: str = "gadm__tcl__iso_change"
    gfw_dataset_version: str = "v20260407"
    gfw_api_url: HttpUrl = HttpUrl("https://www.globalforestwatch.org/api/data/dataset")
    gadm_path: Path = Path("data/global_adm_borders.geojson")

    model_config = SettingsConfigDict(env_file=".env", extra="allow")
