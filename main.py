import pandas as pd
import time
import os
import glob
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------
# Configuration & Setup
# -----------------------------
start_time = time.time()
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Find Input CSV
import sys

csv_files = []

# 1. From CLI Argument
if len(sys.argv) > 1:
    potential_file = sys.argv[1]
    if os.path.isfile(potential_file):
        csv_files.append(potential_file)

# 2. From 'import' directory
if not csv_files and os.path.isdir("import"):
    csv_files = [f for f in glob.glob("import/*.csv") if "output" not in f]

# 3. From current directory (fallback)
if not csv_files:
     csv_files = [f for f in glob.glob("*.csv") if "output" not in f and not f.startswith("generated_")]

if not csv_files:
    raise FileNotFoundError("No input CSV file found (checked CLI arg, 'import/' folder, and current directory).")

# Pick the first one (or arguably the most recent, but first is fine for now)
INPUT_CSV = csv_files[0]
print(f"📄 Processing File: {INPUT_CSV}")

# Load CSV to detect columns
df = pd.read_csv(INPUT_CSV)

# Detect Columns
source_col = None
target_col = None
target_lang_code = "unknown"

for col in df.columns:
    if "Default_Translation" in col:
        source_col = col
    elif "Target_Translation" in col:
        target_col = col
        # Extract language code from "Target_Translation (de-de)" -> "de-de"
        match = re.search(r'\((.*?)\)', col)
        if match:
            target_lang_code = match.group(1)

if not source_col or not target_col:
    raise ValueError(f"Could not automatically detect Source or Target columns in {INPUT_CSV}. Found columns: {df.columns.tolist()}")

print(f"✔ detected Source Column: {source_col}")
print(f"✔ detected Target Column: {target_col}")
print(f"✔ detected Target Language: {target_lang_code}")

OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"translated_{target_lang_code}.csv")

# -----------------------------
# Browser setup
# -----------------------------
options = Options()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

# Construct URL based on detected language (assuming source is always english/auto, or we could extract that too)
# The user's original URL was: https://translate.google.com/?sl=en&tl=de&op=translate
# If we want to be safe, we can try to use the code. Note: Google Translate codes usually match 2-letter ISO, but 'de-de' might need just 'de'.
# Let's take the first part of the code if it has a hyphen for the URL, e.g. 'de-de' -> 'de'
tl_param = target_lang_code.split('-')[0]
url = f"https://translate.google.com/?sl=auto&tl={tl_param}&op=translate"
driver.get(url)
time.sleep(5)

translations = []

for i, text in enumerate(df[source_col]):
    if pd.isna(text) or str(text).strip() == "":
        translations.append(text)
        continue

    try:
        input_box = driver.find_element(By.TAG_NAME, "textarea")
        input_box.clear()
        input_box.send_keys(str(text))

        time.sleep(2)

        output = driver.find_element(
            By.CSS_SELECTOR,
            "span[jsname='W297wb']"
        ).text

        translations.append(output)
        print(f"✔ {i+1}/{len(df)} translated")

    except Exception as e:
        print(f"✖ Error at line {i+1}: {e}")
        translations.append(text)

df[target_col] = translations
df["Has_Translation"] = "Yes"

df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

driver.quit()

print("\n✅ Translation Complete!")
print(f"📄 Generated File: {OUTPUT_CSV}")

end_time = time.time()
elapsed_minutes = (end_time - start_time) / 60
print(f"⏱  Execution Time: {elapsed_minutes:.2f} minutes")

