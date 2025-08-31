from shiny import App, ui, reactive
from shinywidgets import output_widget, register_widget, render_widget
import xarray as xr
import rioxarray as rxr
import geopandas as gpd
import json
import pandas as pd
import plotly.express as px
from ipyleaflet import (
    Map,
    TileLayer,
    LayersControl,
    GeoJSON,
)
import time
from pathlib import Path

# -----------------
# DATA PREPARATION
# -----------------


# # Get the data
# def get_year_range():
#     try:
#         xr_ds = xr.open_dataset("data/MYS/MYS_master_land_cover.nc")
#         min_year = xr_ds.time.min().values.flatten()[0]
#         max_year = xr_ds.time.max().values.flatten()[0]
#         return min_year, max_year
#     except FileNotFoundError:
#         # Fallbaxk values if file does not exist
#         return 2005, 2020


# Define JSON files for mapping country borders and calculating bounds
with open("/app/data/global_adm_borders.geojson", "r") as f:
    data = json.load(f)
    data_gdf = gpd.read_file("/app/data/global_adm_borders.geojson").set_index(["GID_0"])

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
            "year",
            "Select a year",
            min=2005,
            max=2020,
            value=2005,
            sep="",
        ),
        ui.input_dark_mode(mode="dark"),
    ),
    
    # Stacked layout: Map on top, time series on bottom
        
    # Map takes 2/3 of the space
    ui.card(
        output_widget("map"),
        height="500px",
        fillable=True,
    ),
    
    # Time series
    ui.card(
        output_widget("forest_area_plot"),
        title="Forest area trends",
        height="400px",
        fillable=True,
    ),
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
    def _():
        year = input.year()

        for layer in m.layers:
            if layer.name.endswith(f"{year}"):
                print(f"Removing layer: {layer.name}")
                m.remove_layer(layer)

        for reg in select_country:
            # Add tiles
            # cog_file = f"/Users/user/Documents/code/shiny_land_app/data/COG/{reg}/{reg}_Forest_{year}.tiff"
            # Access COG file from mounted volume
            cog_file = f"/app/data/COG/{reg}/{reg}_Forest_{year}.tiff"
            tile = TileLayer(
                # url=(
                #     f"http://titiler:8001/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png" 
                #     f"?url=file://{cog_file}&colormap={colormap_str}&nodata=-9999"
                # ),
                url=(
                    f"http://localhost:8001/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png" 
                    f"?url=file://{cog_file}&colormap={colormap_str}&nodata=-9999"
                ),
                name=f"Forest_{reg}_{year}",
                opacity=0.5,
            )
            print(f"Adding tile layer: {tile.name}")

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
            f"/app/data/COG/{sel_iso}/{sel_iso}_Forest_2015.tiff"
        )
        m.fit_bounds([[sel_bounds[1], sel_bounds[0]], [sel_bounds[3], sel_bounds[2]]])
    
    # Forest area plot
    @output
    @render_widget
    def forest_area_plot():
        # Get selected country
        sel_country = input.country()
        
        try:
            # Load CSV data
            csv_file = f"/app/data/CSV/forest_area_changes.csv"
            if Path(csv_file).exists():
                df = pd.read_csv(csv_file)
                
                # Filter data for selected country
                country_data = df[df["Country"] == sel_country].copy()
                
                if not country_data.empty:
                    # Create bar plot
                    fig = px.bar(
                        country_data,
                        x="Year",
                        y="Forest Area",
                        title=f"Forest Area Changes in {sel_country} (2005-2021)",
                        color_discrete_sequence=['#228B22'],
                        opacity=0.8,
                    )
                    
                    # Update layout
                    fig.update_layout(
                        xaxis_title="Year",
                        yaxis_title="Forest Area<br>(million hectares)",
                        # template="plotly_dark" if input.dark_mode() else "plotly",
                        autosize=True,
                        width=None,
                        height=200,
                        margin=dict(l=40, r=40, t=60, b=40),
                        showlegend=False,
                        bargap=0.1,
                        bargroupgap=0.1,
                    )
                    
                    # Update axes
                    fig.update_xaxes(
                        tickmode="array",
                        tickvals=country_data["Year"].tolist()[::2],
                        ticktext=[str(y) for y in country_data['Year'].tolist()[::2]]
                    )
                    
                    # fig.update_yaxes(
                    #     tickformat=".3f"
                    # )
                    
                    return fig
                else:
                    # No data for selected country
                    fig = px.bar(
                        x=[], y=[], title=f"No data available for {sel_country}"
                    )
                    
                    fig.update_layout(
                        # template="plotly_dark" if input.dark_mode() else "plotly_white",
                        height=200,
                    )
                    
                    return fig
                
            else:
                # CSV file not found
                fig = px.bar(
                    x=[], y=[], 
                    title="Forest area data not found. Run the timeseries_area_change.py script to generate the data."
                )
                
                fig.update_layout(
                    # template="plotly_dark" if input.dark_mode() else "plotly_white",
                    height=200,
                )
                
                return fig
        except Exception as e:
            print(f"Error generating forest area plot: {e}")
            
            # Error fallback
            fig = px.bar(
                x=[], y=[], 
                title=f"Error generating plot: {str(e)}"
            )
            fig.update_layout(
                # template="plotly_dark" if input.dark_mode() else "plotly_white",
                height=200,
            )
            
            return fig
            
            
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
