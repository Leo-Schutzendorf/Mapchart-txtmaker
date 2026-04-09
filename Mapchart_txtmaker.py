import requests
import json
import re
from bs4 import BeautifulSoup

from namechanges import namechanges

year = input("Enter the year of the election (e.g., 1988): ")

flipColors = False #Set to True to make Democrats red and Republicans blue.

main_year = year #So the user can choose different elections for certain states, but it must return to the main year for the next state.

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

COUNTY_KEYWORDS = ["County", "Council of Government", "Parish", "Borough", "Census area", "District", "City and county", "Municipality"]

# Global result lists
Republican_30_40 = []; Democrat_30_40 = []; Other_30_40 = []
Republican_40_50 = []; Democrat_40_50 = []; Other_40_50 = []
Republican_50_60 = []; Democrat_50_60 = []; Other_50_60 = []
Republican_60_70 = []; Democrat_60_70 = []; Other_60_70 = []
Republican_70_80 = []; Democrat_70_80 = []; Other_70_80 = []
Republican_80_90 = []; Democrat_80_90 = []; Other_80_90 = []
Republican_90_100 = []; Democrat_90_100 = []; Other_90_100 = []

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

    # Starting in the 2024 election, Connecticut uses Council of Government areas instead of counties, and the table might be after the obsolete county-level table.  So we look for a table with Council of Government and county keywords, and Margin and Total in the header to ensure it's the results table.  
    if state == "Connecticut" and int(year) >= 2024:
        for t in all_tables:
            header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
            if "Council of Government" in header_text and "Margin" in header_text and "Total" in header_text:
                return t
            
    for t in all_tables:
        header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))

        # Alaska reports results be State House District, not by borough/census area, so we need exclude "State House".
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
    
    # Some tables are collapsible and lack the 'wikitable' class entirely — search for mw-collapsible tables too
    for t in soup.find_all('table', class_=lambda c: c and 'mw-collapsible' in c):
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t

    return None


def parse_column_positions(table):
    """Walk multi-row headers correctly.
    Row 0 (or whichever has party labels) -> build a party-per-flat-col map.
    Row 1 (the # / % sub-header row, if present) -> use those column spans to
    confirm ordering. If only one header row, use it directly."""

    header_rows = []
    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        if ths:
            header_rows.append(ths)
        else:
            break

    if not header_rows:
        return {k: None for k in ['rep_votes','rep_pct','dem_votes','dem_pct','other_votes','other_pct']}

    # ── Find the row that contains party/candidate labels ──────────────────
    PARTY_HINTS = ["republican", "democrat", "democratic", "dfl", "whig",
                   "american", "reform", "independent", "libertarian", "green", 
                   "democ", "repub"]

    label_row_idx = 0
    for i, row in enumerate(header_rows):
        joined = " ".join(th.get_text(strip=True) for th in row).lower()
        if any(h in joined for h in PARTY_HINTS):
            label_row_idx = i
            break

    label_row = header_rows[label_row_idx]

    # ── Build flat-column → party map from the label row ──────────────────
    # For each <th> in the label row, expand colspan and assign a party.
    # "Other" catches third parties by name (e.g. "American", "L. S. Brown American").
    flat_col = 0
    col_party = {}   # flat col index → 'Republican' | 'Democrat' | 'Other' | 'Margin' | 'Total' | 'County'

    # Track how many Republican/Democrat/Other column *groups* we've seen,
    # so that repeated party names (e.g. multi-candidate primaries) still work.
    for th in label_row:
        text = th.get_text(strip=True)
        text_lower = text.lower()
        colspan = int(th.get('colspan', 1))

        if flat_col == 0 and 'county' not in text_lower and 'parish' not in text_lower:
            # Very first column is usually the county name even without a header label
            label = 'County'
        elif 'repub' in text_lower:
            label = 'Republican'
        elif 'democ' in text_lower or 'dfl' in text_lower:
            label = 'Democrat'
        elif 'margin' in text_lower:
            label = 'Margin'
        elif 'total' in text_lower:
            label = 'Total'
        elif flat_col == 0:
            label = 'County'
        else:
            label = 'Other'   # third-party candidates (American, Libertarian, etc.)

        for i in range(colspan):
            col_party[flat_col + i] = label
        flat_col += colspan

    # ── Extract vote/pct column indices for each party ────────────────────
    rep_cols   = [k for k, v in sorted(col_party.items()) if v == 'Republican']
    dem_cols   = [k for k, v in sorted(col_party.items()) if v == 'Democrat']
    other_cols = [k for k, v in sorted(col_party.items()) if v == 'Other']

    pct_first = False
    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        row = [td.get_text(strip=True) for td in tds]
        if len(row) > max(filter(None, [rep_cols[0] if rep_cols else None,
                                        dem_cols[0] if dem_cols else None]), default=0):
            # Check if the first rep column looks like a percentage
            if rep_cols:
                val = row[rep_cols[0]].replace('%','').replace(',','').strip()
                try:
                    f = float(val)
                    if f < 100 and '.' in row[rep_cols[0]]:  # looks like a pct
                        pct_first = True
                except ValueError:
                    pass
        break  # only need first data row

    if pct_first:
        return {
            'rep_votes':   rep_cols[1]   if len(rep_cols)   > 1 else None,
            'rep_pct':     rep_cols[0]   if len(rep_cols)   > 0 else None,
            'dem_votes':   dem_cols[1]   if len(dem_cols)   > 0 else None,
            'dem_pct':     dem_cols[0]   if len(dem_cols)   > 0 else None,
            'other_votes': other_cols[1] if len(other_cols) > 1 else None,
            'other_pct':   other_cols[0] if len(other_cols) > 0 else None,
        }
    else:
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
        'Other':      [Other_30_40, Other_40_50, Other_50_60, Other_60_70,
                       Other_70_80, Other_80_90, Other_90_100],
    }
    for lo, hi, idx in ranges:
        if lo <= pct < hi:
            buckets[party][idx].append(path_id)
            return


