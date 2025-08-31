import xarray as xr
import rioxarray
import rasterio
from pathlib import Path

# Set up a pipeline to create a COG for one landcover type (Forest), for one year, and for one country
select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]

for iso in select_country:
    print(f"[START] Exporting COG for {iso}...")
    
    out_dir = Path(f"data/COG/{iso}")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Import master reclassified land cover data
    landcover_reclass = xr.open_dataset(f"data/{iso}/{iso}_reclassified_forest.nc")

    # Create 2D array: one year and one variable
    year_list = landcover_reclass.time.values

    # Export with 5-year timesteps instead of 1-year
    # If I want to plot timeseries, I can load the master land cover data anyway
    for i in range(0, len(year_list), 5):
        
        # Check if COG file already exists
        out_path = Path(f"data/COG/{iso}/{iso}_Forest_{year_list[i]}.tiff")
        
        if out_path.exists():
            print(f"COG file already exists for {iso}_Forest_{year_list[i]}. Skipping...")
            continue

        landcover_2d = landcover_reclass.sel(time=year_list[i])["Forest"]
        
        # Remove conflicting attributes
        if "_FillValue" in landcover_2d.attrs:
            del landcover_2d.attrs["_FillValue"]
        
        # Set -9999 as nodata
        landcover_2d = landcover_2d.rio.write_nodata(-9999)

        # Export as COG
        out_path = f"{out_dir}/{iso}_Forest_{year_list[i]}.tiff"

        landcover_2d.rio.to_raster(
            out_path, driver="COG", compress="deflate", dtype="float32",
        )
    print(f"[END] Finished exporting a COG file for Forest")