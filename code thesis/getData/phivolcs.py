import requests
import urllib3

# disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://earthquake.phivolcs.dost.gov.ph/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

response = requests.get(url, headers=headers, verify=False)

with open("phivolcs.html", "w", encoding="utf-8") as f:
    f.write(response.text)

print("Downloaded successfully!")