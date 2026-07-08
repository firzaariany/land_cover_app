import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    BIOMASS_BAND_NAME,
    FOREST_BAND_NAME,
    FOREST_COLLECTION,
    assign_biomass_risk_score,
    assign_forest_type_risk_score,
    load_image,
    reproject_to_reference,
)
from landcover_explorer.knowledgebase.gfw_preprocess import fetch_forest_loss_by_driver
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage
from landcover_explorer.shiny.app_helpers import (
    error_fig,
    forest_cover_legend_choice,
    get_ee_geometry,
    get_iso_feature,
    style_bar_fig,
)

import asyncio
import geopandas as gpd
import json
import math
import plotly.express as px
from ipyleaflet import (
    Map,
    TileLayer,
    LayersControl,
    GeoJSON,
    Popup,
)
from ipywidgets import HTML
from pathlib import Path
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
        ui.input_checkbox_group(
            "visible_layers",
            None,
            choices=forest_cover_legend_choice(2005),
            selected=["forest"],
        ),
    ),
    ui.card(
        output_widget("map"),
        height="500px",
        fillable=True,
    ),
    ui.card(
        output_widget("forest_area_plot"),
        title="Forest loss by driver",
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

    _forest_layer_cache: dict = {}

    border_layer = GeoJSON(
        data={"type": "FeatureCollection", "features": []},
        style={"color": "black", "fillColor": "transparent", "weight": 2},
        name="Country Border",
    )
    m.add_layer(border_layer)

    # Hover popup showing forest coverage
    popup_content = HTML("")
    popup = Popup(
        child=popup_content,
        close_button=True,
        auto_close=True,
        name="Clickable Infobox",
    )
    _popup_cache = {"label": ""}

    def on_click(*_, **__):  
        popup_content.value = _popup_cache["label"]
        popup.location = m.center
        if popup in m.layers:
            m.remove_layer(popup)
        m.add_layer(popup)

    border_layer.on_click(on_click)

    @reactive.calc
    def selected_iso():
        return input.country()

    @reactive.calc
    def selected_year():
        return input.year()

    @reactive.effect
    def refresh_forest_legend_label():
        ui.update_checkbox_group(
            "visible_layers",
            choices=forest_cover_legend_choice(selected_year()),
            selected=input.visible_layers(),
        )

    def apply_forest_layer_visibility():
        try:
            visible = set(input.visible_layers())
        except Exception:
            return
        for layer in m.layers:
            if getattr(layer, "name", "").startswith("Forest_"):
                layer.opacity = 0.7 if "forest" in visible else 0

    @reactive.effect
    def update_forest_layer_visibility():
        apply_forest_layer_visibility()

    @reactive.effect
    async def load_forest_cover_layer():
        iso = selected_iso()
        year = selected_year()

        country_name = COUNTRY_NAMES.get(iso, iso)
        notif_id = ui.notification_show(
            f"Loading map layers for {country_name} ({year})…",
            duration=None,
            type="message",
        )
        await asyncio.sleep(0)  # flush notification to browser before blocking

        cache_key = (iso, year)
        if cache_key not in _forest_layer_cache:
            ee_geometry = get_ee_geometry(data, iso)

            def get_forest_cover_layer_data():
                forest_result = None
                forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, year, ee_geometry)
                if forest_dataset is not None:
                    forest_cover = assign_forest_type_risk_score(forest_dataset)
                    forest_map_id = forest_cover.getMapId({"min": 3, "max": 3, "palette": "#05450a"})
                    coverage = calculate_coverage(
                        iso=iso,
                        year=year,
                        country_geometry=ee_geometry,
                        forest_cover=forest_cover,
                    )
                    forest_result = {
                        "tile_url": forest_map_id["tile_fetcher"].url_format,
                        "coverage": coverage,
                    }

                biomass_result = None
                biomass_image = load_image(
                    settings.biomass_collection_id, BIOMASS_BAND_NAME, year, ee_geometry
                )
                if biomass_image is not None:
                    reference = forest_dataset if forest_dataset is not None else biomass_image
                    biomass_reprojected = reproject_to_reference(biomass_image, reference)
                    biomass_risk = assign_biomass_risk_score(biomass_reprojected)
                    biomass_map_id = biomass_risk.getMapId({
                        "min": 0,
                        "max": 3,
                        "palette": ["#ffffb2", "#fecc5c", "#fd8d3c", "#e31a1c"],
                    })
                    biomass_result = {"tile_url": biomass_map_id["tile_fetcher"].url_format}

                return {
                    "forest_tile_url": forest_result["tile_url"] if forest_result else None,
                    "coverage": forest_result["coverage"] if forest_result else None,
                    "biomass_tile_url": biomass_result["tile_url"] if biomass_result else None,
                }

            _forest_layer_cache[cache_key] = await asyncio.to_thread(get_forest_cover_layer_data)

        layer_data = _forest_layer_cache[cache_key]

        for layer in list(m.layers):
            if layer.name.startswith(("Forest_", "Biomass_")):
                m.remove_layer(layer)
        if layer_data["forest_tile_url"]:
            m.add_layer(TileLayer(
                url=layer_data["forest_tile_url"], name=f"Forest_{iso}_{year}", opacity=0.7
            ))
        if layer_data["biomass_tile_url"]:
            m.add_layer(TileLayer(
                url=layer_data["biomass_tile_url"], name=f"Biomass_{iso}_{year}", opacity=0.7
            ))
        apply_forest_layer_visibility()

        coverage_text = (
            f"Forest cover {year}: {layer_data['coverage']['coverage_pct']}%"
            if layer_data["coverage"]
            else f"No forest cover data for {year}"
        )
        _popup_cache["label"] = (
            f"<b>{COUNTRY_NAMES.get(iso, iso)}</b><br>"
            f"{coverage_text}"
        )

        ui.notification_remove(notif_id)

    # Update border and recenter when country changes
    @reactive.effect
    def update_border_and_recenter():
        sel_iso = selected_iso()

        gdf_iso = data_gdf.loc[[sel_iso]]
        min_lon, min_lat, max_lon, max_lat = gdf_iso.total_bounds

        select_feature = get_iso_feature(data, sel_iso)
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
        return fetch_forest_loss_by_driver(selected_iso())

    @output
    @render_widget
    def forest_area_plot():
        sel_iso = selected_iso()

        try:
            df = gfw_forest_loss()

            if df.empty:
                return error_fig("No data available.")

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
            return style_bar_fig(fig)

        except Exception as e:
            return error_fig(f"Error fetching data: {e}")


app = App(app_ui, server)
