import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import compute_forest_mask

import asyncio
import geopandas as gpd
import json
import math
import os
import pandas as pd
import plotly.express as px
import requests
from ipyleaflet import (
    Map,
    TileLayer,
    LayersControl,
    GeoJSON,
    Popup,
)
from ipywidgets import HTML
from pathlib import Path
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage
from shiny import App, ui, reactive
from shinywidgets import output_widget, register_widget, render_widget

# -----------------
# GEE INITIALISATION
# -----------------
settings = Settings()

credentials = ee.ServiceAccountCredentials(
    settings.google_earth_service_account, str(settings.google_earth_key)
)
ee.Initialize(credentials)

# MODIS land cover
dataset = ee.ImageCollection(settings.collection_id)
igbp_land_cover = dataset.select(settings.collection_band_name)

GFW_DATASET = settings.gfw_dataset
GFW_VERSION = settings.gfw_dataset_version
GFW_URL = str(settings.gfw_api_url)
GFW_QUERY = f"{GFW_URL}/{GFW_DATASET}/{GFW_VERSION}/query"

# IGBP_VIS = {
#     "min": 0,
#     "max": 16,
#     "palette": [
#         "1c0dff", "05450a", "086a10", "54a708", "78d203", "009900", "c6b044", "dcd159",
#         "dade48", "fbff13", "b6ff05", "27ff87", "c24f44", "a5a5a5", "ff6d4c",
#         "69fff8", "f9ffa4",
#     ],
# }

# Can list more countries -> To be set up in a separate module
COUNTRY_NAMES = {
    "MYS": "Malaysia",
    "CRI": "Costa Rica",
    "NOR": "Norway",
    "NZL": "New Zealand",
    "IDN": "Indonesia",
}

# -----------------
# DATA PREPARATION
# -----------------

# To be replaced with API call
_GEOJSON_PATH = Path(__file__).parents[3] / settings.gadm_path

with open(_GEOJSON_PATH, "r") as f:
    data = json.load(f)
    data_gdf = gpd.read_file(_GEOJSON_PATH).set_index(["GID_0"])

# -----------------
# PAGE BUILDER
# -----------------

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select(
            "country",
            "Select a country",
            COUNTRY_NAMES,
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
    ui.card(
        output_widget("map"),
        height="500px",
        fillable=True,
    ),
    ui.card(
        output_widget("forest_area_plot"),
        title="Forest area trends",
        height="400px",
        fillable=True,
    ),
    title="Explore Forest",
    fillable=True,
)

# -----------------
# CONTENT
# -----------------


