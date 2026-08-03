import ee

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    BIOMASS_BAND_NAME,
    FOREST_BAND_NAME,
    FOREST_COLLECTION,
    assign_biomass_risk_score,
    assign_forest_type_risk_score,
    compute_aggregate_risk_score,
    load_image,
    aggregate_for_resampling,
)
from landcover_explorer.knowledgebase.distance_risk_assets import load_distance_risk_score
from landcover_explorer.knowledgebase.gfw_preprocess import fetch_forest_loss_by_driver
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage
from landcover_explorer.knowledgebase.risk_stats import (
    ISO_TO_ADM0_NAME,
    build_highlight_image,
    top_n_admin1_by_risk3_area,
    top_n_admin1_collection_by_risk3_area,
)
from landcover_explorer.shiny.app_helpers import (
    AGGREGATE_RISK_PALETTE,
    BIOMASS_RISK_PALETTE,
    FOREST_COVER_COLOR,
    build_annual_forest_cover_stacked_bar,
    build_annual_risk_stacked_bar,
    build_map_legend_html,
    compute_forest_coverage_pct,
    compute_top5_dataframe_for_year,
    error_fig,
    get_ee_geometry,
    get_iso_feature,
    style_bar_fig,
    top5_ranking_dataframe,
    year_slider_with_ticks,
)

import asyncio
import faicons as fa
import geopandas as gpd
import json
import math
import pandas as pd
import plotly.express as px
from ipyleaflet import (
    DivIcon,
    LayerGroup,
    Map,
    Marker,
    TileLayer,
    LayersControl,
    GeoJSON,
    Popup,
    WidgetControl,
)
from ipywidgets import HTML
from pathlib import Path
from shapely.geometry import shape
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

# Can list more countries -> To be set up in a separate module
COUNTRY_NAMES = {
    "MYS": "Malaysia",
    "CRI": "Costa Rica",
    "NOR": "Norway",
    "IDN": "Indonesia",
    "COD": "Democratic Republic of the Congo",
    "JPN": "Japan",
}

MIN_YEAR = 2005
MAX_YEAR = 2025
DEFAULT_YEAR = 2020

FOREST_LAYER_NAME = "Forest cover"
BIOMASS_LAYER_NAME = "Above-ground biomass risk"
AGGREGATE_LAYER_NAME = "Aggregate risk score"
TOP5_LAYER_NAME = "Top 5 highest-risk regions"

ICONS = {
    "region_at_risk": fa.icon_svg("triangle-exclamation", "solid", width="1.5em"),
    "trending_up": fa.icon_svg("arrow-trend-up", "solid"),
    "trending_down": fa.icon_svg("arrow-trend-down", "solid")
}

# -----------------
# DATA PREPARATION
# -----------------

# Global administration border
_GEOJSON_PATH = Path(__file__).parents[3] / settings.gadm_path

with open(_GEOJSON_PATH, "r") as f:
    data = json.load(f)
    data_gdf = gpd.read_file(_GEOJSON_PATH).set_index(["GID_0"])

# Annual total area at risk must be precomputed by scripts/export_distance_risk_assets.py.
# It is set missing until until the script is run.
_ANNUAL_RISK_CSV_PATH = Path(__file__).parents[3] / settings.annual_risk_csv_path
_ANNUAL_RISK_COLUMNS = ["iso", "year", "region", "risk3_area_km2", "distance_risk_available"]
if _ANNUAL_RISK_CSV_PATH.exists():
    annual_risk_df = pd.read_csv(_ANNUAL_RISK_CSV_PATH)
else:
    print(
        f"[warning] {_ANNUAL_RISK_CSV_PATH} not found — run "
        "scripts/export_distance_risk_assets.py to generate it. The year-by-year "
        "total area chart will show no data until then."
    )
    annual_risk_df = pd.DataFrame(columns=_ANNUAL_RISK_COLUMNS)

