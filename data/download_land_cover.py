import cdsapi
import os
from pathlib import Path
from collections import defaultdict
import geopandas as gpd
import rioxarray as rxr
import xarray as xr
import pandas as pd

dataset = "satellite-land-cover"

def ensure_valid_year(sel_year=1992):
    # Ensure the data type of the input
    if isinstance(sel_year, (int, str)):
        years = [int(sel_year)]

    elif isinstance(sel_year, list):
        years = [int(y) for y in sel_year]

    elif not isinstance(sel_year, str):
        raise ValueError(
            "Invalid input. Provide a year as int, str, or a list of those."
        )

    # Check range and assign version
    year_version_map = {}

    for y in years:
        if 1992 <= y <= 2015:
            year_version_map[y] = "v2_0_7cds"

        elif 2016 <= y <= 2022:
            year_version_map[y] = "v2_1_1"

        else:
            raise ValueError(
                f"Year {y} is not supported. Provide a year between 1992 and 2022."
            )

    return year_version_map


def download_by_year(sel_year, give_target):
    # Ensuring if years are valid
    year_ver_map = ensure_valid_year(sel_year)

    # Group years by version
    version_years = defaultdict(list)
    for year, version in year_ver_map.items():
        version_years[version].append(str(year))

    for version, years in version_years.items():
        # Opening a request
        client = cdsapi.Client()

        request = {
            "variable": "all",
            "year": years,  # Set year
            "version": version,  # Set version
        }

        print(f"Requesting version: {version}, years: {years}")

        client.retrieve(dataset, request).download(give_target)
        

def download_by_year_subset(sel_year, give_out_dir, set_extent):
    # Ensuring if years are valid
    year_ver_map = ensure_valid_year(sel_year)

    # Group years by version
    version_years = defaultdict(list)
    for year, version in year_ver_map.items():
        version_years[version].append(str(year))

    for version, years in version_years.items():
        # Opening a request
        client = cdsapi.Client()

        request = {
            "variable": "all",
            "year": years,
            "version": version,
            "area": set_extent,
        }

        print(f"Requesting version: {version}, years: {years}")

        file_name = os.path.join(give_out_dir, f"LCCS_{version}_{'_'.join(years)}.zip")

        if not os.path.isfile(file_name):
            client.retrieve(dataset, request).download(file_name)
        else:
            print(f"{file_name} already exists, skipping download")


# Example to download data for a specific subregion borders

# Country borders
global_borders = gpd.read_file("data/global_adm_borders.shp").set_index(["GID_0"])

# Selected countries
select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]

# Dynamically setting the periods to download land cover data
timestep = 5
final = 2022

for iso in select_country:
    print(iso)

    if iso in global_borders.index:
        # Get extent
        sel_iso = global_borders.loc[[iso]]
        west, south, east, north = sel_iso.total_bounds
        default_extent = [north, west, south, east] 

        # Pick a directory to store the downloaded data
        out_dir = os.path.join(os.getcwd(), "data", iso)
        os.makedirs(out_dir, exist_ok=True)
        
        start = 2005
        while start < final:
            end = min(start + timestep, final)
            year_set = [i for i in range(start, end)]

            download_by_year_subset(year_set, out_dir, default_extent)

            start += timestep
    
    else:
        print(f"Warning: ISO code '{iso}' not found in the shapefile containing global country borders.")