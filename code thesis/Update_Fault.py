import requests, json, os

BASE       = "https://ulap-hazards.georisk.gov.ph/arcgis/rest/services/PHIVOLCSPublic/ActiveFault/MapServer"
PAGE       = 1000
OUTPUT     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "fault.json")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

# ── Step 1: Discover all layers ──────────────────────────────────────────────
print("🔍 Fetching layer list...")
r = SESSION.get(BASE, params={"f": "json"}, timeout=30)
server_info = r.json()

layers = server_info.get("layers", []) + server_info.get("tables", [])
print(f"Found {len(layers)} layers:")
for l in layers:
    print(f"  [{l['id']}] {l['name']}")

# ── Step 2: Fetch fname lookup table ─────────────────────────────────────────
print("\n🔍 Fetching fault name lookup table...")
fname_lookup = {}

for layer in layers:
    lid = layer["id"]
    try:
        lr    = SESSION.get(f"{BASE}/{lid}", params={"f": "json"}, timeout=30)
        linfo = lr.json()

        for field in linfo.get("fields", []):
            if field.get("name", "").lower() in ("fname", "fault_name", "faultname"):
                domain = field.get("domain", {})
                if domain.get("type") == "codedValue":
                    for cv in domain.get("codedValues", []):
                        fname_lookup[str(cv["code"])] = cv["name"]
                    if fname_lookup:
                        print(f"  ✅ Found {len(fname_lookup)} names via domain in layer {lid}")
                        break

        if not fname_lookup:
            qr = SESSION.get(f"{BASE}/{lid}/query", params={
                "where":                "1=1",
                "outFields":            "fname,fault_name,faultname,name,FNAME,FAULT_NAME",
                "returnDistinctValues": "true",
                "f":                    "json",
                "resultRecordCount":    2000
            }, timeout=30)
            for feat in qr.json().get("features", []):
                a    = feat.get("attributes", {})
                code = a.get("fname") or a.get("FNAME")
                name = (a.get("fault_name") or a.get("FAULT_NAME") or
                        a.get("faultname")  or a.get("FAULTNAME")  or
                        a.get("name")       or a.get("NAME"))
                if code is not None and name:
                    fname_lookup[str(code)] = name
            if fname_lookup:
                print(f"  ✅ Found {len(fname_lookup)} names via query in layer {lid}")

    except Exception as e:
        print(f"  ⚠ Layer {lid} lookup failed: {e}")

if not fname_lookup:
    print("  ⚠ No fault name lookup found — will show Fault #<code>")
else:
    sample = {k: fname_lookup[k] for k in list(fname_lookup)[:5]}
    print(f"  📖 Sample: {sample}")

# ── Step 3: Decode tables ─────────────────────────────────────────────────────
FC_CATEGORY   = {"01": "Active Fault", "02": "Potentially Active Fault"}
TRACE_TYPE    = {
    "01": "Approximate",             "02": "Approximate – Flexure/Warp",
    "03": "Approximate – Upthrown",  "04": "Concealed",
    "05": "Concealed – Flexure/Warp","06": "Concealed – Upthrown",
    "07": "Inferred",                "08": "Inferred – Flexure/Warp",
    "09": "Inferred – Upthrown",     "10": "Well Defined"
}
LOCATION_TYPE = {"01": "Onshore", "02": "Offshore", "03": "On/Offshore"}

# ── Step 4: Download all feature layers ──────────────────────────────────────
all_features = []

for layer in layers:
    lid   = layer["id"]
    lname = layer["name"]
    print(f"\n📥 Layer {lid}: {lname}")

    features = []
    offset   = 0

    while True:
        try:
            resp  = SESSION.get(f"{BASE}/{lid}/query", params={
                "where":             "1=1",
                "outFields":         "*",
                "f":                 "geojson",
                "outSR":             "4326",
                "resultOffset":      offset,
                "resultRecordCount": PAGE
            }, timeout=30)
            data  = resp.json()
            chunk = data.get("features", [])

            for feat in chunk:
                p          = feat.get("properties", {}) or {}
                fname_code = str(p.get("fname", ""))

                # Build only the fields needed by index.html
                feat["properties"] = {
                    "Fault Name":   fname_lookup.get(fname_code, f"Fault #{fname_code}" if fname_code else "Unknown"),
                    "Segment Name": p.get("segname", "") if p.get("segname", "") not in ("", "00") else "Main Trace",
                    "Date Mapped":  str(p.get("datemapped", "")) or "—",
                    "Data Source":  "PHIVOLCS-DOST / GeoRisk Philippines",
                    "Category":     FC_CATEGORY.get(str(p.get("fccode", "")), "Active Fault"),
                    "Trace Type":   TRACE_TYPE.get(str(p.get("ttcode", "")), p.get("ttcode", "—")),
                    "Location":     LOCATION_TYPE.get(str(p.get("ltcode", "")), p.get("ltcode", "—")),
                    "_layerName":   lname
                }

            features.extend(chunk)
            print(f"  ... {len(features)} features")
            if len(chunk) < PAGE:
                break
            offset += PAGE

        except Exception as e:
            print(f"  ❌ Error: {e}")
            break

    print(f"  ✅ {len(features)} features from '{lname}'")
    all_features.extend(features)

# ── Step 5: Save to templates/fault.json ─────────────────────────────────────
geojson = {"type": "FeatureCollection", "features": all_features}
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(geojson, f, indent=2)

size_kb = os.path.getsize(OUTPUT) // 1024
print(f"\n🎉 Done! {len(all_features)} features → {OUTPUT} ({size_kb} KB)")