# Annual forest cover area, precomputed by the same script. Missing until it's run.
_ANNUAL_FOREST_COVER_CSV_PATH = Path(__file__).parents[3] / settings.annual_forest_cover_csv_path
_ANNUAL_FOREST_COVER_COLUMNS = ["iso", "year", "region", "forest_area_km2"]
if _ANNUAL_FOREST_COVER_CSV_PATH.exists():
    annual_forest_cover_df = pd.read_csv(_ANNUAL_FOREST_COVER_CSV_PATH)
else:
    print(
        f"[warning] {_ANNUAL_FOREST_COVER_CSV_PATH} not found — run "
        "scripts/export_distance_risk_assets.py to generate it. The annual forest "
        "cover chart will show no data until then."
    )
    annual_forest_cover_df = pd.DataFrame(columns=_ANNUAL_FOREST_COVER_COLUMNS)

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
        year_slider_with_ticks(
            min_year=MIN_YEAR, max_year=MAX_YEAR, value=DEFAULT_YEAR, tick_step=5
        ),
    ),
    ui.navset_tab(
        ui.nav_panel(
            "Map",
            ui.layout_columns(
                ui.value_box(
                    ui.output_text("insight_card_persistent_top_region_title"),
                    ui.output_text("insight_card_persistent_top_region"),
                    showcase=ICONS["region_at_risk"],
                    height="150px",
                ),
                ui.output_ui("insight_card_forest_cover_trend"),
                ui.output_ui("insight_card_compare_top5_total_risk"),
            ),
            ui.card(
                output_widget("map"),
                height="500px",
                fillable=True,
            ),
            ui.layout_columns(
                ui.card(
                    ui.card_header(ui.output_text("insight_card_top5_header_compare_year1")),
                    ui.input_select(
                        "insight_card_top5_compare_year1",
                        "Year",
                        choices=[str(y) for y in range(MIN_YEAR, MAX_YEAR + 1)],
                        selected=str(DEFAULT_YEAR),
                    ),
                    ui.output_data_frame("insight_card_top5_infobox_compare_year1"),
                    height="400px",
                    fillable=True,
                ),
                ui.card(
                    ui.card_header(ui.output_text("insight_card_top5_header_compare_year2")),
                    ui.input_select(
                        "insight_card_top5_compare_year2",
                        "Compare with year",
                        choices=[str(y) for y in range(MIN_YEAR, MAX_YEAR + 1)],
                        selected=str(max(MIN_YEAR, DEFAULT_YEAR - 10)),
                    ),
                    ui.output_data_frame("insight_card_top5_infobox_compare_year2"),
                    height="400px",
                    fillable=True,
                ),
            ),
        ),
        ui.nav_panel(
            "Graphs",
            ui.card(
                ui.card_header(ui.output_text("graph_forest_loss_header")),
                output_widget("graph_forest_area_plot", height="100%"),
                height="400px",
                fillable=True,
            ),
            ui.card(
                ui.card_header(ui.output_text("graph_annual_risk_header")),
                output_widget("graph_annual_risk_plot", height="100%"),
                height="400px",
                fillable=True,
            ),
            ui.card(
                ui.card_header(ui.output_text("graph_annual_forest_cover_header")),
                output_widget("graph_annual_forest_cover_plot", height="100%"),
                height="400px",
                fillable=True,
            ),
        ),
    ),
    title="Forest Degradation Risk",
    fillable=True,
)

# -----------------
# CONTENT
# -----------------


