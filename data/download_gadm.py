# Global Administrative Areas Database (GADM) downloader
# https://gadm.org/

import os
import pycountry
import geopandas as gpd
import pandas as pd

# Directory to save GADM data
GADM_DIR = 'data/gadm_raw'
os.makedirs(GADM_DIR, exist_ok=True)

# Retrieve all countries from pycountry, storing their names and ISO codes
country_pairs = [(country.name, country.alpha_3) for country in pycountry.countries]
iso_codes = [country_pairs[num][1] for num in range(0, len(country_pairs))]

# Download GADM data for each country
for code in iso_codes:
    print("..............")
    print(f".....{code}......")
    print("..............")

    # Check if the file already exists
    gadm_file = os.path.join(GADM_DIR, f'gadm41_{code}_0.json')
    
    if os.path.exists(gadm_file):
        print(f"File {gadm_file} already exists. Skipping download.")
        continue

    # Construct the URL for the GADM data
    url = f'https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_{code}_0.json'

    # Download the GADM data
    try:
        os.system(f'wget -P {GADM_DIR} {url}')

        print(f"Downloaded {gadm_file}")
    except Exception as e:
        print(f"Failed to download {gadm_file}: {e}")

# Compile individual country shapefiles into a single shapefile
iso_dict = {}

for file in os.listdir(GADM_DIR):
    if file.endswith(".json"):
        # Read country borders
        read = gpd.read_file(f'{GADM_DIR}/{file}')

        # Get the country name
        name = file.split("_")[-2]
        iso_dict[name] = read
        
        # Delete the zip file after extraction - to save space
        os.remove(f"{GADM_DIR}/{file}")

# Country borders in the world
global_borders = pd.concat(iso_dict.values()).reset_index(drop=True)

# Export for future use
global_borders.to_file("data/global_adm_borders.shp")
print("Global borders saved to data/global_adm_borders.shp")
