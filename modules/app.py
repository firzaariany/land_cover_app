from shiny import App, ui, reactive
from shinywidgets import output_widget, register_widget
import xarray as xr
import rioxarray as rxr
import geopandas as gpd
import json
from ipyleaflet import (
    Map,
    TileLayer,
    LayersControl,
    GeoJSON,
)

# -----------------
# DATA PREPARATION
# -----------------

# Get max and min years from raster
xr_ds = xr.open_dataset("data/CRI/CRI_master_land_cover.nc")
min_year = xr_ds.time.min().values.flatten()[0]
max_year = xr_ds.time.max().values.flatten()[0]

# Define JSON files for mapping country borders and calculating bounds
with open("data/global_adm_borders.geojson", "r") as f:
    data = json.load(f)
    data_gdf = gpd.read_file("data/global_adm_borders.geojson").set_index(["GID_0"])

select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]

# -----------------
# PAGE BUILDER
# -----------------

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select(
            "country",
            "Select a country",
            {
                "MYS": "Malaysia",
                "CRI": "Costa Rica",
                "NOR": "Norway",
                "NZL": "New Zealand",
                "IDN": "Indonesia",
            },
            selected="MYS",
        ),
        ui.input_slider(
            "year", "Select a year", min=min_year, max=max_year, value=2015, sep=""
        ),
        ui.input_dark_mode(mode="dark"),
    ),
    ui.card(output_widget("map")),
    title="Explore Land Cover Data",
    fillable=True,
)

# -----------------
# CONTENT
# -----------------

def server(input, output, session):
    # Render the map once and perform partial updates via reactive effects
    m = Map()
    m.add_control(LayersControl())
    register_widget("map", m)

    # Initialise colormap for raster
    colormap = {"2": [34, 139, 34]}  # Only for forest
    colormap_str = json.dumps(colormap)

    # Create empty GeoJSON border layer
    border_layer = GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        style={"color": "black", "fillColor": "transparent", "weight": 2},
        # hover_style={"fillColor": "salmon", "fillOpacity": 0.3},
        name="Country Border",
    )
    m.add_layer(border_layer)

    # Raster, served via Titiler
    @reactive.effect
    def tile():
        year = input.year()
        for reg in select_country:
            # Add tiles
            cog_file = f"/Users/user/Documents/code/shiny_land_app/data/COG/{reg}/{reg}_Forest_{year}.tiff"
            tile = TileLayer(
                url=(
                    f"http://127.0.0.1:8001/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png"
                    f"?url=file://{cog_file}&colormap={colormap_str}&nodata=-9999"
                ),
                name="Forest",
                opacity=0.5,
            )
            m.add_layer(tile)

    # Show country border upon country selection
    @reactive.effect
    def _():
        sel_iso = input.country()
        print("Selected country", sel_iso)

        # Recenter the map view
        gdf_iso = data_gdf.loc[[sel_iso]]
        min_lon, min_lat, max_lon, max_lat = gdf_iso.total_bounds
        center_p = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
        m.center = center_p

        # Create a single-country GeoJSON dataframe
        select_feature = next(
            feature
            for feature in data["features"]
            if feature["properties"]["GID_0"] == sel_iso
        )
        border_layer.data = {
            "type": "FeatureCollection",
            "features": [select_feature],
        }

        # Adjust zoom level
        sel_bounds = get_raster_bounds(
            f"/Users/user/Documents/code/shiny_land_app/data/COG/{sel_iso}/{sel_iso}_Forest_2015.tiff"
        )
        m.fit_bounds([[sel_bounds[1], sel_bounds[0]], [sel_bounds[3], sel_bounds[2]]])

# -----------------
# SUPPORTING FUNCTIONS
# -----------------

# Instead of setting the zoom, fit the view into the raster bounds
def get_raster_bounds(nc_path):
    ds = xr.open_dataset(nc_path).sel(band=1)
    ds = ds.rio.write_crs("EPSG:4326") if not ds.rio.crs else ds
    bounds = ds.rio.bounds()
    return bounds


app = App(app_ui, server)
