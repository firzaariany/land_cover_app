from pathlib import Path

# import tempfile
import time
import zipfile
import rioxarray as rxr
import xarray as xr
import geopandas as gpd
import dask
import pandas as pd
import numpy as np


# Fuction to check if a file is a raster file
def is_raster_file(path):
    return path.suffix.lower() in [".tif", ".tiff", ".nc", ".gpkg", "geojson", "shp"]


# First extracting data
def extract_land_cover(iso):
    input_path = Path(f"data/{iso}")

    for f in input_path.iterdir():
        if f.suffix == ".zip":

            with zipfile.ZipFile(f, "r") as zip_ref:
                # Check if any file in the zip already exists in the output directory
                already_exists = all(
                    (input_path / name).exists() for name in zip_ref.namelist()
                )
                if already_exists:
                    print(
                        f"[SKIP] All files from {f.name} already exist. Skipping extraction."
                    )
                    continue

                print(f"[START] Extracting {iso}... Filename: {f.name}")

                try:
                    zip_ref.extractall(input_path)

                except Exception as e:
                    print(f"[ERROR] Failed to process {iso}: {e}. Filename: {f}")
                    continue


# Second, importing individual .nc files, clean up the years, concat into one master .nc file
# Then delete individual .nc files
def concat_land_cover(iso):
    input_path = Path(f"data/{iso}")
    raster_to_concat = []
    nc_files = []
    start = time.time()
    output_file = input_path / f"{iso}_master_land_cover.nc"
    
    for item in input_path.iterdir():
        if item.is_file() and item.suffix.lower() == ".nc":
            nc_files.append(item)
        elif item.is_dir():
            for inner_item in item.rglob("*"):
                if inner_item.is_file() and inner_item.suffix.lower() == ".nc":
                    nc_files.append(inner_item)

    if output_file.exists():
        raster_all_years = xr.open_dataset(output_file, mask_and_scale=True, chunks={})
        print(f"{output_file} exists. Skipping the concatenation process..")

    else:
        for item in input_path.iterdir():

            # If the extracted file is a file
            if item.is_file() and is_raster_file(item):
                check_raster = item

            # If the extracted file is a directory
            elif item.is_dir():
                # Look inside the dir
                for inner_item in item.rglob("*"):
                    if inner_item.is_file() and is_raster_file(inner_item):
                        check_raster = inner_item

            ext = check_raster.suffix.lower()

            if ext == ".tif":
                raster = rxr.open_rasterio(check_raster, masked=True, chunks={})
            elif ext == ".nc":
                raster = xr.open_dataset(check_raster, mask_and_scale=True, chunks={})[
                    "lccs_class"
                ]
            elif ext in [".shp", ".geojson", ".gpkg"]:
                raster = gpd.read_file(check_raster)
            else:
                raise ValueError(f"Unsupported file format: {ext}")

        # Here you extract year from datetime - only for tif and nc
        raster["time"] = pd.to_datetime(raster.time).year
        raster_to_concat.append(raster)

    raster_all_years = xr.concat(raster_to_concat, dim="time").sortby("time")
    raster_all_years = raster_all_years.rio.write_crs("EPSG:4326")

    # Add country and CRS identifier
    raster_all_years.attrs["country"] = iso
    raster_all_years.attrs["CRS EPSG"] = raster_all_years.rio.crs.to_epsg()

    # Export the integrated .nc file before deleting originals
    raster_all_years.to_netcdf(output_file, format="NETCDF4", engine="netcdf4")

    # Delete individual .nc files
    for nc_file in nc_files:
        if nc_file != output_file:
            try:
                nc_file.unlink()
                print(f"Deleted {nc_file}")
            except Exception as e:
                print(f"Failed to delete {nc_file}: {e}")

    print(
        f"""[END] Integrated individual yearly raster into a master raster for {iso} """
        f"""in {time.time() - start:.2f} seconds. Years extracted {raster_all_years.time.values}"""
    )

    return raster_all_years


select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]
for reg in ["IDN"]: # select_country:

    extract_land_cover(iso=reg)

    print(f"Creating an integrated array for {reg}...")
    concat_land_cover(iso=reg)
