import pandas as pd
import time
import os
import glob
import re
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------
# Configuration & Setup
# -----------------------------
start_time = time.time()
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define Files to Process
# Automatically find all CSV files in the 'import' directory
csv_files = glob.glob(os.path.join("import", "*.csv"))
FILES_TO_PROCESS = [{"input": f} for f in csv_files]


# -----------------------------
# Browser setup
# -----------------------------
options = Options()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

# Deduplicate FILES_TO_PROCESS
seen_inputs = set()
unique_files = []
for f in FILES_TO_PROCESS:
    if f["input"] not in seen_inputs:
        unique_files.append(f)
        seen_inputs.add(f["input"])
FILES_TO_PROCESS = unique_files

try:
    for file_config in FILES_TO_PROCESS:
        input_csv = file_config["input"]
        # Output is now dynamic based on detected language

        if not os.path.exists(input_csv):
            print(f"⚠️  Input file not found: {input_csv}. Skipping.")
            continue

        print(f"\n📄 Processing File: {input_csv}")

        # Load CSV
        df = pd.read_csv(input_csv)

        # Detect Columns
        source_col = None
        target_col = None
        target_lang_code = "unknown"

        for col in df.columns:
            if "Default_Translation" in col:
                source_col = col
            elif "Target_Translation" in col:
                target_col = col
                match = re.search(r'\((.*?)\)', col)
                if match:
                    target_lang_code = match.group(1)

        if not source_col or not target_col:
            print(f"✖ Could not detect columns in {input_csv}. Skipping.")
            continue

        print(f"✔ detected Source Column: {source_col}")
        print(f"✔ detected Target Column: {target_col}")
        print(f"✔ detected Target Language: {target_lang_code}")

        # Dynamic Output Filename
        output_csv = os.path.join(OUTPUT_DIR, f"translated_{target_lang_code}.csv")

        # Navigate to Google Translate
        tl_param = target_lang_code.split('-')[0]
        url = f"https://translate.google.com/?sl=en&tl={tl_param}&op=translate"
        driver.get(url)
        time.sleep(5)

        translations = []
        total_rows = len(df)

        for i in range(total_rows):
            source_text = df.at[i, source_col]
            existing_target = df.at[i, target_col]

            # Check existing translation
            if not pd.isna(existing_target) and str(existing_target).strip() != "":
                translations.append(existing_target)
                continue

            # Check valid source
            if pd.isna(source_text) or str(source_text).strip() == "":
                translations.append(source_text)
                continue

            # Random delay to mimic human behavior and avoid rate limits
            time.sleep(random.uniform(1.5, 3.5))

            # Retry logic for translation to handle StaleElementReferenceException
            max_retries = 3
            translated_text = None
            
            for attempt in range(max_retries):
                try:
                    # Wait for input box to be present and interactable
                    input_box = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "textarea"))
                    )
                    input_box.clear()
                    
                    # Small wait after clear to let UI catch up
                    time.sleep(0.5)
                    
                    input_box.send_keys(str(source_text))

                    # Smart Wait: Wait until the output element is present AND has text (length > 0)
                    # We create a custom condition lambda for this.
                    def output_has_text(d):
                        elms = d.find_elements(By.CSS_SELECTOR, "span[jsname='W297wb']")
                        if not elms:
                            return False
                        elm = elms[0]
                        return len(elm.text.strip()) > 0 and elm.text.strip() != "Translating..."

                    WebDriverWait(driver, 15).until(output_has_text)
                    
                    # Stability Check: Ensure text doesn't change for a moment (handling ongoing translation)
                    # We start with a baseline text
                    output_element = driver.find_element(By.CSS_SELECTOR, "span[jsname='W297wb']")
                    current_text = output_element.text
                    
                    # Verify stability for up to 5 seconds
                    stable_start = time.time()
                    is_stable = False
                    
                    while time.time() - stable_start < 5:
                        time.sleep(0.5)
                        try:
                            # Re-fetch element to avoid staleness
                            new_element = driver.find_element(By.CSS_SELECTOR, "span[jsname='W297wb']")
                            new_text = new_element.text
                            
                            if new_text == current_text and new_text.strip() != "":
                                is_stable = True
                                break
                            else:
                                current_text = new_text
                        except StaleElementReferenceException:
                             continue # If stale, retry loop

                    if is_stable:
                        translated_text = current_text
                    else:
                         # If we timed out waiting for stability, just take what we have
                        translated_text = current_text
                    
                    # If we got here, success
                    translations.append(translated_text)
                    print(f"✔ {i+1}/{total_rows} translated")
                    break

                except (StaleElementReferenceException, Exception) as e:
                    if attempt < max_retries - 1:
                        time.sleep(1) # Wait a bit before retrying
                        continue
                    else:
                        print(f"✖ Error at line {i+1} after {max_retries} attempts: {e}")
                        translations.append(source_text)

        df[target_col] = translations
        df["Has_Translation"] = "Yes"

        # Ensure output directory exists (already ensured globally, but good practice)
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"✅ Generated File: {output_csv}")

finally:
    driver.quit()

print("\n🏁 All tasks completed.")


end_time = time.time()
elapsed_minutes = (end_time - start_time) / 60
print(f"⏱  Execution Time: {elapsed_minutes:.2f} minutes")

