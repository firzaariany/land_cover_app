import concurrent.futures

import ee
import pandas as pd

from landcover_explorer.settings import Settings

settings = Settings()

BIOMASS_DATA = settings.biomass_collection_id
BIOMASS_BAND = settings.biomass_collection_band_name
tile_collection_resolution = settings.modis_collection_resolution

# # Both series only depend on the country, not the selected year — cache per iso
# # so changing the year in the UI doesn't re-hit GEE.
# _agb_loss_time_series_cache: dict[str, pd.DataFrame] = {}
# _agb_loss_cumulative_cache: dict[str, pd.DataFrame] = {}


# def import_biomass_layer(select_year, geometry):
#     agb_data = ee.ImageCollection(BIOMASS_DATA).select(BIOMASS_BAND)
#     agb_data_selected = (
#         agb_data.filter(ee.Filter.calendarRange(select_year, select_year, "year"))
#         .first()
#         .clip(geometry)
#     )

#     return agb_data_selected


# def compute_agb_loss_by_driver(land_cover_dataset, geometry, select_year):
#     """Total AGB (Mt) lost to deforestation in select_year, split by proximate driver.

#     Converts the AGB raster (Mg/ha density) to a per-pixel biomass mass, masks it to
#     Hansen forest-loss pixels, then sums separately within pixels classified as
#     agriculture vs. settlement in select_year.

#     Returns
#     -------
#     dict with keys: agriculture_agb_Mt, settlement_agb_Mt
#     """
#     agb_density = import_biomass_layer(select_year, geometry)
#     forest_loss_mask = compute_forest_loss_mask(geometry, select_year)
#     agriculture_mask = compute_agriculture_mask(land_cover_dataset, geometry, select_year)
#     settlement_mask = compute_settlement_mask(land_cover_dataset, geometry, select_year)

#     agb_loss_mass = (
#         agb_density.multiply(ee.Image.pixelArea().divide(10_000))
#         .updateMask(forest_loss_mask)
#     )

#     combined = ee.Image.cat([
#         agb_loss_mass.updateMask(agriculture_mask).rename("agriculture_agb_Mg"),
#         agb_loss_mass.updateMask(settlement_mask).rename("settlement_agb_Mg"),
#     ])

#     result = combined.reduceRegion(
#         reducer=ee.Reducer.sum(),
#         geometry=geometry,
#         scale=tile_collection_resolution,
#         maxPixels=1e9,
#     ).getInfo()

#     return {
#         "agriculture_agb_Mt": result.get("agriculture_agb_Mg", 0) / 1e6,
#         "settlement_agb_Mt": result.get("settlement_agb_Mg", 0) / 1e6,
#     }


# def compute_agb_and_forest_area_by_state(land_cover_dataset, select_year, select_country):
#     """Average AGB density (Mg/ha) within forest pixels, per admin-1 state.

#     Computed as total AGB stock divided by total forest area within each state boundary.
#     States with no forest area get a null density rather than a divide-by-zero.
#     """
#     admin1_regions = ee.FeatureCollection("FAO/GAUL/2015/level1").filter(
#         ee.Filter.eq("ADM0_NAME", select_country)
#     )
#     geometry = admin1_regions.geometry()

#     agb_density = import_biomass_layer(select_year, geometry)  # Mg/ha
#     forest_mask = _compute_mask(land_cover_dataset, geometry, select_year, FOREST_CODES)

#     agb_mass = agb_density.multiply(ee.Image.pixelArea().divide(10_000)).updateMask(forest_mask)  # Mg per pixel
#     forest_area = ee.Image.pixelArea().updateMask(forest_mask)  # m² per pixel

#     combined = ee.Image.cat([
#         agb_mass.rename("agb_Mg"),
#         forest_area.rename("forest_area_m2"),
#     ])
#     admin1_totals = combined.reduceRegions(
#         collection=admin1_regions,
#         reducer=ee.Reducer.sum(),
#         scale=tile_collection_resolution,
#         tileScale=4,
#     )

#     def _agb_per_forest_area(feature):
#         forest_area_ha = ee.Number(feature.get("forest_area_m2")).divide(10_000)
#         agb_Mg = ee.Number(feature.get("agb_Mg"))
#         density = ee.Algorithms.If(forest_area_ha.gt(0), agb_Mg.divide(forest_area_ha), None)
#         return feature.set("agb_density_Mg_per_ha", density)

#     return admin1_totals.map(_agb_per_forest_area).select(["ADM1_NAME", "agb_density_Mg_per_ha"])


# def compute_agb_loss_time_series(iso, land_cover_dataset, geometry, start_year=2001, end_year=2024):
#     """AGB loss by driver for each year in [start_year, end_year], skipping years with no AGB image.

#     Cached per iso since the result doesn't depend on the selected year. Years are fetched from
#     GEE concurrently — each is an independent getInfo() round trip, so this is network-bound.
#     """
#     if iso in _agb_loss_time_series_cache:
#         return _agb_loss_time_series_cache[iso]

#     def _loss_for_year(year):
#         try:
#             return year, compute_agb_loss_by_driver(land_cover_dataset, geometry, year)
#         except ee.EEException:
#             return year, None  # no AGB image for this year

#     years = range(start_year, end_year + 1)
#     with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
#         results = executor.map(_loss_for_year, years)
#         records = [{"year": year, **loss} for year, loss in results if loss is not None]

#     agb_loss_df = pd.DataFrame(records)
#     _agb_loss_time_series_cache[iso] = agb_loss_df

#     return agb_loss_df


# def compute_cumulative_agb_loss(iso, agb_loss_df):
#     """Running total of AGB loss by driver over years, given the output of compute_agb_loss_time_series.

#     Cached per iso since the result doesn't depend on the selected year.
#     """
#     if iso in _agb_loss_cumulative_cache:
#         return _agb_loss_cumulative_cache[iso]

#     agb_loss_cumulative_df = agb_loss_df.copy()
#     agb_loss_cumulative_df[["agriculture_agb_Mt", "settlement_agb_Mt"]] = (
#         agb_loss_df[["agriculture_agb_Mt", "settlement_agb_Mt"]].cumsum()
#     )
#     _agb_loss_cumulative_cache[iso] = agb_loss_cumulative_df

#     return agb_loss_cumulative_df
