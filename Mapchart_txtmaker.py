import requests
import json
import re
from bs4 import BeautifulSoup

year = input("Enter the year of the election (e.g., 1988): ")

states = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
          "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
          "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New_Hampshire",
          "New_Jersey", "New_Mexico", "New_York", "North_Carolina", "North_Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
          "Rhode_Island", "South_Carolina", "South_Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington_(state)",
          "West_Virginia", "Wisconsin", "Wyoming"]

postalCodes = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
               "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
               "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
               "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
               "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New_Hampshire": "NH", "New_Jersey": "NJ",
               "New_Mexico": "NM", "New_York": "NY", "North_Carolina": "NC", "North_Dakota": "ND", "Ohio": "OH",
               "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC",
               "South_Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
               "Washington_(state)": "WA", "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}

COUNTY_KEYWORDS = ["County", "Parish", "Borough", "Census area", "District", "City and county", "Municipality"]

# Global result lists
Republican_30_40 = []; Democrat_30_40 = []; Third_party_30_40 = []
Republican_40_50 = []; Democrat_40_50 = []; Third_party_40_50 = []
Republican_50_60 = []; Democrat_50_60 = []; Third_party_50_60 = []
Republican_60_70 = []; Democrat_60_70 = []; Third_party_60_70 = []
Republican_70_80 = []; Democrat_70_80 = []; Third_party_70_80 = []
Republican_80_90 = []; Democrat_80_90 = []; Third_party_80_90 = []
Republican_90_100 = []; Democrat_90_100 = []; Third_party_90_100 = []

"""make_path_id: Normalize county names to match MapChart's format, and combine with state code for uniqueness.  Wikipedia and MapChart don't always use the same naming conventions."""
def make_path_id(county_name, state_code):
    name = county_name.strip()
    name = name.replace("\'", "_")          # replace apostrophes with spaces
    name = name.replace("-", " ")          # treat hyphens as spaces first
    name = re.sub(r'\s+', ' ', name)       # normalize whitespace
    name = name.replace(" ", "_")          # spaces → single underscores
    name = name.replace("St._", "St__")    # fix St. after the space→_ step
    return f"{name}__{state_code}"


def find_county_table(soup):
    all_tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)
    # Prefer table with both Margin and Total in headers (sortable results table)
    for t in all_tables:
        header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
        if "Margin" in header_text and "Total" in header_text and "State House" not in header_text:
            if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
                return t
    # Fallback: any wikitable with county keywords
    for t in all_tables:
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t
    # Last resort: every table
    for t in soup.find_all('table'):
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t
    return None


def parse_column_positions(table):
    """Walk the first header row's <th> elements, expanding colspan,
    to map flat column index -> party label."""
    header_rows = []
    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        if ths:
            header_rows.append(ths)
        else:
            break

    if not header_rows:
        return {k: None for k in ['rep_votes','rep_pct','dem_votes','dem_pct','other_votes','other_pct']}

    col_labels = {}
    flat_col = 0
    for th in header_rows[0]:
        text = th.get_text(strip=True)
        colspan = int(th.get('colspan', 1))
        if 'Republican' in text:
            label = 'Republican'
        elif 'Democrat' in text or 'Democratic' in text or 'DFL' in text:
            label = 'Democrat'
        elif 'Margin' in text:
            label = 'Margin'
        elif 'Total' in text:
            label = 'Total'
        elif flat_col == 0:
            label = 'County'
        else:
            label = 'Other'
        for i in range(colspan):
            col_labels[flat_col + i] = label
        flat_col += colspan

    rep_cols   = [k for k, v in sorted(col_labels.items()) if v == 'Republican']
    dem_cols   = [k for k, v in sorted(col_labels.items()) if v == 'Democrat']
    other_cols = [k for k, v in sorted(col_labels.items()) if v == 'Other']

    return {
        'rep_votes':   rep_cols[0]   if len(rep_cols)   > 0 else None,
        'rep_pct':     rep_cols[1]   if len(rep_cols)   > 1 else None,
        'dem_votes':   dem_cols[0]   if len(dem_cols)   > 0 else None,
        'dem_pct':     dem_cols[1]   if len(dem_cols)   > 1 else None,
        'other_votes': other_cols[0] if len(other_cols) > 0 else None,
        'other_pct':   other_cols[1] if len(other_cols) > 1 else None,
    }


