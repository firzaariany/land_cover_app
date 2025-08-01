import xarray as xr
import rasterio
import numpy as np
import dask
import pandas as pd
import rioxarray
from pathlib import Path

# Set up a pipeline to create a COG for one landcover type (Forest), for one year, and for one country
select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]

# Categorising LCCS landcover type into five broad types
landcover_dict = {
    "Agriculture": [10, 11, 12, 20, 30, 40],
    "Forest": [50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90, 100, 160, 170],
    "Grassland": [110, 130],
    "Wetland": [180],
    "Settlement": [190],
    "Other": [
        120,
        121,
        122,
        140,
        150,
        151,
        152,
        153,
        200,
        201,
        202,
        210,
    ],  # Shrubland, sparse veg, bare sea, water
}

for iso in select_country:
    print(f"[START] Reclassifying redundant land categories for {iso}...")
    iso_df = xr.open_dataset(f"data/{iso}/{iso}_master_land_cover.nc", chunks={})[
        "lccs_class"
    ]
    iso_df = iso_df.rio.write_crs("EPSG:4326")

    # Drop duplicated years in the time dimension
    years = pd.Series(iso_df.time.values)
    unique_mask = ~years.duplicated()
    iso_df = iso_df.isel(time=unique_mask.values)

    # Check if all output files exist
    out_dir = Path(f"data/COG/{iso}")
    out_dir.mkdir(parents=True, exist_ok=True)

    all_exist = True
    for lc_type in landcover_dict.keys():
        for y in years:
            out_path = out_dir / f"{iso}_{lc_type}_{y}.tiff"
            if not out_path.exists():
                all_exist = False
                break

        if not all_exist:
            break

    if all_exist:
        print(f"All COG files for {iso} already exist. Skipping reclassification.")
        continue

    # Create one variable for one land cover type
    reclassify = {}
    for count, (type, code) in enumerate(landcover_dict.items()):
        print(count + 1, type, code)

        # Reclassify the codes for each landcover type
        binary_mask = xr.where(iso_df.isin(code), count + 1, np.nan).astype("float32")
        binary_mask.name = type  # Set variable name

        reclassify[type] = binary_mask

    # A new xarray with time, lon, lat dimensions and five variables of land cover types
    landcover_reclass = xr.Dataset(reclassify)

    # Add attributes to identify the data
    land_class = []
    for count, type in enumerate(landcover_dict.keys()):
        land_class.append(f"{count+1}: {type}")

    landcover_reclass.attrs["CRS"] = "EPSG:4326"
    landcover_reclass.attrs["Country"] = iso
    landcover_reclass.attrs["Land Classification"] = ", ".join(land_class)

    print("[START] Exporting COG...")

    # Create 2D array: one year and one variable
    year_list = landcover_reclass.time.values
    for lc_type in ["Agriculture", "Forest"]:
        print(lc_type)

        # Export with 5-year timesteps instead of 1-year
        # If I want to plot timeseries, I can load the master land cover data anyway
        for i in range(0, len(year_list), 5):

            landcover_2d = landcover_reclass.sel(time=year_list[i])[lc_type]
            
            # Set -9999 as nodata
            landcover_2d = landcover_2d.rio.write_nodata(-9999)

            # Export as COG
            out_path = f"{out_dir}/{iso}_{lc_type}_{year_list[i]}.tiff"

            landcover_2d.rio.to_raster(
                out_path, driver="COG", compress="deflate", dtype="float32",
            )
        print(f"[END] Finished exporting a COG file for {lc_type}")
