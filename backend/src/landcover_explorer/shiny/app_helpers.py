import math

import ee
import plotly.express as px
from ipyleaflet import CircleMarker, LayerGroup
from shiny import ui


def get_iso_feature(data: dict, iso: str) -> dict:
    return next(f for f in data["features"] if f["properties"]["GID_0"] == iso)


def get_ee_geometry(data: dict, iso: str) -> ee.Geometry:
    return ee.Geometry(get_iso_feature(data, iso)["geometry"])


def build_loss_markers(centroids: list, color: str, layer_name: str) -> LayerGroup:
    max_area = max((pt["loss_area_m2"] for pt in centroids), default=1)
    return LayerGroup(
        layers=[
            CircleMarker(
                location=[pt["lat"], pt["lon"]],
                radius=max(3, int(math.sqrt(pt["loss_area_m2"] / max_area) * 25)),
                color=color,
                fill_color=color,
                fill_opacity=0.7,
                weight=1,
                tooltip=f'{pt["name"]}: {pt["loss_area_m2"] / 1e6:.1f} km²',
            )
            for pt in centroids
        ],
        name=layer_name,
    )


def swatch(color: str) -> str:
    return (
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};border-radius:2px;margin-right:6px;vertical-align:middle;"></span>'
    )


def legend_choices(year: int) -> dict:
    return {
        "forest":           ui.HTML(f'{swatch("#228B22")} Forest cover {year}'),
        "agriculture_loss": ui.HTML(f'{swatch("#E67E22")} Forest loss in agriculture 2001–{year}'),
        "settlements":      ui.HTML(f'{swatch("#9B59B6")} Forest loss in settlements 2001–{year}'),
        "loss":             ui.HTML(f'{swatch("#CC0000")} Forest loss 2000–{year}'),
    }


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
