import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

INPUT_CSV = "Export_de-de_15012026.csv"
OUTPUT_CSV = "output_translated.csv"

SOURCE_COL = "Default_Translation (en-en)"
TARGET_COL = "Target_Translation (de-de)"

# -----------------------------
# Browser setup
# -----------------------------
options = Options()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

driver.get("https://translate.google.com/?sl=en&tl=de&op=translate")
time.sleep(5)

# -----------------------------
# Load CSV
# -----------------------------
df = pd.read_csv(INPUT_CSV)

translations = []

for i, text in enumerate(df[SOURCE_COL]):
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
        print(f"✔ {i+1}/{len(df)} traduzido")

    except Exception as e:
        print(f"✖ Erro na linha {i+1}: {e}")
        translations.append(text)

df[TARGET_COL] = translations
df["Has_Translation"] = "Yes"

df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

driver.quit()

print("\n✅ Tradução completa!")
print(f"📄 Ficheiro gerado: {OUTPUT_CSV}")