def server(input, output, session):
    m = Map()
    m.add_control(LayersControl(collapsed=False))
    m.add_control(
        WidgetControl(widget=HTML(build_map_legend_html()), position="bottomright")
    )
    register_widget("map", m)

    _forest_layer_cache: dict = {}
    _compare_top5_cache: dict = {}
    _forest_coverage_cache: dict = {}
    top5_compare_page_dataframe_state = reactive.Value(top5_ranking_dataframe(None))
    top5_compare_page_total_state = reactive.Value(0.0)
    compare_top5_dataframe_state = reactive.Value(top5_ranking_dataframe(None))
    compare_top5_total_state = reactive.Value(0.0)
    forest_cover_trend_state = reactive.Value(None)

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
                forest_risk_score = None
                forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, year, ee_geometry)
                if forest_dataset is not None:
                    forest_risk_score = assign_forest_type_risk_score(forest_dataset)
                    forest_map_id = forest_risk_score.getMapId(
                        {"min": 3, "max": 3, "palette": FOREST_COVER_COLOR}
                    )
                    coverage = calculate_coverage(
                        iso=iso,
                        year=year,
                        country_geometry=ee_geometry,
                        forest_cover=forest_risk_score,
                    )
                    forest_result = {
                        "tile_url": forest_map_id["tile_fetcher"].url_format,
                        "coverage": coverage,
                    }

                biomass_result = None
                biomass_risk_score = None
                biomass_image = load_image(
                    settings.biomass_collection_id, BIOMASS_BAND_NAME, year, ee_geometry
                )
                if biomass_image is not None:
                    biomass_reprojected = aggregate_for_resampling(biomass_image)
                    biomass_risk_score = assign_biomass_risk_score(biomass_reprojected)
                    biomass_map_id = biomass_risk_score.getMapId({
                        "min": 0,
                        "max": 3,
                        "palette": BIOMASS_RISK_PALETTE,
                    })
                    biomass_result = {"tile_url": biomass_map_id["tile_fetcher"].url_format}

                aggregate_result = None
                if (
                    forest_risk_score is not None
                    and biomass_risk_score is not None
                    and iso in ISO_TO_ADM0_NAME
                ):
                    distance_risk_score = load_distance_risk_score(iso, year)
                    distance_asset_missing = distance_risk_score is None

                    aggregate_risk_score = compute_aggregate_risk_score(
                        biomass_risk_score, forest_risk_score, distance_risk_score
                    )
                    aggregate_map_id = aggregate_risk_score.getMapId({
                        "min": 0,
                        "max": 3,
                        "palette": AGGREGATE_RISK_PALETTE,
                    })
                    top5_ranking = top_n_admin1_by_risk3_area(iso, aggregate_risk_score, n=5)
                    top5_collection = top_n_admin1_collection_by_risk3_area(
                        iso, aggregate_risk_score, n=5
                    )
                    top5_map_id = build_highlight_image(top5_collection).getMapId()
                    aggregate_result = {
                        "tile_url": aggregate_map_id["tile_fetcher"].url_format,
                        "top5_tile_url": top5_map_id["tile_fetcher"].url_format,
                        "top5_ranking": top5_ranking,
                        "top5_dataframe": top5_ranking_dataframe(top5_ranking),
                        "distance_asset_missing": distance_asset_missing,
                    }

                return {
                    "forest_tile_url": forest_result["tile_url"] if forest_result else None,
                    "coverage": forest_result["coverage"] if forest_result else None,
                    "biomass_tile_url": biomass_result["tile_url"] if biomass_result else None,
                    "aggregate_tile_url": aggregate_result["tile_url"] if aggregate_result else None,
                    "top5_tile_url": aggregate_result["top5_tile_url"] if aggregate_result else None,
                    "top5_ranking": aggregate_result["top5_ranking"] if aggregate_result else None,
                    "top5_dataframe": (
                        aggregate_result["top5_dataframe"]
                        if aggregate_result
                        else top5_ranking_dataframe(None)
                    ),
                    "distance_asset_missing": (
                        aggregate_result["distance_asset_missing"] if aggregate_result else None
                    ),
                }

            _forest_layer_cache[cache_key] = await asyncio.to_thread(get_forest_cover_layer_data)

        layer_data = _forest_layer_cache[cache_key]

        kept_layers = [
            layer
            for layer in m.layers
            if layer.name
            not in (FOREST_LAYER_NAME, BIOMASS_LAYER_NAME, AGGREGATE_LAYER_NAME, TOP5_LAYER_NAME)
        ]
        new_layers = []
        if layer_data["forest_tile_url"]:
            new_layers.append(TileLayer(
                url=layer_data["forest_tile_url"], name=FOREST_LAYER_NAME, opacity=0.7
            ))
        if layer_data["biomass_tile_url"]:
            new_layers.append(TileLayer(
                url=layer_data["biomass_tile_url"], name=BIOMASS_LAYER_NAME, opacity=0.7
            ))
        if layer_data["aggregate_tile_url"]:
            new_layers.append(TileLayer(
                url=layer_data["aggregate_tile_url"], name=AGGREGATE_LAYER_NAME, opacity=0.7
            ))
        top5_sublayers = []
        if layer_data["top5_tile_url"]:
            top5_sublayers.append(TileLayer(url=layer_data["top5_tile_url"], opacity=1))
        if layer_data["top5_ranking"]:
            badge_reset_style = (
                "<style>.leaflet-div-icon { background: transparent; border: none; }</style>"
            )
            for rank, region in enumerate(layer_data["top5_ranking"], start=1):
                centroid = shape(region["geometry"]).centroid
                badge_icon = DivIcon(
                    html=(
                        badge_reset_style +
                        f'<div style="font-size:14px; font-weight:bold; color:white; '
                        f'background:#d6006d; border:2px solid white; border-radius:50%; '
                        f'width:24px; height:24px; display:flex; align-items:center; '
                        f'justify-content:center;">{rank}</div>'
                    ),
                    icon_size=[24, 24],
                    icon_anchor=[12, 12],
                )
                top5_sublayers.append(Marker(
                    location=(centroid.y, centroid.x),
                    icon=badge_icon,
                    draggable=False,
                ))
        if top5_sublayers:
            new_layers.append(LayerGroup(layers=top5_sublayers, name=TOP5_LAYER_NAME))
        m.layers = tuple(kept_layers + new_layers)
        if layer_data["distance_asset_missing"]:
            ui.notification_show(
                "Distance-to-loss risk hasn't been precomputed for this country/year "
                "yet — the aggregate risk score shown is based on forest type and "
                "biomass only.",
                type="warning",
                duration=8,
            )
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

    @reactive.effect
    async def load_top5_compare_page():
        iso = selected_iso()
        year = int(input.insight_card_top5_compare_year1())

        cache_key = (iso, year)
        if cache_key not in _compare_top5_cache:
            ee_geometry = get_ee_geometry(data, iso)
            _compare_top5_cache[cache_key] = await asyncio.to_thread(
                compute_top5_dataframe_for_year, iso, year, ee_geometry
            )

        df, total_area_km2 = _compare_top5_cache[cache_key]
        top5_compare_page_dataframe_state.set(df)
        top5_compare_page_total_state.set(total_area_km2)

    @reactive.effect
    async def load_compare_top5():
        iso = selected_iso()
        compare_year = int(input.insight_card_top5_compare_year2())

        cache_key = (iso, compare_year)
        if cache_key not in _compare_top5_cache:
            ee_geometry = get_ee_geometry(data, iso)
            _compare_top5_cache[cache_key] = await asyncio.to_thread(
                compute_top5_dataframe_for_year, iso, compare_year, ee_geometry
            )

        df, total_area_km2 = _compare_top5_cache[cache_key]
        compare_top5_dataframe_state.set(df)
        compare_top5_total_state.set(total_area_km2)

    @reactive.effect
    async def load_forest_cover_trend():
        iso = selected_iso()
        year_min, year_max = sorted(
            (int(input.insight_card_top5_compare_year1()), int(input.insight_card_top5_compare_year2()))
        )

        async def coverage_for(year):
            cache_key = (iso, year)
            if cache_key not in _forest_coverage_cache:
                ee_geometry = get_ee_geometry(data, iso)
                _forest_coverage_cache[cache_key] = await asyncio.to_thread(
                    compute_forest_coverage_pct, iso, year, ee_geometry
                )
            return _forest_coverage_cache[cache_key]

        cover_min, cover_max = await coverage_for(year_min), await coverage_for(year_max)

        forest_cover_trend_state.set({
            "year_min": year_min,
            "year_max": year_max,
            "cover_min": cover_min,
            "cover_max": cover_max,
        })

    @output
    @render.text
    def insight_card_top5_header_compare_year1():
        return f"Top 5 regions with highest degradation risk ({input.insight_card_top5_compare_year1()})"

    @output
    @render.data_frame
    def insight_card_top5_infobox_compare_year1():
        return render.DataGrid(top5_compare_page_dataframe_state(), width="100%")

    @output
    @render.text
    def insight_card_top5_header_compare_year2():
        return f"Top 5 regions with highest degradation risk ({input.insight_card_top5_compare_year2()})"

    @output
    @render.data_frame
    def insight_card_top5_infobox_compare_year2():
        return render.DataGrid(compare_top5_dataframe_state(), width="100%")

    @output
    @render.ui
    def insight_card_compare_top5_total_risk():
        year_a, year_b = int(input.insight_card_top5_compare_year1()), int(input.insight_card_top5_compare_year2())
        totals = {year_a: top5_compare_page_total_state(), year_b: compare_top5_total_state()}
        year_min, year_max = sorted((year_a, year_b))
        total_min, total_max = totals[year_min], totals[year_max]

        trending_up = total_max > total_min
        icon = ICONS["trending_up"] if trending_up else ICONS["trending_down"]
        direction = "increasing" if trending_up else "decreasing"
        diff = abs(total_max - total_min)

        return ui.value_box(
            f"Forest area at risk is {direction} between {year_min} and {year_max} by",
            f"{diff:,.1f} km²",
            showcase=icon,
            height="150px",
        )

    @output
    @render.text
    def insight_card_persistent_top_region_title():
        year_min, year_max = sorted(
            (int(input.insight_card_top5_compare_year1()), int(input.insight_card_top5_compare_year2()))
        )
        return f"Region at risk in {year_min} and {year_max}"

    @output
    @render.text
    def insight_card_persistent_top_region():
        df_a = top5_compare_page_dataframe_state()
        df_b = compare_top5_dataframe_state()

        if df_a.empty or df_b.empty:
            return "N/A"

        region_a, region_b = df_a["Region"].iloc[0], df_b["Region"].iloc[0]
        return region_a if region_a == region_b else "None"

    @output
    @render.ui
    def insight_card_forest_cover_trend():
        trend = forest_cover_trend_state()
        if trend is None or trend["cover_min"] is None or trend["cover_max"] is None:
            value = "N/A"
            icon = ICONS["trending_down"]
        else:
            trending_up = trend["cover_max"] > trend["cover_min"]
            icon = ICONS["trending_up"] if trending_up else ICONS["trending_down"]
            value = f"{trend['cover_min']}% → {trend['cover_max']}%"

        if trend:
            year_min, year_max = trend["year_min"], trend["year_max"]
        else:
            year_min, year_max = sorted(
                (int(input.insight_card_top5_compare_year1()), int(input.insight_card_top5_compare_year2()))
            )

        return ui.value_box(
            f"Forest cover trend between {year_min} and {year_max}",
            value,
            showcase=icon,
            height="150px",
        )

    @output
    @render.text
    def graph_forest_loss_header():
        return f"Forest loss by driver ({selected_year()})"

    @reactive.calc
    def gfw_forest_loss():
        return fetch_forest_loss_by_driver(selected_iso())

    @output
    @render_widget
    def graph_forest_area_plot():
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
                template="plotly_white",
            )
            return style_bar_fig(fig)

        except Exception as e:
            return error_fig(f"Error fetching data: {e}")

    @output
    @render.text
    def graph_annual_risk_header():
        return f"Total forest area at risk, categorized by region"

    @output
    @render_widget
    def graph_annual_risk_plot():
        try:
            return build_annual_risk_stacked_bar(annual_risk_df, selected_iso())
        except Exception as e:
            return error_fig(f"Error building chart: {e}")

    @output
    @render.text
    def graph_annual_forest_cover_header():
        return f"Total forest cover area, categorized by region"

    @output
    @render_widget
    def graph_annual_forest_cover_plot():
        try:
            return build_annual_forest_cover_stacked_bar(annual_forest_cover_df, selected_iso())
        except Exception as e:
            return error_fig(f"Error building chart: {e}")


app = App(app_ui, server)
