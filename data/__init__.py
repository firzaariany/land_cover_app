import os
from pathlib import Path

# Create COG directory and country subdirectories
select_country = ["MYS", "CRI", "NZL", "NOR", "IDN"]
cog_root = Path(__file__).parent / "COG"
cog_root.mkdir(exist_ok=True)

for iso in select_country:
    country_dir = cog_root / iso
    if country_dir.exists():
        print(f"{country_dir} already exists. Skipping {iso}.")
        continue
    country_dir.mkdir()
    print(f"Created directory: {country_dir}")