# ── Main loop ────────────────────────────────────────────────────────────────

for state in states:
    print(f"Processing {state.replace('_', ' ')}...")

    url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_{state}"
    req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    """Temporarily set url and year for specific states with unique cases, then reset year at the end of the loop for testing."""
    #------------------------------------------------------------------------------
    
    #------------------------------------------------------------------------------

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

    if state == "Alaska" and int(year) < 2024:
        print("Alaska doesn\'t have results by borough/census area until 2024.  Consider adding them to Wikipedia using data from davesredistricting.org.")
        continue
    if cols['rep_votes'] is None or cols['dem_votes'] is None and state != "Alaska":
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

        """Use namechanges.py, a separate file with a function to normalize county names, to handle special cases and ensure consistency with MapChart's naming conventions.  This includes replacing apostrophes, handling specific words like "County" or "Parish", and making state-specific adjustments."""
        countyName = namechanges(countyName, state, year)


        path_id = make_path_id(countyName, state_code)
        bucket_county(path_id, winner_pct, winner)

        # Before the 1980 election, Cibola County, NM was part of Valencia County.  Before the 1984 election, La Paz County, AZ was part of Yuma County.  Add these counties with the same results as their parent counties, but print a warning since this is an approximation.  There are other cases.
        if state == "Arizona" and countyName == "Yuma" and int(year) < 1984:
            print("  WARNING: La Paz County, AZ was part of Yuma County before 1984.  Adding La Paz with the same results as Yuma, but this is an approximation.")
            bucket_county(make_path_id("La_Paz", state_code), winner_pct, winner)
        if state == "New_Mexico" and countyName == "Valencia" and int(year) < 1980:
            print("  WARNING: Cibola County, NM was part of Valencia County before 1980.  Adding Cibola with the same results as Valencia, but this is an approximation.")
            bucket_county(make_path_id("Cibola", state_code), winner_pct, winner)
        if state == "Virginia" and countyName == "Poquoson" and int(year) < 1976:
            print("  WARNING: Poquoson, VA was part of York County before 1976.  Adding Poquoson with the same results as York, but this is an approximation.")
            bucket_county(make_path_id("Poquoson", state_code), winner_pct, winner)
    
    """DC can be treated as a county-equivalent for MapChart, but its results are in an infobox, not a table.  Its results are in the same row as "Percentage", with the winner on the left side, second place on the right side.  Also, 
    it's in the seventh row, under "Popular vote" and two below "Electoral vote".  I chose to do this after Delaware because it's next in ABC order."""

    if state == "Delaware":
        url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_the_District_of_Columbia"
        response = requests.get(url, headers=req_headers)
        soup = BeautifulSoup(response.content, "html.parser")
        infobox = soup.find('table', class_='infobox')
        winner_pct = 0.0
        winner = "Democrat"
        if infobox:
            for row in infobox.find_all('tr'):
                if "Percentage" in row.get_text():
                    row_text = row.get_text(strip=True)
                    # Strip the word "Percentage" from the front, then grab the first number
                    numbers = re.findall(r'\d+\.\d+', row_text)
                    if numbers:
                        winner_pct = float(numbers[0])
                    break
        path_id = make_path_id("Washington", "DC")
        bucket_county(path_id, winner_pct, winner)
        print(f"  Added District of Columbia as {winner} with {winner_pct}%")
    year = main_year #Reset year in case it was changed for a specific state