def safe_int(s):
    try:
        return int(s.replace(',', '').replace('\xa0', '').replace('+', '').strip())
    except (ValueError, AttributeError):
        return 0


def safe_float(s):
    try:
        return float(s.replace('%', '').replace('\xa0', '').replace('+', '').strip())
    except (ValueError, AttributeError):
        return 0.0


def bucket_county(path_id, pct, party):
    ranges = [(30,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,101,6)]
    buckets = {
        'Republican': [Republican_30_40, Republican_40_50, Republican_50_60, Republican_60_70,
                       Republican_70_80, Republican_80_90, Republican_90_100],
        'Democrat':   [Democrat_30_40,   Democrat_40_50,   Democrat_50_60,   Democrat_60_70,
                       Democrat_70_80,   Democrat_80_90,   Democrat_90_100],
        'Other':      [Third_party_30_40, Third_party_40_50, Third_party_50_60, Third_party_60_70,
                       Third_party_70_80, Third_party_80_90, Third_party_90_100],
    }
    for lo, hi, idx in ranges:
        if lo <= pct < hi:
            buckets[party][idx].append(path_id)
            return


# ── Main loop ────────────────────────────────────────────────────────────────

for state in states:
    print(f"Processing {state}...")

    url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_{state}"
    req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    response = requests.get(url, headers=req_headers)
    soup = BeautifulSoup(response.content, "html.parser")

    """The county-level results are usually in a table with class 'wikitable sortable', but this isn't consistent.
    We look for tables containing county keywords, and prefer ones with 'Margin' and 'Total"""
    table = find_county_table(soup)
    if table is None:
        print(f"  WARNING: Could not find county-level table for {state}. Skipping.")
        continue

    cols = parse_column_positions(table)

    """If we can't identify the Republican and Democrat vote columns, we won't be able to determine winners.  Skip these tables, but print a warning and the first few header rows to help with debugging.  Alaska is a special case since it doesn't report results by borough/census area until 2024."""

    if cols['rep_votes'] is None or cols['dem_votes'] is None and state == "Alaska" and year < 2024:
        print("Alaska doesn\'t have results by borough/census area until 2024.  Consider adding them to Wikipedia using data from davesredistricting.org.")
        continue
    if cols['rep_votes'] is None or cols['dem_votes'] is None and state != "Alaska" and year >= 2024:
        print(f"  WARNING: Could not identify Republican/Democrat columns for {state}. Skipping.")
        for tr in table.find_all('tr')[:3]:
            print("    Header:", [th.get_text(strip=True) for th in tr.find_all('th')])
        continue

    needed_cols = [c for c in [cols['rep_pct'], cols['dem_pct'], cols['other_pct']] if c is not None]
    max_col = max(needed_cols) if needed_cols else 0
    state_code = postalCodes[state]

    """Walk the table rows, skipping non-data rows, totals, and those with insufficient columns."""
    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        row = [td.get_text(strip=True) for td in tds]

        """Skip rows that don't have a valid county name or are totals, and those that don't have enough columns for the needed data.  Also, row[0] is the county name, but MapChart and Wikipedia sometimes differ on naming."""
        countyName = row[0]
        if not row[0] or row[0].lower() in ('total', 'totals'):
            continue
        if len(row) <= max_col:
            continue
        
        """Extract vote counts and percentages, handling missing/invalid data gracefully.
        Determine the winner and their percentage, then bucket the county accordingly."""
        rep_votes   = safe_int(row[cols['rep_votes']])
        dem_votes   = safe_int(row[cols['dem_votes']])
        other_votes = safe_int(row[cols['other_votes']]) if cols['other_votes'] else 0

        rep_pct   = safe_float(row[cols['rep_pct']])   if cols['rep_pct']   else 0.0
        dem_pct   = safe_float(row[cols['dem_pct']])   if cols['dem_pct']   else 0.0
        other_pct = safe_float(row[cols['other_pct']]) if cols['other_pct'] else 0.0

        if rep_votes >= dem_votes and rep_votes >= other_votes:
            winner, winner_pct = 'Republican', rep_pct
        elif dem_votes >= rep_votes and dem_votes >= other_votes:
            winner, winner_pct = 'Democrat', dem_pct
        else:
            winner, winner_pct = 'Other', other_pct

        """Normalize county name for MapChart: fix certain words."""
        countyName = countyName.replace("\'", "_")

        #-------- Alaska ---------
        countyName = countyName.replace(" City and", "").replace(" Borough", "").replace(" Census Area", "").replace(" Municipality", "")
        countyName = countyName.replace("Southeast Fairbanks", "SE_Fairbanks")
        
        if state == "Florida":
            countyName = countyName.replace("De Soto", "DeSoto")
            countyName = countyName.replace("Miami-Dade", "Miami_Dade")
            if year <= "1988":
                countyName = countyName.replace("Dade", "Miami_Dade")

        countyName = countyName.replace("Kauaʻi", "Kauai")# Hawaii

        if state == "Illinois":
            countyName = countyName.replace("LaSalle", "La_Salle").replace("DeWitt", "De_Witt")# Illinois
        
        countyName = countyName.replace("LaRue", "Larue")# Kentucky

        if state == "Louisiana":
            countyName = countyName.replace("DeSoto", "De_Soto")

        if state == "Maryland":
            if countyName == "Baltimore":
                countyName = "Baltimore_County"

        if state == "Mississippi":
            countyName = countyName.replace("De Soto", "DeSoto")

        countyName = countyName.replace("Ste. Genevieve", "Sainte_Genevieve")#Missouri

        if state == "Missouri":
            if countyName == "St. Louis":
                countyName = "St__Louis_Co_"
            if countyName == "St. Louis City":
                countyName = "St__Louis"
        countyName = countyName.replace("Ormsby", "Carson_City")# Nevada
        countyName = countyName.replace("Coös", "Coos")# New Hampshire
        countyName = countyName.replace("Doña Ana", "Dona_Ana")# New Mexico
        countyName = countyName.replace("LeFlore", "Le_Flore")# Oklahoma
        if state == "South_Dakota":
            countyName = countyName.replace("Shannon", "Oglala_Lakota")

        #-------- Virginia ---------
        if state == "Virginia":
            countyName = countyName.replace("County", "_Co")
            
        countyName = countyName.replace("Fairfax City", "Fairfax")

        path_id = make_path_id(countyName, state_code)
        bucket_county(path_id, winner_pct, winner)


