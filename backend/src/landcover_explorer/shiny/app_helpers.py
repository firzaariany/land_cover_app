import ee
import plotly.express as px
from shiny import ui

from landcover_explorer.knowledgebase.gee_tiles_preprocess import (
    FOREST_COLOR_MAP,
    FOREST_TYPE_LABELS,
)


def get_iso_feature(data: dict, iso: str) -> dict:
    return next(f for f in data["features"] if f["properties"]["GID_0"] == iso)


def get_ee_geometry(data: dict, iso: str) -> ee.Geometry:
    return ee.Geometry(get_iso_feature(data, iso)["geometry"])


def swatch(color: str) -> str:
    return (
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};border-radius:2px;margin-right:6px;vertical-align:middle;"></span>'
    )


def legend_choices(year: int) -> dict:
    return {
        "forest": ui.HTML(f'{swatch("#228B22")} Forest cover {year}'),
        "loss":   ui.HTML(f'{swatch("#CC0000")} Forest loss 2000–{year}'),
    }


def forest_type_legend() -> ui.Tag:
    """Static color key for the forest subtypes rendered by the categorical
    forest cover tile (see FOREST_COLOR_MAP / compute_forest_type_mask)."""
    rows = "".join(
        f'<div style="margin:2px 0;">{swatch(color)}{FOREST_TYPE_LABELS[code]}</div>'
        for code, color in FOREST_COLOR_MAP.items()
    )
    return ui.div(
        ui.HTML(rows),
        style="font-size:11px; margin-left:18px; margin-top:2px;",
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
