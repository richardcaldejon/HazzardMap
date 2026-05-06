import os
import json
import re
import uuid
from bs4 import BeautifulSoup
from datetime import datetime
import threading
import time

# =========================
# FILE PATHS
# =========================
HTML_FILE = os.path.join("phivolcs.html")
JSON_FILE = "history.json"

# =========================
# HELPERS
# =========================
def extract_float(value):
    match = re.search(r"-?\d+(\.\d+)?", value)
    return float(match.group()) if match else None

def clean_text(value):
    return value.replace("Â°", "°").strip()

def parse_datetime(text):
    try:
        return datetime.strptime(text, "%d %B %Y - %I:%M %p")
    except:
        return None

def extract_place(text):
    return clean_text(text)

# =========================
# SUCCESS FLAG
# =========================
success = False

try:
    # ---------------- LOAD EXISTING JSON ----------------
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
            except:
                existing_data = []
    else:
        existing_data = []

    existing_times = {item["time"] for item in existing_data if "time" in item}

    # ---------------- LOAD HTML ----------------
    with open(HTML_FILE, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f, "html.parser")

    rows = soup.find_all("tr")
    new_data = []

    # ---------------- PARSE ----------------
    for row in rows:
        cols = row.find_all("td")

        if len(cols) < 6:
            continue

        try:
            a_tag = cols[0].find("a")
            datetime_text = a_tag.get_text(strip=True) if a_tag else cols[0].get_text(strip=True)

            dt = parse_datetime(datetime_text)
            if not dt:
                continue

            time_ms = int(dt.timestamp() * 1000)

            if time_ms in existing_times:
                continue

            lat_raw = cols[1].get_text(strip=True)
            lon_raw = cols[2].get_text(strip=True)
            depth_raw = cols[3].get_text(strip=True)
            mag_raw = cols[4].get_text(strip=True)
            loc_raw = cols[5].get_text(" ", strip=True)

            if not any(c.isdigit() for c in lat_raw):
                continue

            new_data.append({
                "time": time_ms,
                "place": extract_place(loc_raw),
                "magnitude": extract_float(mag_raw),
                "latitude": extract_float(lat_raw),
                "longitude": extract_float(lon_raw),
                "depth_km": extract_float(depth_raw),
                "id": str(uuid.uuid4())[:10]
            })

        except Exception as e:
            print("Row skipped:", e)

    # ---------------- MERGE + SAVE ----------------
    all_data = existing_data + new_data
    all_data.sort(key=lambda x: x["time"], reverse=True)

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)

    print("===================================")
    print(f"Total earthquakes stored: {len(all_data)}")
    print("Saved to:", JSON_FILE)
    print("===================================")

    # mark success ONLY if we reached here
    success = True

except Exception as e:
    print("❌ Extraction failed:", e)

# =========================
# DELETE HTML IF SUCCESS within 5 seconds
# =========================


if success and os.path.exists(HTML_FILE):
    def delete_file():
        time.sleep(2)
        if os.path.exists(HTML_FILE):
            os.remove(HTML_FILE)

    threading.Thread(target=delete_file).start()