# ── Build output dict and write valid JSON ────────────────────────────────────

output = {"groups": {
    "#d3e7ff": {"label": "Democratic 30-40%",  "paths": Democrat_30_40},
    "#b9d7ff": {"label": "Democratic 40-50%",  "paths": Democrat_40_50},
    "#86b6f2": {"label": "Democratic 50-60%",  "paths": Democrat_50_60},
    "#4389e3": {"label": "Democratic 60-70%",  "paths": Democrat_60_70},
    "#1666cb": {"label": "Democratic 70-80%",  "paths": Democrat_70_80},
    "#0645b4": {"label": "Democratic 80-90%",  "paths": Democrat_80_90},
    "#0047b9": {"label": "Democratic 90-100%", "paths": Democrat_90_100},
    "#ffccd0": {"label": "Republican 30-40%",  "paths": Republican_30_40},
    "#f2b3be": {"label": "Republican 40-50%",  "paths": Republican_40_50},
    "#e27f90": {"label": "Republican 50-60%",  "paths": Republican_50_60},
    "#cc2f4a": {"label": "Republican 60-70%",  "paths": Republican_60_70},
    "#d40000": {"label": "Republican 70-80%",  "paths": Republican_70_80},
    "#aa0000": {"label": "Republican 80-90%",  "paths": Republican_80_90},
    "#800000": {"label": "Republican 90-100%", "paths": Republican_90_100},
}}

with open("output.txt", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False)

print("Done! Results written to output.txt")
