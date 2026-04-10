from os import stat

import requests
import json
import re
from bs4 import BeautifulSoup

from namechanges import namechanges

year = input("Enter the year of the election (e.g., 1988): ")

flipColors = True #Set to True to make Democrats red and Republicans blue.

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

# Named third-party candidates tracked separately for distinct colors
Perot_30_40 = []; Perot_40_50 = []; Perot_50_60 = []; Perot_60_70 = []; Perot_70_80 = []; Perot_80_90 = []; Perot_90_100 = []
Wallace_30_40 = []; Wallace_40_50 = []; Wallace_50_60 = []; Wallace_60_70 = []; Wallace_70_80 = []; Wallace_80_90 = []; Wallace_90_100 = []
Unpledged_30_40 = []; Unpledged_40_50 = []; Unpledged_50_60 = []; Unpledged_60_70 = []; Unpledged_70_80 = []; Unpledged_80_90 = []; Unpledged_90_100 = []
tie = []

"""make_path_id: Normalize county names to match MapChart's format, and combine with state code for uniqueness."""
def make_path_id(county_name, state_code):
    name = county_name.strip()
    name = name.replace("\'", "_")
    name = name.replace("-", " ")
    name = re.sub(r'\s+', ' ', name)
    name = name.replace(" ", "_")
    name = name.replace("St._", "St__")
    return f"{name}__{state_code}"


def find_county_table(soup):
    all_tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)

    if state == "Connecticut" and int(year) >= 2024:# In 2023, Connecticut switched to reporting results by "Council of Government" instead of obsolete counties, and the table header reflects this change.
        for t in all_tables:
            header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
            if "Council of Government" in header_text and "Margin" in header_text and "Total" in header_text:
                return t
            
    for t in all_tables:
        header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
        if "Margin" in header_text and "Total" in header_text and "State House" not in header_text:
            if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
                return t

    for t in all_tables:
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t
    for t in soup.find_all('table'):
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t
    for t in soup.find_all('table', class_=lambda c: c and 'mw-collapsible' in c):
        if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
            return t

    return None


def classify_header(text, flat_col):
    """Return the party label for a column header cell."""
    t = text.lower()

    if flat_col == 0 and 'county' not in t and 'parish' not in t:
        return 'County'
    if 'repub' in t:
        return 'Republican'
    if 'democ' in t or 'dfl' in t:
        return 'Democrat'
    if 'margin' in t:
        return 'Margin'
    if 'total' in t:
        return 'Total'
    if flat_col == 0:
        return 'County'

    # ── Named third parties — check before generic Other ──────────────────
    # Wallace: his name, or his party "American Independent"
    if 'wallace' in t or 'american independent' in t:
        return 'Wallace'
    # Unpledged electors / States' Rights
    if 'unpledged' in t or "states' rights" in t or 'states rights' in t:
        return 'Unpledged'
    # Perot: his name, or the Reform Party
    if 'perot' in t or ('reform' in t and 'party' in t):
        return 'Perot'

    # Everything else is generic Other
    return 'Other'