def server(input, output, session):
    m = Map()
    m.add_control(LayersControl())
    register_widget("map", m)

    border_layer = GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        style={"color": "black", "fillColor": "transparent", "weight": 2},
        name="Country Border",
    )
    m.add_layer(border_layer)

    # Hover popup — cache label in a plain dict so the on_click callback
    # (which runs outside Shiny's reactive graph) can read the latest value
    popup_content = HTML("")
    popup = Popup(
        child=popup_content,
        close_button=True,
        auto_close=True,
        name="Clickable Infobox",
    )
    _popup_cache = {"label": ""}

    def on_click(*_, **__):  # noqa: ARG001
        popup_content.value = _popup_cache["label"]
        popup.location = m.center
        if popup in m.layers:
            m.remove_layer(popup)
        m.add_layer(popup)

    border_layer.on_click(on_click)  # register once

    @reactive.calc
    def selected_iso():
        return input.country()

    @reactive.calc
    def selected_year():
        return input.year()

    # Fetch MODIS IGBP tile URL clipped to the selected country and year
    # @reactive.calc
    # def gee_igbp_tile_url():
    #     iso = input.country()
    #     year = input.year()

    #     country_feature = next(
    #         f for f in data["features"]
    #         if f["properties"]["GID_0"] == iso
    #     )
    #     ee_geometry = ee.Geometry(country_feature["geometry"])

    #     image = (
    #         igbp_land_cover
    #         .filter(ee.Filter.calendarRange(year, year, "year"))
    #         .first()
    #         .clip(ee_geometry)
    #     )

    #     map_id = image.getMapId(IGBP_VIS)
    #     return map_id["tile_fetcher"].url_format

    # Update tile layer and popup cache when country or year changes.
    # Stage 1 (sequential): build forest mask — both downstream calls depend on it.
    # Stage 2 (parallel): getMapId and calculate_coverage are independent GEE calls.
    @reactive.effect
    async def _():
        iso = selected_iso()
        year = selected_year()

        print(f"Processing data for {iso} in {year}", flush=True)

        country_name = COUNTRY_NAMES.get(iso, iso)
        notif_id = ui.notification_show(
            f"Loading forest data for {country_name} ({year})…",
            duration=None,
            type="message",
        )
        await asyncio.sleep(0)

        iso_feature = next(
            f for f in data["features"] if f["properties"]["GID_0"] == iso
        )
        ee_geometry = ee.Geometry(iso_feature["geometry"])

        app_forest = await asyncio.to_thread(
            compute_forest_mask, igbp_land_cover, ee_geometry, selected_year()
        )

        def get_tile_url():
            map_id = app_forest.getMapId({"min": 0, "max": 1, "palette": ["#228B22"]})
            return map_id["tile_fetcher"].url_format

        def get_coverage():
            return calculate_coverage(
                iso=iso,
                year=year,
                country_geometry=ee_geometry,
                category_mask=app_forest,
            )

        tile_url, coverage = await asyncio.gather(
            asyncio.to_thread(get_tile_url),
            asyncio.to_thread(get_coverage),
        )

        for layer in list(m.layers):
            if layer.name.startswith("Forest_"):
                m.remove_layer(layer)
        m.add_layer(
            TileLayer(
                url=tile_url,
                name=f"Forest_{iso}_{year}",
                opacity=0.5,
            )
        )

        country_display = COUNTRY_NAMES.get(coverage["iso"], coverage["iso"])
        _popup_cache["label"] = (
            f"<b>{country_display}</b><br>Forest cover {coverage['year']}: {coverage['coverage_pct']}%"
        )

        ui.notification_remove(notif_id)

    # # Update IGBP land cover layer when country or year changes
    # @reactive.effect
    # def _():
    #     iso = input.country()
    #     year = input.year()
    #     url = gee_igbp_tile_url()

    #     for layer in list(m.layers):
    #         if layer.name.startswith("IGBP_"):
    #             m.remove_layer(layer)

    #     m.add_layer(TileLayer(url=url, name=f"IGBP_{iso}_{year}", opacity=0.7))

    # Update border and recenter when country changes
    @reactive.effect
    def _():
        sel_iso = selected_iso()

        gdf_iso = data_gdf.loc[[sel_iso]]
        min_lon, min_lat, max_lon, max_lat = gdf_iso.total_bounds

        select_feature = next(
            f for f in data["features"] if f["properties"]["GID_0"] == sel_iso
        )
        border_layer.data = {
            "type": "FeatureCollection",
            "features": [select_feature],
        }

        if popup in m.layers:
            m.remove_layer(popup)

        # Set center and zoom last so they are not overridden by border_layer update
        span = max(max_lat - min_lat, max_lon - min_lon)
        m.zoom = max(2, min(10, round(math.log2(360 / span))))
        m.center = [float((min_lat + max_lat) / 2), float((min_lon + max_lon) / 2)]

    @reactive.calc
    def gfw_forest_loss():
        sel_iso = selected_iso()

        headers = {
            "Authorization": f"Bearer {settings.gfw_access_token}",
            "x-api-key": settings.gfw_api_key,
        }

        sql_primary = f"""
        SELECT
            umd_tree_cover_loss__year,
            SUM(umd_tree_cover_loss__ha) AS umd_tree_cover_loss__ha
        FROM data
        WHERE iso = '{sel_iso}'
            AND umd_tree_cover_density_2000__threshold = 30
            AND is__umd_regional_primary_forest_2001 = 'true'
        GROUP BY umd_tree_cover_loss__year
        ORDER BY umd_tree_cover_loss__year
        """

        response = requests.get(GFW_QUERY, headers=headers, params={"sql": sql_primary})
        response.raise_for_status()

        if not response.json()["data"]:
            sql_fallback = f"""
        SELECT
            umd_tree_cover_loss__year,
            SUM(umd_tree_cover_loss__ha) AS umd_tree_cover_loss__ha
        FROM data
        WHERE iso = '{sel_iso}'
            AND umd_tree_cover_density_2000__threshold = 30
        GROUP BY umd_tree_cover_loss__year
        ORDER BY umd_tree_cover_loss__year
        """
            response = requests.get(GFW_QUERY, headers=headers, params={"sql": sql_fallback})
            response.raise_for_status()

        return pd.DataFrame(response.json()["data"])

    # Forest loss chart (GFW API)
    @output
    @render_widget
    def forest_area_plot():
        sel_iso = selected_iso()

        try:
            df = gfw_forest_loss()

            if df.empty:
                fig = px.bar(
                    pd.DataFrame({"Year": [], "Loss": []}),
                    x="Year",
                    y="Loss",
                    title="No data available.",
                )
                fig.update_layout(height=300)
                return fig

            df_renamed = df.rename(
                columns={
                    "umd_tree_cover_loss__year": "Year",
                    "umd_tree_cover_loss__ha": "Primary tree cover loss (kha)",
                }
            )
            df_renamed["Primary tree cover loss (kha)"] = df_renamed[
                "Primary tree cover loss (kha)"
            ].apply(lambda x: round(x / 1000, 2))

            fig = px.bar(
                df_renamed,
                x="Year",
                y="Primary tree cover loss (kha)",
                labels={"Primary tree cover loss (kha)": "Tree Cover Loss (kha)"},
                title=f"Primary Forest Loss in {COUNTRY_NAMES.get(sel_iso, sel_iso)}",
                color_discrete_sequence=["#228B22"],
                opacity=0.8,
                template="plotly_dark",
                height=300,
            )
            fig.update_layout(
                autosize=True,
                margin=dict(l=40, r=40, t=60, b=60),
                showlegend=False,
            )
            fig.update_xaxes(showticklabels=True, tickfont=dict(size=10))
            return fig

        except Exception as e:
            fig = px.bar(
                pd.DataFrame({"Year": [], "Loss": []}),
                x="Year",
                y="Loss",
                title=f"Error fetching data: {e}",
            )
            fig.update_layout(height=300)
            return fig


app = App(app_ui, server)
