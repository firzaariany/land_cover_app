import xarray as xr
import rasterio
import numpy as np
import dask
import pandas as pd
import rioxarray
from pathlib import Path
import gc
import psutil

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


def print_memory():
    process = psutil.Process()
    print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.1f} MB")


# Call it before and after processing
print("Checking memory before reclassification: ", print_memory())

# Phase 1: Reclasasification (only if master file of land reclassification does not exist)

for iso in select_country:
    master_reclass = Path(f"data/{iso}/{iso}_reclassified_forest.nc")

    if not master_reclass.exists():
        print(f"[START] Reclassifying forest for {iso}...")
        iso_df = xr.open_dataset(
            f"data/{iso}/{iso}_master_land_cover.nc",
            chunks="auto",
        )["lccs_class"]
        iso_df = iso_df.rio.write_crs("EPSG:4326")

        # Drop duplicated years in the time dimension
        years = pd.Series(iso_df.time.values)
        unique_mask = ~years.duplicated()
        iso_df = iso_df.isel(time=unique_mask.values)

        # # Create one variable for one land cover type -> take up memory
        # reclassify = {}
        # for count, (type, code) in enumerate(landcover_dict.items()):
        #     print(count + 1, type, code)

        #     # Reclassify the codes for each landcover type
        #     binary_mask = xr.where(iso_df.isin(code), count + 1, np.nan).astype(
        #         "float32"
        #     )
        #     binary_mask.name = type  # Set variable name
        #     reclassify[type] = binary_mask

        #     # Clear intermediate results
        #     del binary_mask
        #     gc.collect()

        # Create forest variable
        binary_mask = xr.where(iso_df.isin(landcover_dict["Forest"]), 1, np.nan).astype(
            "float32"
        )
        binary_mask.name = "Forest"
        reclassify = {"Forest": binary_mask}
        
        # Clear intermediate results
        del binary_mask
        gc.collect()

        # A new xarray with time, lon, lat dimensions and one land type
        landcover_reclass = xr.Dataset(reclassify)

        # Add attributes to identify the data
        land_class = []
        for count, type in enumerate(landcover_dict.keys()):
            land_class.append(f"{count+1}: {type}")

        landcover_reclass.attrs["CRS"] = "EPSG:4326"
        landcover_reclass.attrs["Country"] = iso
        landcover_reclass.attrs["Land Classification"] = "Forest"
        # landcover_reclass.attrs["Land Classification"] = ", ".join(land_class) -> for > 1 land cover

        # Export reclassified forest data
        out_netcdf = Path(f"data/{iso}/{iso}_reclassified_forest.nc")
        landcover_reclass.to_netcdf(
            f"{out_netcdf}",
            format="NETCDF4",
            engine="netcdf4",
        )

        print(
            f"[END] Finished exporting reclassified forest data for {iso} to data/{iso}/{iso}"
        )

        # Clear memory after each country
        del landcover_reclass, iso_df
        gc.collect()

    else:
        print(
            f"Master reclassified forest data already exists for {iso}. Skipping reclassification."
        )

print("Checking memory after reclassification: ", print_memory())
