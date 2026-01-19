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
print("---------------------------------------------------------")
print(" TRASNLATION SCRIPT SETTINGS ")
print("---------------------------------------------------------")
print("Select Mode:")
print(" [1] FILL MISSING (Scans Input File only, fills gaps)")
print(" [2] RETRANSLATE ALL (Overwrites everything)")
print(" [3] RESUME CRASH (Loads existing Output file to continue)")
mode_input = input("Selection: ").strip().upper()

FORCE_RETRANSLATE = False
RESUME_FROM_OUTPUT = False

if mode_input == "2" or mode_input == "ALL":
    FORCE_RETRANSLATE = True
    print(">> MODE: RETRANSLATE ALL (Fresh Start)")
elif mode_input == "3" or "RESUME" in mode_input:
    RESUME_FROM_OUTPUT = True
    print(">> MODE: RESUME (Loading Output file)")
else:
    # Default to 1
    print(">> MODE: FILL MISSING (Input Scan)")

print("---------------------------------------------------------")
time.sleep(2)

start_time = time.time()
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define Files to Process
# Automatically find all Excel files in the 'import' directory
excel_files = glob.glob(os.path.join("import", "*.xlsx"))
FILES_TO_PROCESS = [{"input": f} for f in excel_files]


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

        # Load Excel (use openpyxl engine)
        # Load ALL sheets to preserve metadata
        xls = pd.ExcelFile(input_csv, engine='openpyxl')
        all_sheets = pd.read_excel(xls, sheet_name=None) # Returns dict {sheet_name: df}
        
        # Determine which sheet is the Translations sheet
        # Priority: "Translations" -> First Sheet
        sheet_name = None
        if "Translations" in all_sheets:
            sheet_name = "Translations"
        else:
            sheet_name = list(all_sheets.keys())[0]
            
        df = all_sheets[sheet_name]
        
        print(f"✔ Working on Sheet: {sheet_name}")
        print(f"✔ Found {len(all_sheets)} sheets: {list(all_sheets.keys())}")

        # Detect Columns
        source_col = None
        target_col = None
        target_lang_code = "unknown"

        for col in df.columns:
            # Check for British English source
            if "British English (en-en)" in col or "en-en" in col:
                source_col = col
            # Check for Target Language (matches regex (xx-xx) but not en-en)
            elif "(" in col and ")" in col:
                match = re.search(r'\((.*?)\)', col)
                if match:
                    code = match.group(1)
                    if code != "en-en":
                        target_col = col
                        target_lang_code = code

            # Fallback for previous CSV header style if mixed
            if not source_col and "Default_Translation" in col:
                source_col = col
            if not target_col and "Target_Translation" in col:
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
        output_excel = os.path.join(OUTPUT_DIR, f"translated_{target_lang_code}.xlsx")

        # ----------------------------------------------------------------
        # Resume Logic: Check if we have partial progress in Output directory
        # ONLY IF USER SELECTED MODE 3 (RESUME)
        # ----------------------------------------------------------------
        if RESUME_FROM_OUTPUT and os.path.exists(output_excel):
            print(f"🔄 Found existing output file: {output_excel}. Resuming from there...")
            try:
                # Load the output file
                xls_out = pd.ExcelFile(output_excel, engine='openpyxl')
                all_sheets_out = pd.read_excel(xls_out, sheet_name=None)
                
                # Check if our target sheet exists in output
                if sheet_name in all_sheets_out:
                    df_out = all_sheets_out[sheet_name]
                    # Verify length
                    if len(df_out) == len(df):
                        df = df_out
                        # Update our main container
                        all_sheets[sheet_name] = df
                        
                        # Count existing
                        try:
                            valid_count = df[target_col].dropna().apply(lambda x: str(x).strip() != "").sum()
                            print(f"✅ Successfully loaded progress from output file.")
                            print(f"ℹ️  Found {valid_count} existing translations in '{target_col}'.")
                        except:
                            print("✅ Successfully loaded progress from output file.")
                            
                    else:
                        print(f"⚠️ Warning: Output file length ({len(df_out)}) differs from input ({len(df)}). Using Input file (starting over).")
                else:
                     print(f"⚠️ Output file exists but missing sheet '{sheet_name}'. Starting over.")
            except Exception as e:
                print(f"⚠️ Could not load existing output file: {e}. Using Input file.")
        
        # If Mode 1 (Fill Missing) or just failed to load output, we proceed with 'df' (from input)
        # logic below handles skipping if values exist (which handles Fill Missing nicely).

        # ------------------------------------------------------
        # Pre-check: Identify rows that actually need translation
        # ------------------------------------------------------
        total_rows = len(df)
        rows_to_process = []
        
        for i in range(total_rows):
            source_text = df.at[i, source_col]
            existing_target = df.at[i, target_col]
            
            # Condition 1: Source must be valid
            if pd.isna(source_text) or str(source_text).strip() == "":
                continue
                
                
            # Condition 2: Check if already translated
            # We treat all non-empty source rows as candidates for processing/verification.
            # BUT if we want to RESUME, we must skip the ones we already have values for.
            # Re-enabling the skip logic for existing translations for RESUME functionality.
            # UNLESS FORCE_RETRANSLATE is on.
            if not FORCE_RETRANSLATE:
                if not pd.isna(existing_target) and str(existing_target).strip() != "":
                   continue
                
            rows_to_process.append(i)

        count_needed = len(rows_to_process)
        print(f"📊 Rows total: {total_rows}")
        print(f"⏭  Already translated/Empty: {total_rows - count_needed}")
        print(f"🔄 Need translation: {count_needed}")

        if count_needed == 0:
            print(f"✅ File {input_csv} is already fully processed. Skipping.")
            continue

        # Navigate to Google Translate
        tl_param = target_lang_code.split('-')[0]
        url = f"https://translate.google.com/?sl=en&tl={tl_param}&op=translate"
        driver.get(url)
        time.sleep(5)

        translations = []
        current_target_data = df[target_col].tolist()
        
        # Save interval
        SAVE_INTERVAL = 10
        changes_since_save = 0
        
        for i in range(total_rows):
            # If this row wasn't marked for processing, skip it (it's either done or empty)
            if i not in rows_to_process:
                continue
            
            source_text = df.at[i, source_col]
            
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
                    # Update our local list (which mimics the column)
                    current_target_data[i] = translated_text
                    print(f"✔ {i+1}/{total_rows} translated")
                    
                    # Update DataFrame immediately
                    df.at[i, target_col] = translated_text
                    
                    changes_since_save += 1
                    if changes_since_save >= SAVE_INTERVAL:
                        print(f"💾 Auto-saving progress... ({i+1}/{total_rows})")
                        # Write ALL sheets
                        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                            for s_name, s_df in all_sheets.items():
                                s_df.to_excel(writer, sheet_name=s_name, index=False)
                        changes_since_save = 0
                        
                    break

                except Exception as e:
                    # Check for critical session errors
                    error_str = str(e).lower()
                    if "invalid session id" in error_str or "no such window" in error_str:
                        print(f"🔥 Critical Error: {e}")
                        print("🛑 Stopping execution to prevent data corruption/loss.")
                        # Save what we have so far
                        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                            for s_name, s_df in all_sheets.items():
                                s_df.to_excel(writer, sheet_name=s_name, index=False)
                        raise e # Re-raise to exit the loop/script

                    if attempt < max_retries - 1:
                        time.sleep(1) # Wait a bit before retrying
                        continue
                    else:
                        print(f"✖ Error at line {i+1} after {max_retries} attempts: {e}")
                        current_target_data[i] = source_text

        df[target_col] = current_target_data
        df["Has Translation"] = "Yes"
        # Update the dict
        all_sheets[sheet_name] = df

        # Final Save
        os.makedirs(os.path.dirname(output_excel), exist_ok=True)
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            for s_name, s_df in all_sheets.items():
                s_df.to_excel(writer, sheet_name=s_name, index=False)
        print(f"✅ Generated File: {output_excel}")

finally:
    driver.quit()

print("\n🏁 All tasks completed.")


end_time = time.time()
elapsed_minutes = (end_time - start_time) / 60
print(f"⏱  Execution Time: {elapsed_minutes:.2f} minutes")

