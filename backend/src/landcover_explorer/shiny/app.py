import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    compute_agriculture_mask,
    compute_forest_loss_mask,
    compute_modis_forest_mask,
    compute_state_forest_loss_in_settlements,
)
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage

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
    CircleMarker,
    LayerGroup,
)
from ipywidgets import HTML
from pathlib import Path
from shiny import App, ui, reactive, render
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

_layer_cache: dict = {}

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
        ui.hr(),
        ui.p("Map layers", style="font-weight:bold; margin-bottom:4px;"),
        ui.output_ui("map_legend"),
    ),
    ui.card(
        output_widget("map"),
        height="500px",
        fillable=True,
    ),
    ui.layout_columns(
        ui.card(
            output_widget("forest_area_plot"),
            title="Forest loss by driver",
            height="400px",
            fillable=True,
        ),
        ui.card(
            output_widget("driver_class_pie"),
            title="Loss by driver class",
            height="400px",
            fillable=True,
        ),
        col_widths=[8, 4],
        gap="0.5rem",
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

    @output
    @render.ui
    def map_legend():
        year = selected_year()
        def swatch(color):
            return f'<span style="display:inline-block;width:12px;height:12px;background:{color};border-radius:2px;margin-right:6px;"></span>'
        return ui.HTML(f"""
            <div style="display:flex; flex-direction:column; gap:4px; font-size:13px;">
                <span>{swatch("#228B22")}Forest cover {year}</span>
                <span>{swatch("#FFA500")}Agriculture</span>
                <span>{swatch("#9B59B6")}Forest loss in settlements 2001–{year}</span>
                <span>{swatch("#CC0000")}Forest loss 2000–{year}</span>
            </div>
        """)

    @reactive.effect
    async def _():
        iso = selected_iso()
        year = selected_year()

        print(f"Processing data for {iso} in {year}", flush=True)

        country_name = COUNTRY_NAMES.get(iso, iso)
        notif_id = ui.notification_show(
            f"Loading map layers for {country_name} ({year})…",
            duration=None,
            type="message",
        )
        await asyncio.sleep(0)

        cache_key = (iso, year)
        if cache_key not in _layer_cache:
            iso_feature = next(
                f for f in data["features"] if f["properties"]["GID_0"] == iso
            )
            ee_geometry = ee.Geometry(iso_feature["geometry"])

            app_forest, app_agri, (app_settlement_loss, settlement_loss_centroids), app_loss = await asyncio.gather(
                asyncio.to_thread(compute_modis_forest_mask, igbp_land_cover, ee_geometry, year),
                asyncio.to_thread(compute_agriculture_mask, igbp_land_cover, ee_geometry, year),
                asyncio.to_thread(compute_state_forest_loss_in_settlements, igbp_land_cover, ee_geometry, year, country_name),
                asyncio.to_thread(compute_forest_loss_mask, ee_geometry, year),
            )

            def get_forest_tile_url():
                map_id = app_forest.getMapId({"min": 0, "max": 1, "palette": ["#228B22"]})
                return map_id["tile_fetcher"].url_format

            def get_agri_tile_url():
                map_id = app_agri.getMapId({"min": 0, "max": 1, "palette": ["#FFA500"]})
                return map_id["tile_fetcher"].url_format

            def get_loss_tile_url():
                map_id = app_loss.getMapId({"min": 0, "max": 1, "palette": ["#CC0000"]})
                return map_id["tile_fetcher"].url_format

            def get_coverage():
                return calculate_coverage(
                    iso=iso,
                    year=year,
                    country_geometry=ee_geometry,
                    category_mask=app_forest,
                )

            forest_tile_url, agri_tile_url, loss_tile_url, coverage = await asyncio.gather(
                asyncio.to_thread(get_forest_tile_url),
                asyncio.to_thread(get_agri_tile_url),
                asyncio.to_thread(get_loss_tile_url),
                asyncio.to_thread(get_coverage),
            )

            _layer_cache[cache_key] = {
                "forest_tile_url": forest_tile_url,
                "agri_tile_url": agri_tile_url,
                "loss_tile_url": loss_tile_url,
                "coverage": coverage,
                "settlement_loss_centroids": settlement_loss_centroids,
            }

        forest_tile_url = _layer_cache[cache_key]["forest_tile_url"]
        agri_tile_url = _layer_cache[cache_key]["agri_tile_url"]
        loss_tile_url = _layer_cache[cache_key]["loss_tile_url"]
        coverage = _layer_cache[cache_key]["coverage"]
        settlement_loss_centroids = _layer_cache[cache_key]["settlement_loss_centroids"]

        max_settlement_area = max((pt["loss_area_m2"] for pt in settlement_loss_centroids), default=1)
        settlement_markers = LayerGroup(
            layers=[
                CircleMarker(
                    location=[pt["lat"], pt["lon"]],
                    radius=max(3, int(math.sqrt(pt["loss_area_m2"] / max_settlement_area) * 25)),
                    color="#9B59B6",
                    fill_color="#9B59B6",
                    fill_opacity=0.7,
                    weight=1,
                    tooltip=f'{pt["name"]}: {pt["loss_area_m2"] / 1e6:.1f} km²',
                )
                for pt in settlement_loss_centroids
            ],
            name=f"Settlement_{iso}_{year}",
        )

        for layer in list(m.layers):
            if layer.name.startswith(("Forest_", "Agriculture_", "Settlement_", "Loss_")):
                m.remove_layer(layer)
        m.add_layer(TileLayer(url=loss_tile_url, name=f"Loss_{iso}_{year}", opacity=0.7))
        m.add_layer(TileLayer(url=forest_tile_url, name=f"Forest_{iso}_{year}", opacity=0.5))
        m.add_layer(TileLayer(url=agri_tile_url, name=f"Agriculture_{iso}_{year}", opacity=0.5))
        m.add_layer(settlement_markers)

        _popup_cache["label"] = (
            f"<b>{COUNTRY_NAMES.get(iso, iso)}</b><br>"
            f"Forest cover {year}: {coverage['coverage_pct']}%"
        )

        ui.notification_remove(notif_id)

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

        sql = f"""
        SELECT
            wri_google_tree_cover_loss_drivers__driver,
            umd_tree_cover_loss__year,
            SUM(umd_tree_cover_loss__ha) AS umd_tree_cover_loss__ha,
            SUM("gfw_gross_emissions_co2e_all_gases__Mg") AS gfw_gross_emissions_co2e_all_gases__Mg
        FROM data
        WHERE iso = '{sel_iso}'
            AND umd_tree_cover_density_2000__threshold = 30
            AND wri_google_tree_cover_loss_drivers__driver IS NOT NULL
        GROUP BY 
            wri_google_tree_cover_loss_drivers__driver,
            umd_tree_cover_loss__year
        """

        response = requests.get(GFW_QUERY, headers=headers, params={"sql": sql})

        if not response.ok:
            raise RuntimeError(
                f"GFW API error {response.status_code} for {sel_iso}: {response.text[:200]}"
            )

        # Group sub-class of tree loss drivers into larger classes
        df = pd.DataFrame(response.json()["data"])

        driver_class_map = {
            "Hard commodities":             "Deforestation",
            "Permanent agriculture":        "Deforestation",
            "Settlements & Infrastructure": "Deforestation",
            "Logging":                      "Temporary disturbances",
            "Other natural disturbances":   "Temporary disturbances",
            "Wildfire":                     "Temporary disturbances",
            "Shifting cultivation":         "Temporary disturbances",
        }
        df["large_driver_class"] = df["wri_google_tree_cover_loss_drivers__driver"].map(driver_class_map)

        return df

    @output
    @render_widget
    def forest_area_plot():
        sel_iso = selected_iso()

        try:
            df = gfw_forest_loss()

            if df.empty:
                fig = px.bar(x=[], y=[], title="No data available.")
                fig.update_layout(height=300)
                return fig

            df["Year"] = df["umd_tree_cover_loss__year"]
            df["Forest Loss (kha)"] = (df["umd_tree_cover_loss__ha"] / 1000).round(2)
            df["Driver"] = df["wri_google_tree_cover_loss_drivers__driver"]

            fig = px.bar(
                df,
                x="Year",
                y="Forest Loss (kha)",
                color="Driver",
                barmode="stack",
                opacity=0.8,
                title=f"Forest Loss in {COUNTRY_NAMES.get(sel_iso, sel_iso)}",
                template="plotly_dark",
                height=300,
            )
            fig.update_layout(
                autosize=True,
                margin=dict(l=40, r=160, t=60, b=60),
                legend=dict(
                    orientation="v",
                    x=1.02,
                    y=1,
                    xanchor="left",
                    yanchor="top",
                    font=dict(size=10),
                    bgcolor="rgba(0,0,0,0)",
                    title=dict(text="Driver", font=dict(size=11)),
                ),
            )
            fig.update_xaxes(showticklabels=True, tickfont=dict(size=10))
            return fig

        except Exception as e:
            fig = px.bar(x=[], y=[], title=f"Error fetching data: {e}")
            fig.update_layout(height=300)
            return fig

    @output
    @render_widget
    def driver_class_pie():
        sel_iso = selected_iso()

        try:
            df = gfw_forest_loss()

            if df.empty:
                fig = px.pie(title="No data available.")
                fig.update_layout(height=300)
                return fig

            df_class = (
                df.groupby("large_driver_class", as_index=False)["umd_tree_cover_loss__ha"]
                .sum()
                .rename(columns={
                    "large_driver_class":      "Driver class",
                    "umd_tree_cover_loss__ha": "Tree cover loss (kha)",
                })
            )
            df_class["Tree cover loss (kha)"] = (df_class["Tree cover loss (kha)"] / 1000).round(2)

            fig = px.pie(
                df_class,
                names="Driver class",
                values="Tree cover loss (kha)",
                color="Driver class",
                color_discrete_map={
                    "Deforestation": "#8B0000",
                    "Temporary disturbances": "#DAA520",
                },
                title=f"Driver class share<br>{COUNTRY_NAMES.get(sel_iso, sel_iso)}",
                template="plotly_dark",
                hole=0.4,
            )
            fig.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=60, b=80),
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.15,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                    itemsizing="constant",
                ),
                showlegend=True,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            return fig

        except Exception as e:
            fig = px.pie(title=f"Error: {e}")
            fig.update_layout(height=300)
            return fig


app = App(app_ui, server)
