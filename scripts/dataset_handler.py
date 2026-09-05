import json
import pandas as pd
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Resolve the absolute path to the project root (/mnt/work/MAYOS)
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = BASE_DIR / "data" / "exercises.csv"
DEFAULT_JSON_PATH = BASE_DIR / "data" / "exercises.json"
DEFAULT_PROCESSED_PATH = BASE_DIR / "data" / "processed_exercises.csv"


from utils.logger import MyosLogger
logger = MyosLogger().get_logger(__name__)

## loading json file
try:
  with open(DEFAULT_JSON_PATH, "r", encoding="utf-8") as json_file:
    json_file_data = json.load(json_file)
    logger.info("JSON file loaded successfully")
except FileNotFoundError:
  logger.error("JSON file not found")

## loading csv file
csv_file_data = pd.read_csv(DEFAULT_CSV_PATH)

## assigning image and gif path at each row in csv
for item, row in zip(json_file_data, csv_file_data.itertuples()):
  csv_file_data.at[row.Index,'image_path'] = item['image']
  csv_file_data.at[row.Index,'gif_path'] = item['gif_url']

processed_df = csv_file_data.drop(columns='gifUrl')

# 3. Combine Instructions
instruction_cols = [c for c in processed_df.columns if c.startswith('instructions/')]
instruction_cols.sort(key=lambda x: int(x.split('/')[1]))

def combine_instructions(row):
    steps = [str(row[c]) for c in instruction_cols if pd.notna(row[c])]
    return "\n".join(steps)

processed_df['instructions'] = processed_df.apply(combine_instructions, axis=1)

# Drop the messy instruction columns
cols_to_drop = [c for c in instruction_cols if c in processed_df.columns]
processed_df.drop(columns=instruction_cols, inplace=True)

# 5. Save the clean output
processed_df.to_csv(DEFAULT_PROCESSED_PATH, index=False)  
logger.info("Data processed. Instructions merged. Saved to processed_exercises.csv")


  
  