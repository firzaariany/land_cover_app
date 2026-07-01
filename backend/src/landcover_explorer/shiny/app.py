import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    compute_forest_loss_mask,
    compute_modis_forest_mask,
    compute_state_forest_loss_in_agriculture,
    compute_state_forest_loss_in_settlements,
)
from landcover_explorer.knowledgebase.gfw_preprocess import fetch_forest_loss_by_driver
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage
from landcover_explorer.knowledgebase.biomass_stats import (
    compute_agb_loss_time_series,
    compute_cumulative_agb_loss,
)
from landcover_explorer.shiny.app_helpers import (
    build_loss_markers,
    error_fig,
    get_ee_geometry,
    get_iso_feature,
    legend_choices,
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

# MODIS land cover
dataset = ee.ImageCollection(settings.collection_id)
igbp_land_cover = dataset.select(settings.collection_band_name)

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
        ui.input_checkbox_group(
            "visible_layers",
            None,
            choices=legend_choices(2005),
            selected=["forest", "loss"],
        ),
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
            ui.input_select(
                "agb_view",
                None,
                {"yearly": "Yearly", "cumulative": "Cumulative"},
                selected="yearly",
            ),
            output_widget("agb_loss_plot"),
            title="Aboveground biomass loss by driver",
            height="400px",
            fillable=True,
        ),
        col_widths=[6, 6],
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

    def on_click(*_, **__):  
        popup_content.value = _popup_cache["label"]
        popup.location = m.center
        if popup in m.layers:
            m.remove_layer(popup)
        m.add_layer(popup)

    border_layer.on_click(on_click)

    _settlement_group: reactive.Value = reactive.value(None)
    _agriculture_group: reactive.Value = reactive.value(None)
    _agb_loss_series: reactive.Value = reactive.value(None)

    @reactive.calc
    def selected_iso():
        return input.country()

    @reactive.calc
    def selected_year():
        return input.year()

    @reactive.effect
    def refresh_legend_labels():
        ui.update_checkbox_group(
            "visible_layers",
            choices=legend_choices(selected_year()),
            selected=input.visible_layers(),
        )

    @reactive.effect
    async def load_map_layers():
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
            ee_geometry = get_ee_geometry(data, iso)

            app_forest, (_, settlement_loss_centroids), app_loss, (__, agriculture_loss_centroids) = await asyncio.gather(
                asyncio.to_thread(compute_modis_forest_mask, igbp_land_cover, ee_geometry, year),
                asyncio.to_thread(compute_state_forest_loss_in_settlements, igbp_land_cover, ee_geometry, year, country_name),
                asyncio.to_thread(compute_forest_loss_mask, ee_geometry, year),
                asyncio.to_thread(compute_state_forest_loss_in_agriculture, igbp_land_cover, ee_geometry, year, country_name),
            )

            def get_forest_tile_url():
                map_id = app_forest.getMapId({"min": 0, "max": 1, "palette": ["#228B22"]})
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

            forest_tile_url, loss_tile_url, coverage = await asyncio.gather(
                asyncio.to_thread(get_forest_tile_url),
                asyncio.to_thread(get_loss_tile_url),
                asyncio.to_thread(get_coverage),
            )

            _layer_cache[cache_key] = {
                "forest_tile_url": forest_tile_url,
                "loss_tile_url": loss_tile_url,
                "coverage": coverage,
                "settlement_loss_centroids": settlement_loss_centroids,
                "agriculture_loss_centroids": agriculture_loss_centroids,
            }

        forest_tile_url = _layer_cache[cache_key]["forest_tile_url"]
        loss_tile_url = _layer_cache[cache_key]["loss_tile_url"]
        coverage = _layer_cache[cache_key]["coverage"]
        settlement_loss_centroids = _layer_cache[cache_key]["settlement_loss_centroids"]
        agriculture_loss_centroids = _layer_cache[cache_key]["agriculture_loss_centroids"]

        settlement_markers = build_loss_markers(
            settlement_loss_centroids, "#9B59B6", f"Settlement_{iso}_{year}"
        )
        _settlement_group.set(settlement_markers)

        agriculture_loss_markers = build_loss_markers(
            agriculture_loss_centroids, "#E67E22", f"AgriLoss_{iso}_{year}"
        )
        _agriculture_group.set(agriculture_loss_markers)

        for layer in list(m.layers):
            if layer.name.startswith(("Forest_", "AgriLoss_", "Settlement_", "Loss_")):
                m.remove_layer(layer)
        m.add_layer(TileLayer(url=loss_tile_url, name=f"Loss_{iso}_{year}", opacity=0))
        m.add_layer(TileLayer(url=forest_tile_url, name=f"Forest_{iso}_{year}", opacity=0))

        _popup_cache["label"] = (
            f"<b>{COUNTRY_NAMES.get(iso, iso)}</b><br>"
            f"Forest cover {year}: {coverage['coverage_pct']}%"
        )

        ui.notification_remove(notif_id)

    @reactive.effect
    def update_layer_visibility():
        try:
            visible = set(input.visible_layers())
        except Exception:
            return

        opacity_map = {
            "Forest_": ("forest", 0.5),
            "Loss_":   ("loss",   0.7),
        }
        for layer in m.layers:
            name = getattr(layer, "name", "") or ""
            for prefix, (key, target_opacity) in opacity_map.items():
                if name.startswith(prefix):
                    layer.opacity = target_opacity if key in visible else 0

        # Remove all marker groups first so they can be re-added in a fixed
        # z-order: settlements below, agriculture_loss on top.
        _marker_groups = (("settlements", _settlement_group), ("agriculture_loss", _agriculture_group))
        for _, group_val in _marker_groups:
            grp = group_val()
            if grp is not None and grp in m.layers:
                m.remove_layer(grp)
        for key, group_val in _marker_groups:
            grp = group_val()
            if grp is not None and key in visible:
                m.add_layer(grp)

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

    # Runs only when the country changes (not the year) — compute_agb_loss_time_series
    # caches per iso internally, but depending only on selected_iso() 
    @reactive.effect
    async def load_agb_loss_series():
        iso = selected_iso()
        ee_geometry = get_ee_geometry(data, iso)

        _agb_loss_series.set(None)  # signal "loading" to agb_loss_plot
        df = await asyncio.to_thread(
            compute_agb_loss_time_series, iso, igbp_land_cover, ee_geometry
        )
        _agb_loss_series.set(df)

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

    @output
    @render_widget
    def agb_loss_plot():
        sel_iso = selected_iso()

        try:
            df = _agb_loss_series()

            if df is None:
                return error_fig("Loading…")

            if df.empty:
                return error_fig("No data available.")

            cumulative = input.agb_view() == "cumulative"
            if cumulative:
                df = compute_cumulative_agb_loss(sel_iso, df)

            df_long = df.melt(
                id_vars="year",
                value_vars=["agriculture_agb_Mt", "settlement_agb_Mt"],
                var_name="Driver",
                value_name="AGB Loss (Mt)",
            )
            df_long["Driver"] = df_long["Driver"].map({
                "agriculture_agb_Mt": "Agriculture",
                "settlement_agb_Mt": "Settlements",
            })

            title_prefix = "Cumulative " if cumulative else ""
            fig = px.bar(
                df_long,
                x="year",
                y="AGB Loss (Mt)",
                color="Driver",
                barmode="stack",
                opacity=0.8,
                title=f"{title_prefix}Aboveground Biomass Loss by Driver in {COUNTRY_NAMES.get(sel_iso, sel_iso)}",
                color_discrete_map={"Agriculture": "#FFA500", "Settlements": "#9B59B6"},
                template="plotly_dark",
                height=300,
            )
            return style_bar_fig(fig, xaxis_dtick=2)

        except Exception as e:
            return error_fig(f"Error fetching data: {e}")


app = App(app_ui, server)
