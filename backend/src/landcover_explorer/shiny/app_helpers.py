import ee
import pandas as pd
import plotly.express as px
from htmltools import Tag
from shiny import ui


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
