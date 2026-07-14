import ee
import plotly.express as px
from shiny import ui


def get_iso_feature(data: dict, iso: str) -> dict:
    return next(f for f in data["features"] if f["properties"]["GID_0"] == iso)


def get_ee_geometry(data: dict, iso: str) -> ee.Geometry:
    return ee.Geometry(get_iso_feature(data, iso)["geometry"])


def swatch(color: str) -> str:
    return (
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};border-radius:2px;margin-right:6px;vertical-align:middle;"></span>'
    )


def forest_cover_legend_choice(year: int) -> dict:
    return {
        "forest": ui.HTML(f'{swatch("#05450a")} Forest cover {year}'),
        "biomass": ui.HTML(f'{swatch("#fd8d3c")} Above-ground biomass risk {year}'),
        "aggregate": ui.HTML(f'{swatch("#ff0000")} Aggregate risk score {year}'),
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
