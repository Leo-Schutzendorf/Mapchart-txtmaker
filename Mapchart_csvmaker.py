import requests
import re
from bs4 import BeautifulSoup
import csv

# ====================== CONFIG ======================
year = input("Enter the year of the election (e.g., 2024): ").strip()

for year in [1960, 1964, 1968, 1972, 1976, 1980, 1984, 1988, 1992, 1996, 2000, 2004, 2008, 2012, 2016, 2020, 2024]:
    states = [
        "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
        "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
        "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
        "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
        "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
        "New_Hampshire", "New_Jersey", "New_Mexico", "New_York",
        "North_Carolina", "North_Dakota", "Ohio", "Oklahoma", "Oregon",
        "Pennsylvania", "Rhode_Island", "South_Carolina", "South_Dakota",
        "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
        "Washington_(state)", "West_Virginia", "Wisconsin", "Wyoming"
    ]

    postalCodes = {
        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
        "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
        "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
        "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
        "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
        "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
        "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
        "New_Hampshire": "NH", "New_Jersey": "NJ", "New_Mexico": "NM", "New_York": "NY",
        "North_Carolina": "NC", "North_Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
        "Oregon": "OR", "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC",
        "South_Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington_(state)": "WA",
        "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
    }

    COUNTY_KEYWORDS = [
        "County", "Parish", "Borough", "Census Area", "Municipality",
        "Council of Government", "District", "City and county"
    ]


    # ====================== NAME CHANGES ======================
    def namechanges(countyName, state, year):
        """Normalize county name for MapChart path IDs."""
        countyName = countyName.replace("'", "_")
        countyName = countyName.replace(" ", "_")
        countyName = countyName.replace("St.", "St_")
        # Alaska
        countyName = countyName.replace("_City_and", "").replace("_Borough", "").replace("_Census_Area", "").replace("_Municipality", "")
        countyName = countyName.replace("Southeast_Fairbanks", "SE_Fairbanks")
        countyName = countyName.replace("_Planning_Region", "")  # Connecticut

        if state == "Florida":
            countyName = countyName.replace("De_Soto", "DeSoto")
            countyName = countyName.replace("Miami-Dade", "Miami_Dade")
            if int(year) <= 1988:
                countyName = countyName.replace("Dade", "Miami_Dade")

        countyName = countyName.replace("Kauaʻi", "Kauai")  # Hawaii

        if state == "Illinois":
            countyName = countyName.replace("LaSalle", "La_Salle").replace("DeWitt", "De_Witt")

        countyName = countyName.replace("LaRue", "Larue")  # Kentucky

        if state == "Louisiana":
            countyName = countyName.replace("DeSoto", "De_Soto")

        if state == "Maryland":
            if countyName == "Baltimore":
                countyName = "Baltimore_County"
            if "Mary" in countyName and "St" in countyName:
                countyName = "St_Mary_s"

        if state == "Mississippi":
            countyName = countyName.replace("De_Soto", "DeSoto")

        countyName = countyName.replace("Ste._Genevieve", "Sainte_Genevieve")  # Missouri

        if state == "Missouri":
            if countyName == "St._Louis":
                countyName = "St__Louis_Co_"
            if countyName == "St._Louis_City":
                countyName = "St__Louis"

        countyName = countyName.replace("Ormsby", "Carson_City")  # Nevada
        countyName = countyName.replace("Coös", "Coos")           # New Hampshire
        countyName = countyName.replace("Doña_Ana", "Dona_Ana")   # New Mexico
        countyName = countyName.replace("LeFlore", "Le_Flore")    # Oklahoma

        if state == "South_Dakota":
            countyName = countyName.replace("Shannon", "Oglala_Lakota")

        if state == "Virginia":
            countyName = countyName.replace("_County", "_Co_")
            countyName = countyName.replace("Bedford", "Bedford_Co_")
            if countyName == "Fairfax":
                countyName = "Fairfax_Co_"
            if "Franklin" in countyName and "City" not in countyName:
                countyName = "Franklin_Co_"
            if countyName == "Richmond":
                countyName = "Richmond_Co_"
            if countyName == "Roanoke":
                countyName = "Roanoke_Co_"
            if "_City" in countyName and "James_City" not in countyName and "Charles" not in countyName:
                countyName = countyName.replace("_City", "")

        return countyName


    # ====================== HELPERS ======================
    def safe_int(s):
        try:
            return int(re.sub(r'[^\d]', '', str(s)))
        except:
            return 0

    def safe_float(s):
        try:
            cleaned = re.sub(r'[^\d.]', '', str(s))
            return float(cleaned) if cleaned else 0.0
        except:
            return 0.0

    def is_pct(val):
        """Return True if the string looks like a percentage (has a decimal or %)."""
        s = str(val).strip()
        return '%' in s or ('.' in s and re.search(r'\d+\.\d+', s) is not None)


    # ====================== HEADER PARSING ======================
    # Wikipedia county tables have multi-row headers with colspans.
    # We expand them into a flat list of (party_label, sub_label) per column.
    # party_label is one of: 'county', 'democrat', 'republican', 'other:<name>',
    #                         'margin', 'total', 'unknown'
    # sub_label is '#' (votes) or '%' (percentage)

    PARTY_KEYWORDS = {
        'democrat': ['democrat', 'democratic', 'dfl'],
        'republican': ['republican', 'repub'],
        'margin': ['margin'],
        'total': ['total votes', 'total cast', 'votes cast', 'total'],
    }

    THIRD_PARTY_SKIP = ['margin']  # labels we will skip entirely in output


    def classify_party(text):
        t = text.lower().strip()
        if not t:
            return None
        for party, keywords in PARTY_KEYWORDS.items():
            if any(k in t for k in keywords):
                return party
        # Anything else with 'candidate' or a proper noun is a third party
        if re.search(r'[A-Z]', text):  # has uppercase → likely a name/party
            return f'other:{text.strip()}'
        return None


    def parse_headers(table):
        """
        Returns a list of dicts, one per data column (0-indexed from first <td> in data rows):
            {'party': str, 'sub': '#' | '%'}
        'county' party marks the county-name column.
        """
        header_rows = []
        for tr in table.find_all('tr'):
            cells = tr.find_all(['th', 'td'])
            if not cells:
                continue
            # Stop collecting header rows once we hit a row that looks like data
            if all(c.name == 'td' for c in cells):
                break
            header_rows.append(cells)
            if len(header_rows) == 3:  # Wikipedia never uses more than 3 header rows
                break

        if not header_rows:
            return []

        # Build a grid: grid[row][col] = text
        # We need to expand rowspan/colspan
        max_cols = 20
        grid = [[None] * max_cols for _ in range(len(header_rows))]

        for ri, cells in enumerate(header_rows):
            col = 0
            for cell in cells:
                # Skip already-filled slots (from rowspan above)
                while col < max_cols and grid[ri][col] is not None:
                    col += 1
                text = cell.get_text(separator=' ', strip=True)
                cs = int(cell.get('colspan', 1))
                rs = int(cell.get('rowspan', 1))
                for dr in range(rs):
                    for dc in range(cs):
                        if ri + dr < len(header_rows) and col + dc < max_cols:
                            grid[ri + dr][col + dc] = text
                col += cs

        # Determine how many columns are actually used
        n_cols = max(
            (i for i in range(max_cols) if any(grid[r][i] is not None for r in range(len(header_rows)))),
            default=-1
        ) + 1

        # The top header row sets the party, the bottom row sets #/%
        # Find which row is the "party" row and which is the "#/%" row
        # Strategy: the party row has multi-colspan cells; the sub row has '#' and '%'
        party_row_idx = 0
        sub_row_idx = len(header_rows) - 1

        # Assign party and sub for each column
        columns = []
        for col in range(n_cols):
            party_text = grid[party_row_idx][col] or ''
            sub_text = grid[sub_row_idx][col] or ''

            # County column: first column, or explicitly labelled
            if col == 0:
                columns.append({'party': 'county', 'sub': 'name'})
                continue

            # Classify party from the top row
            party = classify_party(party_text)

            # Sub-column type
            sub_lower = sub_text.lower()
            if '#' in sub_lower or 'vote' in sub_lower or sub_lower == '#':
                sub = '#'
            elif '%' in sub_lower:
                sub = '%'
            else:
                # Fall back: if sub_text is the same as party_text, no sub-header
                sub = '#'  # default

            columns.append({'party': party or 'unknown', 'sub': sub})

        return columns


    # ====================== FIND TABLE ======================
    def find_county_table(soup, state, year):
        all_tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)
        # Connecticut 2024+ uses "Council of Government"
        if state == "Connecticut" and int(year) >= 2024:
            for t in all_tables:
                header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
                if "Council of Government" in header_text and "Margin" in header_text:
                    return t
        for t in all_tables:
            header_text = " ".join(th.get_text(strip=True) for th in t.find_all('th'))
            if "Margin" in header_text and "Total" in header_text and "State House" not in header_text:
                if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
                    return t
        for t in all_tables:
            if any(kw in t.get_text() for kw in COUNTY_KEYWORDS):
                return t
        return None


    # ====================== MAIN SCRAPING ======================
    all_results = []
    # We'll collect party columns dynamically; start with the fixed ones.
    # extra_parties will be populated from the first state that has third parties.
    extra_party_labels = []  # ordered list of 'other:Name' strings seen across all states

    REQ_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for state in states:
        display = state.replace('_', ' ')
        print(f"Processing {display}...")

        url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_{state}"
        try:
            response = requests.get(url, headers=REQ_HEADERS, timeout=15)
            soup = BeautifulSoup(response.content, "html.parser")
        except Exception as e:
            print(f"  ERROR fetching {display}: {e}")
            continue

        table = find_county_table(soup, state, year)
        if not table:
            print(f"  WARNING: No county table found for {display}")
            continue

        if state == "Alaska" and int(year) < 2024:
            print(f"  SKIP: Alaska has no borough results before 2024")
            continue

        columns = parse_headers(table)
        if not columns:
            print(f"  WARNING: Could not parse headers for {display}")
            continue

        # Identify column indices by role
        county_col   = next((i for i, c in enumerate(columns) if c['party'] == 'county'), 0)
        dem_votes_col = next((i for i, c in enumerate(columns) if c['party'] == 'democrat' and c['sub'] == '#'), None)
        dem_pct_col   = next((i for i, c in enumerate(columns) if c['party'] == 'democrat' and c['sub'] == '%'), None)
        rep_votes_col = next((i for i, c in enumerate(columns) if c['party'] == 'republican' and c['sub'] == '#'), None)
        rep_pct_col   = next((i for i, c in enumerate(columns) if c['party'] == 'republican' and c['sub'] == '%'), None)
        total_col     = next((i for i, c in enumerate(columns) if c['party'] == 'total' and c['sub'] == '#'), None)

        if dem_votes_col is None or rep_votes_col is None:
            print(f"  WARNING: Cannot identify Dem/Rep columns for {display}")
            continue

        # Collect third-party columns for this state (excluding margin/total)
        state_extra = {}  # label -> (votes_col, pct_col)
        for i, c in enumerate(columns):
            p = c['party']
            if p and p.startswith('other:') and p not in ('margin',):
                if p not in state_extra:
                    state_extra[p] = {'votes': None, 'pct': None}
                if c['sub'] == '#':
                    state_extra[p]['votes'] = i
                elif c['sub'] == '%':
                    state_extra[p]['pct'] = i
        # Register any new third-party labels globally (preserving insertion order)
        for label in state_extra:
            if label not in extra_party_labels:
                extra_party_labels.append(label)

        state_code = postalCodes.get(state, state[:2].upper())

        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if not tds:
                continue
            row = [td.get_text(strip=True) for td in tds]

            if not row[county_col] or row[county_col].lower() in ('total', 'totals', ''):
                continue

            def get_int(col):
                return safe_int(row[col]) if col is not None and col < len(row) else 0

            def get_float(col):
                return safe_float(row[col]) if col is not None and col < len(row) else 0.0

            dem_votes = get_int(dem_votes_col)
            rep_votes = get_int(rep_votes_col)
            dem_pct   = get_float(dem_pct_col)
            rep_pct   = get_float(rep_pct_col)

            # Gather extra party votes/pcts
            extra_votes = {}
            extra_pcts  = {}
            for label, cols in state_extra.items():
                extra_votes[label] = get_int(cols['votes'])
                extra_pcts[label]  = get_float(cols['pct'])

            # Combine all "other" for totals / winner logic
            other_votes_total = sum(extra_votes.values())
            total_votes = get_int(total_col) if total_col else dem_votes + rep_votes + other_votes_total
            if total_votes == 0:
                continue

            # Determine winner
            vote_map = {'Democrat': dem_votes, 'Republican': rep_votes}
            for label in extra_votes:
                vote_map[label] = extra_votes[label]
            winner_label = max(vote_map, key=vote_map.get)
            if winner_label == 'Democrat':
                winner, winner_pct = 'Democrat', dem_pct
            elif winner_label == 'Republican':
                winner, winner_pct = 'Republican', rep_pct
            else:
                winner = winner_label.replace('other:', '')
                winner_pct = extra_pcts.get(winner_label, 0.0)

            county_raw  = row[county_col]
            county_name = namechanges(county_raw, state, year)
            path_id     = f"{county_name}__{state_code}"

            record = {
                "State":              display,
                "County__State_Code": path_id,
                "Democrat_Votes":     dem_votes,
                "Democrat_Pct":       round(dem_pct, 2),
                "Republican_Votes":   rep_votes,
                "Republican_Pct":     round(rep_pct, 2),
            }
            for label in extra_party_labels:
                col_name = label.replace('other:', '')
                record[f"{col_name}_Votes"] = extra_votes.get(label, 0)
                record[f"{col_name}_Pct"]   = round(extra_pcts.get(label, 0.0), 2)

            record["Total_Votes"]  = total_votes
            record["Winner"]       = winner
            record["Winner_Pct"]   = round(winner_pct, 2)

            all_results.append(record)


    # ====================== WRITE CSV ======================
    # Build final fieldnames: fixed columns first, then any extra parties, then totals
    fixed_start = ["State", "County__State_Code", "Democrat_Votes", "Democrat_Pct",
                "Republican_Votes", "Republican_Pct"]
    extra_fields = []
    for label in extra_party_labels:
        col_name = label.replace('other:', '')
        extra_fields += [f"{col_name}_Votes", f"{col_name}_Pct"]
    fixed_end = ["Total_Votes", "Winner", "Winner_Pct"]

    fieldnames = fixed_start + extra_fields + fixed_end

    csv_filename = f"{year}results.csv"
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n✅ Done! Saved: {csv_filename}  ({len(all_results)} rows)")