def parse_column_positions(table):
    header_rows = []
    for tr in table.find_all('tr'):
        ths = tr.find_all('th')
        if ths:
            header_rows.append(ths)
        else:
            break

    if not header_rows:
        return {k: None for k in ['rep_votes','rep_pct','dem_votes','dem_pct',
                                   'other_votes','other_pct',
                                   'wallace_votes','wallace_pct',
                                   'unpledged_votes','unpledged_pct',
                                   'perot_votes','perot_pct']}

    PARTY_HINTS = ["republican", "democrat", "democratic", "dfl", "whig",
                   "american", "reform", "independent", "libertarian", "green",
                   "democ", "repub", "wallace", "unpledged", "perot"]

    label_row_idx = 0
    for i, row in enumerate(header_rows):
        joined = " ".join(th.get_text(strip=True) for th in row).lower()
        if any(h in joined for h in PARTY_HINTS):
            label_row_idx = i
            break

    label_row = header_rows[label_row_idx]

    flat_col = 0
    col_party = {}
    for th in label_row:
        text = th.get_text(strip=True)
        colspan = int(th.get('colspan', 1))
        label = classify_header(text, flat_col)
        for i in range(colspan):
            col_party[flat_col + i] = label
        flat_col += colspan

    rep_cols       = [k for k, v in sorted(col_party.items()) if v == 'Republican']
    dem_cols       = [k for k, v in sorted(col_party.items()) if v == 'Democrat']
    other_cols     = [k for k, v in sorted(col_party.items()) if v == 'Other']
    wallace_cols   = [k for k, v in sorted(col_party.items()) if v == 'Wallace']
    unpledged_cols = [k for k, v in sorted(col_party.items()) if v == 'Unpledged']
    perot_cols     = [k for k, v in sorted(col_party.items()) if v == 'Perot']

    # Detect whether percentage comes before vote count
    pct_first = False
    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        row = [td.get_text(strip=True) for td in tds]
        if rep_cols and len(row) > rep_cols[0]:
            val = row[rep_cols[0]].replace('%','').replace(',','').strip()
            try:
                f = float(val)
                if f < 100 and '.' in row[rep_cols[0]]:
                    pct_first = True
            except ValueError:
                pass
        break

    def pick(cols, votes_idx, pct_idx):
        return (cols[votes_idx] if len(cols) > votes_idx else None,
                cols[pct_idx]   if len(cols) > pct_idx   else None)

    if pct_first:
        rv, rp = pick(rep_cols,       1, 0)
        dv, dp = pick(dem_cols,       1, 0)
        ov, op = pick(other_cols,     1, 0)
        wv, wp = pick(wallace_cols,   1, 0)
        uv, up = pick(unpledged_cols, 1, 0)
        pv, pp = pick(perot_cols,     1, 0)
    else:
        rv, rp = pick(rep_cols,       0, 1)
        dv, dp = pick(dem_cols,       0, 1)
        ov, op = pick(other_cols,     0, 1)
        wv, wp = pick(wallace_cols,   0, 1)
        uv, up = pick(unpledged_cols, 0, 1)
        pv, pp = pick(perot_cols,     0, 1)

    return {
        'rep_votes': rv, 'rep_pct': rp,
        'dem_votes': dv, 'dem_pct': dp,
        'other_votes': ov, 'other_pct': op,
        'wallace_votes': wv, 'wallace_pct': wp,
        'unpledged_votes': uv, 'unpledged_pct': up,
        'perot_votes': pv, 'perot_pct': pp,
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
        'Other':      [Other_30_40,      Other_40_50,      Other_50_60,      Other_60_70,
                       Other_70_80,      Other_80_90,      Other_90_100],
        'Wallace':    [Wallace_30_40,    Wallace_40_50,    Wallace_50_60,    Wallace_60_70,
                       Wallace_70_80,    Wallace_80_90,    Wallace_90_100],
        'Unpledged':  [Unpledged_30_40,  Unpledged_40_50,  Unpledged_50_60,  Unpledged_60_70,
                       Unpledged_70_80,  Unpledged_80_90,  Unpledged_90_100],
        'Perot':      [Perot_30_40,      Perot_40_50,      Perot_50_60,      Perot_60_70,
                       Perot_70_80,      Perot_80_90,      Perot_90_100],
        'Tie':        [tie, tie, tie, tie, tie, tie, tie],
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

    #Add any state-specific URL overrides here-----------------------------------
    if state == "Alaska":
        url = "https://en.wikipedia.org/wiki/2024_United_States_presidential_election_in_Alaska"
    
    if state == "California":
        url = "https://en.wikipedia.org/wiki/1962_California_gubernatorial_election"

    if state in ["Colorado", "Connecticut", "Massachusetts", "Minnesota", "New_Jersey", "New_Hampshire", "New_York", "Oregon", "Virginia", "Washington_(state)"]:
        url = "https://en.wikipedia.org/wiki/1984_United_States_presidential_election_in_"+state
    
    if state == "Utah":
        url = "https://en.wikipedia.org/wiki/1980_Utah_gubernatorial_election"
    
    if state == "Vermont":
        url = "https://en.wikipedia.org/wiki/1976_United_States_presidential_election_in_Vermont"
    
    #----------------------------------------------------------------------------

    response = requests.get(url, headers=req_headers)
    soup = BeautifulSoup(response.content, "html.parser")

    table = find_county_table(soup)
    if table is None:
        print(f"  WARNING: Could not find county-level table for {state}. Skipping.")
        continue

    cols = parse_column_positions(table)

    # Debug: report any named third-party columns found
    named = {k: v for k, v in cols.items()
             if v is not None and any(x in k for x in ('wallace','unpledged','perot'))}

    if state == "Alaska" and int(year) < 2024:
        print("Alaska doesn't have results by borough/census area until 2024.")
        continue
    if cols['rep_votes'] is None or cols['dem_votes'] is None and state != "Alaska":
        print(f"  WARNING: Could not identify Republican/Democrat columns for {state}. Skipping.")
        for tr in table.find_all('tr')[:3]:
            print("    Header:", [th.get_text(strip=True) for th in tr.find_all('th')])
        continue

    needed_cols = [c for c in [cols['rep_pct'], cols['dem_pct'], cols['other_pct'],
                                cols['wallace_pct'], cols['unpledged_pct'], cols['perot_pct']]
                   if c is not None]
    max_col = max(needed_cols) if needed_cols else 0
    state_code = postalCodes[state]

    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        row = [td.get_text(strip=True) for td in tds]

        countyName = row[0]
        if not row[0] or row[0].lower() in ('total', 'totals'):
            continue
        if len(row) <= max_col:
            continue

        rep_votes       = safe_int(row[cols['rep_votes']])
        dem_votes       = safe_int(row[cols['dem_votes']])
        other_votes     = safe_int(row[cols['other_votes']])     if cols['other_votes']     else 0
        wallace_votes   = safe_int(row[cols['wallace_votes']])   if cols['wallace_votes']   else 0
        unpledged_votes = safe_int(row[cols['unpledged_votes']]) if cols['unpledged_votes'] else 0
        perot_votes     = safe_int(row[cols['perot_votes']])     if cols['perot_votes']     else 0

        rep_pct         = safe_float(row[cols['rep_pct']])       if cols['rep_pct']         else 0.0
        dem_pct         = safe_float(row[cols['dem_pct']])       if cols['dem_pct']         else 0.0
        other_pct       = safe_float(row[cols['other_pct']])     if cols['other_pct']       else 0.0
        wallace_pct     = safe_float(row[cols['wallace_pct']])   if cols['wallace_pct']     else 0.0
        unpledged_pct   = safe_float(row[cols['unpledged_pct']]) if cols['unpledged_pct']   else 0.0
        perot_pct       = safe_float(row[cols['perot_pct']])     if cols['perot_pct']       else 0.0

        vote_map = {
            'Republican': (rep_votes,       rep_pct),
            'Democrat':   (dem_votes,       dem_pct),
            'Other':      (other_votes,     other_pct),
            'Wallace':    (wallace_votes,   wallace_pct),
            'Unpledged':  (unpledged_votes, unpledged_pct),
            'Perot':      (perot_votes,     perot_pct),
        }

        best_party = max(vote_map, key=lambda p: vote_map[p][0])
        best_votes = vote_map[best_party][0]

        tied = [p for p, (v, _) in vote_map.items() if v == best_votes and best_votes > 0]
        if len(tied) > 1:
            winner, winner_pct = 'Tie', max(vote_map[p][1] for p in tied)
        else:
            winner, winner_pct = best_party, vote_map[best_party][1]

        countyName = namechanges(countyName, state, year)
        path_id = make_path_id(countyName, state_code)
        bucket_county(path_id, winner_pct, winner)

        if state == "Arizona" and countyName == "Yuma" and int(year) < 1984:
            print("  WARNING: La Paz County, AZ was part of Yuma County before 1984. Adding La Paz with same results.")
            bucket_county(make_path_id("La_Paz", state_code), winner_pct, winner)
        if state == "New_Mexico" and countyName == "Valencia" and int(year) < 1984:
            print("  WARNING: Cibola County, NM was part of Valencia County before 1980 and not reported separately until 1984. Adding Cibola with same results.")
            bucket_county(make_path_id("Cibola", state_code), winner_pct, winner)
        if state == "Virginia" and countyName == "Poquoson" and int(year) < 1976:
            print("  WARNING: Poquoson, VA was part of York County before 1976. Adding Poquoson with same results.")
            bucket_county(make_path_id("Poquoson", state_code), winner_pct, winner)

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
                    numbers = re.findall(r'\d+\.\d+', row_text)
                    if numbers:
                        winner_pct = float(numbers[0])
                    break
        path_id = make_path_id("Washington", "DC")
        bucket_county(path_id, winner_pct, winner)
        print(f"  Added District of Columbia as {winner} with {winner_pct}%")

    year = main_year

# ── Build output dict and write valid JSON ────────────────────────────────────
if flipColors:
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
        "#ffccaa": {"label": "Other 30-40%",       "paths": Other_30_40},
        "#ffb380": {"label": "Other 40-50%",       "paths": Other_40_50},
        "#ff994d": {"label": "Other 50-60%",       "paths": Other_50_60},
        "#ff7f2a": {"label": "Other 60-70%",       "paths": Other_60_70},
        "#ff6600": {"label": "Other 70-80%",       "paths": Other_70_80},
        "#e65c00": {"label": "Other 80-90%",       "paths": Other_80_90},
        "#cc5200": {"label": "Other 90-100%",      "paths": Other_90_100},
        "#ffe680": {"label": "Unpledged 30-40%",   "paths": Unpledged_30_40},
        "#ffdc43": {"label": "Unpledged 40-50%",   "paths": Unpledged_40_50},
        "#f4c200": {"label": "Unpledged 50-60%",   "paths": Unpledged_50_60},
        "#e6b800": {"label": "Unpledged 60-70%",   "paths": Unpledged_60_70},
        "#cc9900": {"label": "Unpledged 70-80%",   "paths": Unpledged_70_80},
        "#b38600": {"label": "Unpledged 80-90%",   "paths": Unpledged_80_90},
        "#806000": {"label": "Unpledged 90-100%",  "paths": Unpledged_90_100},
        "#d4b8e0": {"label": "Wallace 30-40%",     "paths": Wallace_30_40},
        "#c49dd0": {"label": "Wallace 40-50%",     "paths": Wallace_40_50},
        "#a875c0": {"label": "Wallace 50-60%",     "paths": Wallace_50_60},
        "#8e4daa": {"label": "Wallace 60-70%",     "paths": Wallace_60_70},
        "#732d94": {"label": "Wallace 70-80%",     "paths": Wallace_70_80},
        "#5c1a7a": {"label": "Wallace 80-90%",     "paths": Wallace_80_90},
        "#400060": {"label": "Wallace 90-100%",    "paths": Wallace_90_100},
        "#c5ffc5": {"label": "Perot 30-40%",       "paths": Perot_30_40},
        "#afe9af": {"label": "Perot 40-50%",       "paths": Perot_40_50},
        "#94c594": {"label": "Perot 50-60%",       "paths": Perot_50_60},
        "#73d873": {"label": "Perot 60-70%",       "paths": Perot_60_70},
        "#30a630": {"label": "Perot 70-80%",       "paths": Perot_70_80},
        "#2b8c2b": {"label": "Perot 80-90%",       "paths": Perot_80_90},
        "#246624": {"label": "Perot 90-100%",      "paths": Perot_90_100},
        "#d4c4dc": {"label": "Tie",                "paths": tie},
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
        "#ffccaa": {"label": "Other 30-40%",       "paths": Other_30_40},
        "#ffb380": {"label": "Other 40-50%",       "paths": Other_40_50},
        "#ff994d": {"label": "Other 50-60%",       "paths": Other_50_60},
        "#ff7f2a": {"label": "Other 60-70%",       "paths": Other_60_70},
        "#ff6600": {"label": "Other 70-80%",       "paths": Other_70_80},
        "#e65c00": {"label": "Other 80-90%",       "paths": Other_80_90},
        "#cc5200": {"label": "Other 90-100%",      "paths": Other_90_100},
        "#ffe680": {"label": "Unpledged 30-40%",   "paths": Unpledged_30_40},
        "#ffdc43": {"label": "Unpledged 40-50%",   "paths": Unpledged_40_50},
        "#f4c200": {"label": "Unpledged 50-60%",   "paths": Unpledged_50_60},
        "#e6b800": {"label": "Unpledged 60-70%",   "paths": Unpledged_60_70},
        "#cc9900": {"label": "Unpledged 70-80%",   "paths": Unpledged_70_80},
        "#b38600": {"label": "Unpledged 80-90%",   "paths": Unpledged_80_90},
        "#806000": {"label": "Unpledged 90-100%",  "paths": Unpledged_90_100},
        "#d4b8e0": {"label": "Wallace 30-40%",     "paths": Wallace_30_40},
        "#c49dd0": {"label": "Wallace 40-50%",     "paths": Wallace_40_50},
        "#a875c0": {"label": "Wallace 50-60%",     "paths": Wallace_50_60},
        "#8e4daa": {"label": "Wallace 60-70%",     "paths": Wallace_60_70},
        "#732d94": {"label": "Wallace 70-80%",     "paths": Wallace_70_80},
        "#5c1a7a": {"label": "Wallace 80-90%",     "paths": Wallace_80_90},
        "#400060": {"label": "Wallace 90-100%",    "paths": Wallace_90_100},
        "#c5ffc5": {"label": "Perot 30-40%",       "paths": Perot_30_40},
        "#afe9af": {"label": "Perot 40-50%",       "paths": Perot_40_50},
        "#94c594": {"label": "Perot 50-60%",       "paths": Perot_50_60},
        "#73d873": {"label": "Perot 60-70%",       "paths": Perot_60_70},
        "#30a630": {"label": "Perot 70-80%",       "paths": Perot_70_80},
        "#2b8c2b": {"label": "Perot 80-90%",       "paths": Perot_80_90},
        "#246624": {"label": "Perot 90-100%",      "paths": Perot_90_100},
        "#d4c4dc": {"label": "Tie",                "paths": tie},
    }}

with open("output.txt", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False)

print("Done! Results written to output.txt")
