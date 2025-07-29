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
            selected="MYS"
        ),
        ui.input_slider(
            "year",
            "Select a year",
            min=min_year, max=max_year, value=2015,
            sep=""
        ),
        ui.input_dark_mode(mode="dark")
    ),
    ui.card(
        output_widget("map")
    ),
    title="Explore Land Cover Data",
    fillable=True,
)

# -----------------
# CONTENT
# -----------------
def server(input, output, session):
    # Render the map once and perform partial updates via reactive effects
    m = Map(zoom=5)
    m.add_control(LayersControl())
    register_widget("map", m)
    
    # Create empty GeoJSON border layer
    border_layer = GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        style={"color": "black", "fillColor": "transparent", "weight": 2},
        hover_style={"fillColor": "salmon", "fillOpacity": 0.3},
        name="Country Border"
    )
    m.add_layer(border_layer)
    
    # Add tiles here
    
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
        


# ### THIS WORKS ###
# def server(input, output, session):

#     # Initialise basemap
#     m = Map(zoom=4)
#     m.add_control(LayersControl())
#     register_widget("map", m)
#     # output.m = output_widget("map")

#     # Borders of the selected countries
#     border_layer = GeoJSON(
#         data=sel_iso_features,
#         style={
#             "color" : "black",
#             "fillColor" : "transparent",
#             "weight" : 2
#         },
#         hover_style = {
#             "fillColor" : "salmon",
#             "fillOpacity" : 0.5
#         },
#         name="Country Border"
#     )

#     m.add_layer(border_layer)

#     # Update center whenever user gives input
#     @reactive.effect
#     def _():
#         sel_input = input.country()
#         gdf_iso = data_gdf.loc[[sel_input]]
#         min_lon, min_lat, max_lon, max_lat = gdf_iso.total_bounds
#         center_p = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
#         m.center = center_p

# @output
# @render_widget
# def map():
#     # sel_iso = input.country()
#     # sel_year = input.year()
#     iso_gadm = country_border()

#     min_lon, min_lat, max_lon, max_lat = iso_gadm.total_bounds
#     center_p = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)

#     # Country border
#     geo_json_data = json.loads(iso_gadm.to_json())

#     geo_layer = GeoJSON(
#         data=geo_json_data,
#         style={
#             "color": "black",
#             "fillColor": "transparent",
#             "weight": 2,
#         },
#         hover_style={"fillColor": "salmon", "fillOpacity": 0.3},
#         name="Country Border",
#     )
#     m.add_layer(geo_layer)

# # Get raster bounds
# cog_file = f"/Users/user/Documents/code/shiny_land_app/data/COG/{sel_iso}/{sel_iso}_Agriculture_{sel_year}.tiff"

# # Raster, served via Titiler
# tile = TileLayer(
#     url=f"http://127.0.0.1:8000/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url=file://{cog_file}",
#     name="Agriculture",
#     opacity=0.5,
# )
# m.add_layer(tile)

# return m


# app_ui = ui.page_sidebar(
#     sidebar_ui("sidebar"),
#     main=output_widget("map") # If I place the map in a card, I don't have to call it here again
# )

app = App(app_ui, server)
