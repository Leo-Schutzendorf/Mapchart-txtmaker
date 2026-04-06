import requests
from bs4 import BeautifulSoup
import pandas as pd

#Ask for year
year = input("Enter the year of the election (e.g., 1988): ")

url = "https://en.wikipedia.org/wiki/1992_United_States_presidential_election_in_Delaware"

states = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
          "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
          "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New_Hampshire",
          "New_Jersey", "New_Mexico", "New_York", "North_Carolina", "North_Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
          "Rhode_Island", "South_Carolina", "South_Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington_(State)",
          "West_Virginia", "Wisconsin", "Wyoming"]

postalCodes = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
               "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
               "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
               "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New_Hampshire": "NH", "New_Jersey": "NJ", "New_Mexico": "NM", "New_York": "NY", "North_Carolina": "NC",
               "North_Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC", "South_Dakota": "SD", "Tennessee": "TN",
               "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington_(State)": "WA", "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}

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
print("Print 1st row")
print(rows[0])

"""Get the state winner and runner-up from the first two rows of the table. The first row contains the winner, and the second row contains the runner-up. If neither row contains "Republican"
or "Democrat", then we can assume that a third party candidate was the runner-up."""

header = rows
if "Republican" in header[1]:
    state_winner = "Republican"
    RepLoc = 1
if "Democrat" in header[1]:
    state_winner = "Democrat"
    DemLoc = 1
if "Republican" not in header[1] and "Democrat" not in header[1]:
    state_winner = "Third party"
    ThirdpartyLoc = 1

if "Republican" in header[2]:
    state_runner_up = "Republican"
    RepLoc = 2
if "Democrat" in header[2]:
    state_runner_up = "Democrat"
    DemLoc = 2
if "Republican" not in header[2] and "Democrat" not in header[2]:
    state_runner_up = "Third party"
    ThirdpartyLoc = 2

if "Republican" in header[3]:
    state_third_place = "Republican"
    RepLoc = 3
if "Democrat" in header[3]:
    state_third_place = "Democrat"
    DemLoc = 3
if "Republican" not in header[3] and "Democrat" not in header[3]:
    state_third_place = "Third party"
    ThirdpartyLoc = 3

Republican_30_40 = []
Democrat_30_40 = []
Third_party_30_40 = []
Republican_40_50 = []
Democrat_40_50 = []
Third_party_40_50 = []
Republican_50_60 = []
Democrat_50_60 = []
Third_party_50_60 = []
Republican_60_70 = []
Democrat_60_70 = []
Third_party_60_70 = []
Republican_70_80 = []
Democrat_70_80 = []
Third_party_70_80 = []
Republican_80_90 = []
Democrat_80_90 = []
Third_party_80_90 = []
Republican_90_100 = []
Democrat_90_100 = []
Third_party_90_100 = []
# write results to txt file
with open("output.txt", "w", encoding="utf-8") as f:
    f.write("\{\"groups\":\{\"\#2166ac\":\{\"label\":\"Democrat\",\"paths\":\n[")
    for row in rows:
        f.write(f"{row}\n")
for i, row in enumerate(rows):
    print(f"Row {i} (len={len(row)}): {row}")
for row in rows[2:]:  # Skip header rows
    if int(row[1].replace(',', ''))>=int(row[3].replace(',', '')) and int(row[1].replace(',', ''))>=int(row[5].replace(',', '')):
        county_winner = state_winner
    if int(row[3].replace(',', ''))>=int(row[1].replace(',', '')) and int(row[3].replace(',', ''))>=int(row[5].replace(',', '')):
        county_winner = state_runner_up

    """Assign the county winner to a list based on their percentage of the vote."""
    if county_winner == "Republican":
        if int(row[2].replace(',', ''))>=30:
            pass