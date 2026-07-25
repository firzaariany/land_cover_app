import ee
import pandas as pd
import plotly.express as px
from htmltools import Tag
from shiny import ui

from landcover_explorer.settings import Settings
from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    BIOMASS_BAND_NAME,
    FOREST_BAND_NAME,
    FOREST_COLLECTION,
    aggregate_for_resampling,
    assign_biomass_risk_score,
    assign_forest_type_risk_score,
    compute_aggregate_risk_score,
    load_image,
)
from landcover_explorer.knowledgebase.distance_risk_assets import load_distance_risk_score
from landcover_explorer.knowledgebase.land_cover_stats import calculate_coverage
from landcover_explorer.knowledgebase.risk_stats import (
    ISO_TO_ADM0_NAME,
    rank_admin1_by_risk3_area,
)

settings = Settings()


def get_iso_feature(data: dict, iso: str) -> dict:
    return next(f for f in data["features"] if f["properties"]["GID_0"] == iso)


def get_ee_geometry(data: dict, iso: str) -> ee.Geometry:
    return ee.Geometry(get_iso_feature(data, iso)["geometry"])


def year_slider_with_ticks(min_year: int, max_year: int, value: int, tick_step: int) -> Tag:
    """ui.input_slider doesn't expose ionRangeSlider's grid_num option, so the
    ticks=True heuristic won't necessarily land on 5-year marks — set data-grid-num
    directly on the underlying input so ticks fall exactly every tick_step years."""
    slider = ui.input_slider(
        "year",
        "Select a year",
        min=min_year,
        max=max_year,
        value=value,
        sep="",
        ticks=True,
    )
    grid_num = (max_year - min_year) / tick_step
    for child in slider.children:
        if "js-range-slider" in (getattr(child, "attrs", None) or {}).get("class", ""):
            child.attrs["data-grid-num"] = str(grid_num)
    return slider


def top5_ranking_dataframe(ranking: list[dict] | None) -> pd.DataFrame:
    """Build a table-ready DataFrame from the top-5 admin1 ranking (see risk_stats.py),
    for rendering with shiny.render.data_frame instead of hand-built HTML."""
    columns = ["Rank", "Region", "Area (km2)"]
    if not ranking:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        [
            [rank, region["name"], round(region["risk3_area_m2"] / 1e6, 1)]
            for rank, region in enumerate(ranking, start=1)
        ],
        columns=columns,
    )


def compute_top5_dataframe_for_year(
    iso: str, year: int, ee_geometry: ee.Geometry
) -> tuple[pd.DataFrame, float]:
    """Standalone aggregate-risk pipeline for a single (iso, year): forest + biomass
    + distance risk scores, combined and ranked by admin1. Used by the Compare Years
    page, which needs a top-5 table for an arbitrary year independent of the main
    map's selected year.

    Each of the top 5 regions' area is expressed as a percentage of the total
    at-risk area across ALL admin1 regions (not just the top 5), so the columns
    can sum to less than 100%.

    Returns (top5_dataframe, total_risk3_area_km2) — the total covers every admin1
    region, not just the top 5, so callers can show it alongside the table."""
    columns = ["Region", "Area (km2)", "% of Total"]
    if iso not in ISO_TO_ADM0_NAME:
        return pd.DataFrame(columns=columns), 0.0

    forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, year, ee_geometry)
    biomass_image = load_image(settings.biomass_collection_id, BIOMASS_BAND_NAME, year, ee_geometry)
    if forest_dataset is None or biomass_image is None:
        return pd.DataFrame(columns=columns), 0.0

    forest_risk_score = assign_forest_type_risk_score(forest_dataset)
    biomass_risk_score = assign_biomass_risk_score(aggregate_for_resampling(biomass_image))
    distance_risk_score = load_distance_risk_score(iso, year)

    aggregate_risk_score = compute_aggregate_risk_score(
        biomass_risk_score, forest_risk_score, distance_risk_score
    )

    full_ranking = rank_admin1_by_risk3_area(iso, aggregate_risk_score)
    if not full_ranking:
        return pd.DataFrame(columns=columns), 0.0

    total_risk3_area_m2 = sum(region["risk3_area_m2"] for region in full_ranking)

    df = pd.DataFrame(
        [
            [
                region["name"],
                round(region["risk3_area_m2"] / 1e6, 1),
                round(region["risk3_area_m2"] / total_risk3_area_m2 * 100, 1)
                if total_risk3_area_m2
                else 0.0,
            ]
            for region in full_ranking[:5]
        ],
        columns=columns,
    )
    return df, round(total_risk3_area_m2 / 1e6, 1)


def compute_forest_coverage_pct(iso: str, year: int, ee_geometry: ee.Geometry) -> float | None:
    """Forest cover percentage for a single (iso, year), or None if no forest
    dataset is available for that year. Used to compare forest cover trend
    between two years on the Compare Years page."""
    forest_dataset = load_image(FOREST_COLLECTION, FOREST_BAND_NAME, year, ee_geometry)
    if forest_dataset is None:
        return None

    forest_risk_score = assign_forest_type_risk_score(forest_dataset)
    coverage = calculate_coverage(
        iso=iso, year=year, country_geometry=ee_geometry, forest_cover=forest_risk_score
    )
    return coverage["coverage_pct"]


def style_bar_fig(fig, xaxis_dtick: int | None = None):
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
    xaxis_kwargs = dict(showticklabels=True, tickfont=dict(size=10))
    if xaxis_dtick is not None:
        xaxis_kwargs.update(tickmode="linear", dtick=xaxis_dtick)
    fig.update_xaxes(**xaxis_kwargs)
    return fig


def error_fig(message: str):
    fig = px.bar(x=[], y=[], title=message)
    fig.update_layout(height=300)
    return fig
