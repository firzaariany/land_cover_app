# Land Cover Visualization App
An interactive Shiny app to visualize land cover rasters over selected countries using Titiler for on-the-fly Cloud-Optimized GeoTiff (COG) tile serving. 

## Features
- Interactive map displaying land cover rasters over multiple countries.
- Dynamic raster layer updates based on user-selectd year.
- Raster tiles served via a locally running Titiler server
- Country borders displayed as vector overlays

## Getting started
### Prerequisites
- Python 3.8+
- [Shiny for Python](https://shiny.posit.co/py/get-started/)
- [Ipyleaflet](https://ipyleaflet.readthedocs.io/en/latest/installation/index.html), embedded in Shiny
- [Titiler](https://developmentseed.org/titiler/) installed and running locally 
- Cloud-Optimized GeoTiff (COG) raster files stored locally

### Installation
1. Clone this repository
```
git clone https://github.com/firzaariany/land_cover_app.git
cd land_cover_app
```

2. Install dependencies
```
conda env create -f environment.yml
```

3. Create Cloud-Optimized GeoTiff (COG) for selected countries
- Initialised directory creations for COG by running the script in `data/__init__.py`
- Download global administration border from [GADM](https://gadm.org/) by running the script in `data/download_gadm.py`
- Selected countries are `["MYS", "CRI", "NZL", "NOR", "IDN"]`. This will create a shapefile titled `data/global_adm_borders.shp` and other vector-like formats, as well as create a geojson file titled `data/global_adm_borders.geojson`.
- Download land cover rasters for selected countries from [Copernicus Climate Data Store](https://cds.climate.copernicus.eu/datasets/satellite-land-cover?tab=overview) by running the script in `data/download_land_cover.py`. This will create directories for each selected countries, in which lays the zip files for land cover rasters from 2005 - 2020.
- Unzip the land cover rasters, and consolidate the individual layers for 2005 - 2020 as one xarray dataset by running the script in `data/master_land_cover.py`. This will create .nc file titled `data/{country}/{country}_master_land_cover.nc` for each selected country. Each .nc file consists of five land cover variables and latitude, longitude, and time dimensions. 
- Re-classify the redundant land cover classification into more general classification and create COG for each land cover variable, time selection, and each country. The script is now only creating COG for forest and agriculture for the year 2005, 2010, 2015, 2020. Doing this by running the script in `data/reclassify_land_cover_COG.py`. This will return COG files in the directory `data/COG/{country}/{country}_{land_variable}_{year}.tiff`

4. Start the Titiler server locally to serve COG rasters
```
uvicorn main:app --reload --port 8001
```

5. Run the Shiny app
```
shiny run --reload modules/app.py
```

### Usage 
- Select the year from the UI input to update the forest raster layers.
- The map will overlay raster tiles from the local Titiler server for all selected countries.
- Select the country to re-center the view and become the focus of the raster view.

## Project structure
- `modules/app.py` - Main Shiny app server and UI code
- `data` - Directory with all scripts to download, processed, and export COGs for selected countries, as well as to download the vector data for country borders
- `main.py` - Titiler server backend to serve raster tiles
- `environment.yml` - Python dependencies

## Notes
- Ensure the Titiler server is running before launching the Shiny app.
- Raster files must be accessible by the Titiler server with correct file paths (will be ensured if you run `__init__.py`, `data/download_land_cover.py`, `data/master_land_cover.py`, then `data/reclassify_land_cover_COG.py` in correct order).
- This app is designed for local use and development; adapt paths and hosting for production.

## Contact
Firza Riany (GIS Data Scientis)
firzariany2@gmail.com