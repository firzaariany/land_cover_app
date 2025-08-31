import os
from pathlib import Path
import gc
import xarray as xr
import pandas as pd

# Initialise CSV directory
select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]
csv_root = Path(__file__).parent / "CSV"
csv_root.mkdir(exist_ok=True)

def calculate_forest_area_changes(country_code):
    """Calculate forest area changes for a specific country"""
    try:
        # Import files
        data_file = f"data/{country_code}/{country_code}_reclassified_forest.nc"
        
        if not Path(data_file).exists():
            print(f"❌ Data file not found: {data_file}")
            return None
        print(f"📊 Processing {country_code}...")
        
        # Load data with chunks for memory efficiency
        master_array = xr.open_dataset(data_file, chunks="auto")["Forest"]
        
        # Calculate forest area changes over time
        resolution = 300*300 # in meters
        conversion_factor = 1e+10 # m2 to million hectares
        
        years = master_array.time.values
        forest_area = {}
        
        for y in years:
            pixel_count = master_array.sel(time=y).count(["lat", "lon"]).values
            forest_area[y] = (pixel_count * resolution) / conversion_factor
            
        # Convert to pandas dataframe
        forest_series = pd.Series(forest_area)
        forest_df = forest_series.to_frame(name="Forest Area")

        # Years as columns
        forest_df = forest_df.reset_index()
        forest_df = forest_df.rename(columns={"index" : "Year"})

        # Add metadata
        forest_df["Unit"] = "million hectares"
        forest_df["Country"] = country_code
        forest_df["Land Cover Type"] = "Forest"
        
        # Ordering column headers
        col_order = ["Country", "Land Cover Type", "Unit", "Year","Forest Area"]
        forest_df = forest_df[col_order]
        
        # Clean up memory
        master_array.close()
        del master_array
        gc.collect()
        
        return forest_df
        
    except Exception as e:
        print(f"❌ Error calculating forest area changes for {country_code}: {e}")
        return None

def main():
    """Main pipeline to process all countries"""
    print("🌳 Starting forest area changes pipeline")
    
    all_df = []
    for iso in select_country:
        country_df = calculate_forest_area_changes(iso)
        
        if country_df is not None:
            all_df.append(country_df)
        else:
            print(f"❌ Failed to process {iso}")
    
    if all_df:
        # Combine all dataframes
        master_df = pd.concat(all_df, ignore_index=True)
        
        # Save combined file
        master_csv = csv_root / "forest_area_changes.csv"
        master_df.to_csv(master_csv, index=False)
        print(f"\n�� Pipeline completed successfully!")
        print(f"🌍 Countries processed: {master_df['Country'].nunique()}")
        print(f"📅 Year range: {master_df['Year'].min()} - {master_df['Year'].max()}")
    
if __name__ == "__main__":
    print("�� Starting script...")
    master_df = main()
    
    if master_df:
        print(f"\n✅ Final dataset shape: {master_df.shape}")
    else:
        print("\n💥 Script failed to produce output!")