# ── Build output dict and write valid JSON ────────────────────────────────────
if flipColors: #Optionally flip red/blue colors for Democrats and Republicans
    output = {"groups": {
        "#d3e7ff": {"label": "Republican 30-40%",  "paths": Republican_30_40},
        "#b9d7ff": {"label": "Republican 40-50%",  "paths": Republican_40_50},
        "#86b6f2": {"label": "Republican 50-60%",  "paths": Republican_50_60},
        "#4389e3": {"label": "Republican 60-70%",  "paths": Republican_60_70},
        "#1666cb": {"label": "Republican 70-80%",  "paths": Republican_70_80},
        "#0645b4": {"label": "Republican 80-90%",  "paths": Republican_80_90},
        "#003ab4": {"label": "Republican 90-100%", "paths": Republican_90_100},
        "#ffccd0": {"label": "Democratic 30-40%",  "paths": Democrat_30_40},
        "#f2b3be": {"label": "Democratic 40-50%",  "paths": Democrat_40_50},
        "#e27f90": {"label": "Democratic 50-60%",  "paths": Democrat_50_60},
        "#cc2f4a": {"label": "Democratic 60-70%",  "paths": Democrat_60_70},
        "#d40000": {"label": "Democratic 70-80%",  "paths": Democrat_70_80},
        "#aa0000": {"label": "Democratic 80-90%",  "paths": Democrat_80_90},
        "#800000": {"label": "Democratic 90-100%", "paths": Democrat_90_100},
        "#ffccaa": {"label": "Other 30-40%",  "paths": Other_30_40},
        "#ffb380": {"label": "Other 40-50%",  "paths": Other_40_50},
        "#ff994d": {"label": "Other 50-60%",  "paths": Other_50_60},
        "#ff7f2A": {"label": "Other 60-70%",  "paths": Other_60_70},
        "#ff6600": {"label": "Other 70-80%",  "paths": Other_70_80},
        "#e65c00": {"label": "Other 80-90%",  "paths": Other_80_90},
        "#cc5200": {"label": "Other 90-100%", "paths": Other_90_100},
    }}
else:
    output = {"groups": {
        "#d3e7ff": {"label": "Democratic 30-40%",  "paths": Democrat_30_40},
        "#b9d7ff": {"label": "Democratic 40-50%",  "paths": Democrat_40_50},
        "#86b6f2": {"label": "Democratic 50-60%",  "paths": Democrat_50_60},
        "#4389e3": {"label": "Democratic 60-70%",  "paths": Democrat_60_70},
        "#1666cb": {"label": "Democratic 70-80%",  "paths": Democrat_70_80},
        "#0645b4": {"label": "Democratic 80-90%",  "paths": Democrat_80_90},
        "#003ab4": {"label": "Democratic 90-100%", "paths": Democrat_90_100},
        "#ffccd0": {"label": "Republican 30-40%",  "paths": Republican_30_40},
        "#f2b3be": {"label": "Republican 40-50%",  "paths": Republican_40_50},
        "#e27f90": {"label": "Republican 50-60%",  "paths": Republican_50_60},
        "#cc2f4a": {"label": "Republican 60-70%",  "paths": Republican_60_70},
        "#d40000": {"label": "Republican 70-80%",  "paths": Republican_70_80},
        "#aa0000": {"label": "Republican 80-90%",  "paths": Republican_80_90},
        "#800000": {"label": "Republican 90-100%", "paths": Republican_90_100},
        "#ffccaa": {"label": "Other 30-40%",  "paths": Other_30_40},
        "#ffb380": {"label": "Other 40-50%",  "paths": Other_40_50},
        "#ff994d": {"label": "Other 50-60%",  "paths": Other_50_60},
        "#ff7f2A": {"label": "Other 60-70%",  "paths": Other_60_70},
        "#ff6600": {"label": "Other 70-80%",  "paths": Other_70_80},
        "#e65c00": {"label": "Other 80-90%",  "paths": Other_80_90},
        "#cc5200": {"label": "Other 90-100%", "paths": Other_90_100},
    }}

with open("output.txt", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False)

print("Done! Results written to output.txt")
