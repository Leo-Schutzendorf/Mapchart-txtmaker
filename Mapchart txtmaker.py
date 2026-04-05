import requests
from bs4 import BeautifulSoup
import pandas as pd

url = "https://en.wikipedia.org/wiki/1988_United_States_presidential_election_in_Utah"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.content, "html.parser")

# Find the table that contains "County"
tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)

table = None
for t in tables:
    if "County" in t.get_text() or "Parish" in t.get_text():
        table = t
        break

rows = []
for tr in table.find_all('tr'):
    cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
    if cells:
        rows.append(cells)

# write results to txt file
with open("output.txt", "w", encoding="utf-8") as f:
    f.write("\{\"groups\":\{\"\#2166ac\":\{\"label\":\"Democrat\",\"paths\":\n[")
    for row in rows:
        f.write(f"{row}\n")
for i, row in enumerate(rows):
    print(f"Row {i} (len={len(row)}): {row}")