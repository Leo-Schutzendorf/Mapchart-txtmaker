from flask import Flask, jsonify, render_template, Response, request
import json
import threading
import queue
import time

app = Flask(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────
# Keyed by (year, otherAsDem, otherAsRep) so different reassignment modes are
# cached separately.  To add a new per-run option, add it to the cache key here
# and pass it through the stream endpoint below.
results_cache = {}


# ─── Scraper ──────────────────────────────────────────────────────────────────
# otherAsDem / otherAsRep: when True, all non-D/R votes are folded into that
# party's total before deciding a county winner.
# To add a new reassignment mode (e.g. a specific third party), add a parameter
# here, thread it through the vote_map block (~line 277), and expose it in the
# /api/stream endpoint below.
def run_scraper(year, progress_queue, otherAsDem=False, otherAsRep=False):
    """Run the scraper for a given year, sending progress updates to the queue."""
    import requests as req
    import re
    from bs4 import BeautifulSoup

    try:
        from namechanges import namechanges
    except ImportError:
        def namechanges(name, state, year):
            return name

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
        "California": "CA", "Colorado": "CO", "Connecticut": "CT",
        "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
        "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
        "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
        "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
        "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
        "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
        "New_Hampshire": "NH", "New_Jersey": "NJ", "New_Mexico": "NM",
        "New_York": "NY", "North_Carolina": "NC", "North_Dakota": "ND",
        "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
        "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC",
        "South_Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington_(state)": "WA",
        "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
    }

    COUNTY_KEYWORDS = [
        "County", "Council of Government", "Parish", "Borough",
        "Census area", "District", "City and county", "Municipality"
    ]

    # ── Vote-bucket lists ──────────────────────────────────────────────────────
    # Each list collects MapChart path IDs for counties in that result range.
    # To add a new named third-party candidate, add seven lists here (one per
    # 10-point bucket), add them to bucket_county's `buckets` dict, and add
    # them to the final `output` dict at the bottom of this function.
    Republican_30_40 = []; Democrat_30_40 = []
    Republican_40_50 = []; Democrat_40_50 = []
    Republican_50_60 = []; Democrat_50_60 = []
    Republican_60_70 = []; Democrat_60_70 = []
    Republican_70_80 = []; Democrat_70_80 = []
    Republican_80_90 = []; Democrat_80_90 = []
    Republican_90_100 = []; Democrat_90_100 = []

    Perot_30_40 = []; Perot_40_50 = []; Perot_50_60 = []
    Perot_60_70 = []; Perot_70_80 = []; Perot_80_90 = []; Perot_90_100 = []
    Wallace_30_40 = []; Wallace_40_50 = []; Wallace_50_60 = []
    Wallace_60_70 = []; Wallace_70_80 = []; Wallace_80_90 = []; Wallace_90_100 = []
    Unpledged_30_40 = []; Unpledged_40_50 = []; Unpledged_50_60 = []
    Unpledged_60_70 = []; Unpledged_70_80 = []; Unpledged_80_90 = []; Unpledged_90_100 = []

    # Generic "Other" bucket (everything that isn't R/D/Wallace/Unpledged/Perot)
    Other_30_40 = []; Other_40_50 = []; Other_50_60 = []
    Other_60_70 = []; Other_70_80 = []; Other_80_90 = []; Other_90_100 = []

    tie = []

    # ── Helpers ────────────────────────────────────────────────────────────────

    def make_path_id(county_name, state_code):
        name = county_name.strip()
        name = name.replace("'", "_")
        name = name.replace("-", " ")
        name = re.sub(r'\s+', ' ', name)
        name = name.replace(" ", "_")
        name = name.replace("St._", "St__")
        return f"{name}__{state_code}"

    def find_county_table(soup, state, year):
        all_tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)
        if state == "Connecticut" and int(year) >= 2024:
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
        # Maps a column header string → a party label used for column lookup.
        # To recognise a new third-party candidate, add an elif branch here and
        # return an appropriate label string (also add it to parse_column_positions).
        t = text.lower()
        if flat_col == 0 and 'county' not in t and 'parish' not in t:
            return 'County'
        if 'repub' in t: return 'Republican'
        if 'democ' in t or 'dfl' in t: return 'Democrat'
        if 'margin' in t: return 'Margin'
        if 'total' in t: return 'Total'
        if flat_col == 0: return 'County'
        if 'wallace' in t or 'american independent' in t: return 'Wallace'
        if 'unpledged' in t or "states' rights" in t or 'states rights' in t: return 'Unpledged'
        if 'perot' in t or ('reform' in t and 'party' in t): return 'Perot'
        return 'Other'

    def parse_column_positions(table):
        header_rows = []
        for tr in table.find_all('tr'):
            ths = tr.find_all('th')
            if ths: header_rows.append(ths)
            else: break
        if not header_rows:
            return {k: None for k in ['rep_votes','rep_pct','dem_votes','dem_pct',
                                       'other_votes','other_pct','wallace_votes','wallace_pct',
                                       'unpledged_votes','unpledged_pct','perot_votes','perot_pct']}
        PARTY_HINTS = ["republican","democrat","democratic","dfl","whig","american","reform",
                       "independent","libertarian","green","democ","repub","wallace","unpledged","perot"]
        label_row_idx = 0
        for i, row in enumerate(header_rows):
            joined = " ".join(th.get_text(strip=True) for th in row).lower()
            if any(h in joined for h in PARTY_HINTS):
                label_row_idx = i; break
        label_row = header_rows[label_row_idx]
        flat_col = 0; col_party = {}
        for th in label_row:
            text = th.get_text(strip=True)
            colspan = int(th.get('colspan', 1))
            label = classify_header(text, flat_col)
            for i in range(colspan): col_party[flat_col + i] = label
            flat_col += colspan
        rep_cols       = [k for k,v in sorted(col_party.items()) if v == 'Republican']
        dem_cols       = [k for k,v in sorted(col_party.items()) if v == 'Democrat']
        other_cols     = [k for k,v in sorted(col_party.items()) if v == 'Other']
        wallace_cols   = [k for k,v in sorted(col_party.items()) if v == 'Wallace']
        unpledged_cols = [k for k,v in sorted(col_party.items()) if v == 'Unpledged']
        perot_cols     = [k for k,v in sorted(col_party.items()) if v == 'Perot']
        pct_first = False
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if not tds: continue
            row = [td.get_text(strip=True) for td in tds]
            if rep_cols and len(row) > rep_cols[0]:
                val = row[rep_cols[0]].replace('%','').replace(',','').strip()
                try:
                    f = float(val)
                    if f < 100 and '.' in row[rep_cols[0]]: pct_first = True
                except ValueError: pass
            break
        def pick(cols, vi, pi):
            return (cols[vi] if len(cols) > vi else None,
                    cols[pi] if len(cols) > pi else None)
        if pct_first:
            rv,rp = pick(rep_cols,1,0); dv,dp = pick(dem_cols,1,0)
            ov,op = pick(other_cols,1,0); wv,wp = pick(wallace_cols,1,0)
            uv,up = pick(unpledged_cols,1,0); pv,pp = pick(perot_cols,1,0)
        else:
            rv,rp = pick(rep_cols,0,1); dv,dp = pick(dem_cols,0,1)
            ov,op = pick(other_cols,0,1); wv,wp = pick(wallace_cols,0,1)
            uv,up = pick(unpledged_cols,0,1); pv,pp = pick(perot_cols,0,1)
        return {'rep_votes':rv,'rep_pct':rp,'dem_votes':dv,'dem_pct':dp,
                'other_votes':ov,'other_pct':op,'wallace_votes':wv,'wallace_pct':wp,
                'unpledged_votes':uv,'unpledged_pct':up,'perot_votes':pv,'perot_pct':pp}

    def safe_int(s):
        try: return int(s.replace(',','').replace('\xa0','').replace('+','').strip())
        except: return 0

    def safe_float(s):
        try: return float(s.replace('%','').replace('\xa0','').replace('+','').strip())
        except: return 0.0

    def bucket_county(path_id, pct, party):
        # Places a county path ID into the correct 10-point bucket for its party.
        # To add a new named party, add it to the `buckets` dict here (pointing
        # to its seven bucket lists) and create those lists above.
        ranges = [(30,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,101,6)]
        buckets = {
            'Republican': [Republican_30_40,Republican_40_50,Republican_50_60,Republican_60_70,
                           Republican_70_80,Republican_80_90,Republican_90_100],
            'Democrat':   [Democrat_30_40,Democrat_40_50,Democrat_50_60,Democrat_60_70,
                           Democrat_70_80,Democrat_80_90,Democrat_90_100],
            'Other':      [Other_30_40,Other_40_50,Other_50_60,Other_60_70,
                           Other_70_80,Other_80_90,Other_90_100],
            'Wallace':    [Wallace_30_40,Wallace_40_50,Wallace_50_60,Wallace_60_70,
                           Wallace_70_80,Wallace_80_90,Wallace_90_100],
            'Unpledged':  [Unpledged_30_40,Unpledged_40_50,Unpledged_50_60,Unpledged_60_70,
                           Unpledged_70_80,Unpledged_80_90,Unpledged_90_100],
            'Perot':      [Perot_30_40,Perot_40_50,Perot_50_60,Perot_60_70,
                           Perot_70_80,Perot_80_90,Perot_90_100],
            'Tie':        [tie,tie,tie,tie,tie,tie,tie],
        }
        for lo,hi,idx in ranges:
            if lo <= pct < hi:
                buckets[party][idx].append(path_id)
                return

    req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # ── Main scraping loop ─────────────────────────────────────────────────────
    # Iterates every state, fetches its Wikipedia page, finds the county table,
    # and buckets each county by winning party + vote percentage.
    # To skip or specially handle a state, add a conditional before the main
    # county loop (see the Alaska early-continue below as an example).
    for i, state in enumerate(states):
        display_name = state.replace('_', ' ')
        progress_queue.put({"type": "progress", "state": display_name,
                            "index": i + 1, "total": len(states)})

        url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_{state}"
        try:
            response = req.get(url, headers=req_headers, timeout=15)
            soup = BeautifulSoup(response.content, "html.parser")
        except Exception as e:
            progress_queue.put({"type": "warning", "message": f"Network error for {display_name}: {e}"})
            continue

        table = find_county_table(soup, state, year)
        if table is None:
            progress_queue.put({"type": "warning", "message": f"No county table found for {display_name}"})
            continue

        cols = parse_column_positions(table)

        if state == "Alaska" and int(year) < 2024:
            progress_queue.put({"type": "warning", "message": "Alaska: no borough results before 2024"})
            continue
        if cols['rep_votes'] is None or cols['dem_votes'] is None:
            progress_queue.put({"type": "warning", "message": f"Could not identify columns for {display_name}"})
            continue

        needed_cols = [c for c in [cols['rep_pct'],cols['dem_pct'],cols['other_pct'],
                                    cols['wallace_pct'],cols['unpledged_pct'],cols['perot_pct']] if c is not None]
        max_col = max(needed_cols) if needed_cols else 0
        state_code = postalCodes[state]

        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if not tds: continue
            row = [td.get_text(strip=True) for td in tds]
            if not row[0] or row[0].lower() in ('total','totals'): continue
            if len(row) <= max_col: continue

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
            total_votes = rep_votes + dem_votes + other_votes + wallace_votes + unpledged_votes + perot_votes

            # ── Vote map (default: show each party separately) ─────────────────
            # vote_map[party] = (vote_count, percentage)
            # The winning party is the one with the highest vote_count.
            # To add a new named third party here, include it in the default map
            # and handle its reassignment in the two if-blocks below.
            vote_map = {
                'Republican': (rep_votes,       rep_pct),
                'Democrat':   (dem_votes,       dem_pct),
                'Other':      (other_votes,     other_pct),
                'Wallace':    (wallace_votes,   wallace_pct),
                'Unpledged':  (unpledged_votes, unpledged_pct),
                'Perot':      (perot_votes,     perot_pct),
            }

            # ── Reassignment: all non-R/D votes → Democrat ─────────────────────
            # When otherAsDem is True we collapse every third-party vote into
            # the Democratic column.  The Democrat vote total becomes
            # (total - Republican), and the Republican column is unchanged.
            # To reassign only a specific party (e.g. only Perot → Dem), replace
            # (total_votes - rep_votes) with (dem_votes + perot_votes) and adjust
            # the percentage accordingly.
            if otherAsDem:
                dem_reassigned = total_votes - rep_votes
                # Compute pct from vote counts so Wikipedia rounding errors
                # cannot push the winner below 50%.
                dem_reassigned_pct = (dem_reassigned / total_votes * 100.0) if total_votes else 0.0
                vote_map = {
                    'Republican': (rep_votes,          rep_pct),
                    'Democrat':   (dem_reassigned,     dem_reassigned_pct),
                }

            # ── Reassignment: all non-R/D votes → Republican ───────────────────
            # Mirror of the above: every third-party vote folds into Republican.
            if otherAsRep:
                rep_reassigned = total_votes - dem_votes
                rep_reassigned_pct = (rep_reassigned / total_votes * 100.0) if total_votes else 0.0
                dem_pct_recalc = (dem_votes / total_votes * 100.0) if total_votes else 0.0
                vote_map = {
                    'Republican': (rep_reassigned,  rep_reassigned_pct),
                    'Democrat':   (dem_votes,        dem_pct_recalc),
                }

            best_party = max(vote_map, key=lambda p: vote_map[p][0])
            best_votes = vote_map[best_party][0]
            tied = [p for p,(v,_) in vote_map.items() if v == best_votes and best_votes > 0]
            if len(tied) > 1:
                winner, winner_pct = 'Tie', max(vote_map[p][1] for p in tied)
            else:
                winner, winner_pct = best_party, vote_map[best_party][1]

            countyName = namechanges(row[0], state, year)
            path_id = make_path_id(countyName, state_code)
            bucket_county(path_id, winner_pct, winner)

            # ── County split / merge special cases ────────────────────────────
            # Some counties were created or dissolved mid-century.  When the
            # source table only lists the parent, we copy its result to the child.
            # To add more, follow the same pattern: check state + county + year.
            if state == "Arizona" and countyName == "Yuma" and int(year) < 1984:
                bucket_county(make_path_id("La_Paz", state_code), winner_pct, winner)
            if state == "New_Mexico" and countyName == "Valencia" and int(year) < 1984:
                bucket_county(make_path_id("Cibola", state_code), winner_pct, winner)
            if state == "Virginia" and countyName == "York" and int(year) < 1976:
                bucket_county(make_path_id("Poquoson", state_code), winner_pct, winner)

        # ── DC special case ────────────────────────────────────────────────────
        # DC has no counties so it's not in the state loop; we handle it after
        # Delaware (alphabetically adjacent).  It always goes to Democrat.
        # To add other non-state territories (PR, GU…), follow the same pattern.
        if state == "Delaware":
            try:
                dc_url = f"https://en.wikipedia.org/wiki/{year}_United_States_presidential_election_in_the_District_of_Columbia"
                dc_resp = req.get(dc_url, headers=req_headers, timeout=15)
                dc_soup = BeautifulSoup(dc_resp.content, "html.parser")
                infobox = dc_soup.find('table', class_='infobox')
                dc_winner_pct = 0.0
                dc_republican_pct = 0.0
                if infobox:
                    for r in infobox.find_all('tr'):
                        if "Percentage" in r.get_text():
                            nums = re.findall(r'\d+\.\d+', r.get_text(strip=True))
                            if nums:
                                dc_winner_pct    = float(nums[0])
                                # Republicans never win DC but we need their share
                                # to compute the "other reassigned" percentage.
                                dc_republican_pct = float(nums[1]) if len(nums) > 1 else 0.0
                            break

                # If otherAsDem, treat all non-Republican DC votes as Democrat.
                # DC infobox only has percentages (no raw counts), so we use
                # 100 - republican_pct.  Clamp to [0,100] against rounding edge cases.
                if otherAsDem:
                    dc_winner_pct = max(0.0, min(100.0 - dc_republican_pct, 100.0))
                bucket_county(make_path_id("Washington", "DC"), dc_winner_pct, "Democrat")

            except Exception as e:
                progress_queue.put({"type": "warning", "message": f"DC error: {e}"})

    # ── Build final MapChart JSON output ───────────────────────────────────────
    # Each key is a hex colour used by MapChart; `paths` is the list of county
    # IDs that won at that shade.  To add a new named party, add seven entries
    # here (one per 10-point bucket) pointing to its seven bucket lists.
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

    progress_queue.put({"type": "done", "data": output})


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/results")
def results():
    """Check whether a cached result exists for this year + reassignment mode."""
    year       = request.args.get("year", "").strip()
    other_mode = request.args.get("otherMode", "none")  # "dem", "rep", or "none"

    if not year.isdigit() or not (1788 <= int(year) <= 2100):
        return jsonify({"error": "Invalid year"}), 400

    # Cache key includes reassignment mode so "1992 + otherAsDem" is stored
    # separately from plain "1992".  To add more modes, extend this key.
    cache_key = (year, other_mode)
    if cache_key in results_cache:
        return jsonify({"status": "cached", "data": results_cache[cache_key]})

    return jsonify({"status": "use_stream"}), 202


@app.route("/api/stream")
def stream():
    """Server-Sent Events endpoint — streams progress updates then final data.

    Query parameters:
      year      – four-digit election year (required)
      otherMode – how to handle non-R/D votes:
                    "dem"  → otherAsDem=True  (all third-party → Democrat)
                    "rep"  → otherAsRep=True  (all third-party → Republican)
                    "none" → show third parties separately (default)

    To add a new reassignment option:
      1. Add a new otherMode string here (e.g. "dem_only_perot")
      2. Pass a new boolean to run_scraper()
      3. Handle it in run_scraper's vote_map block
    """
    year       = request.args.get("year", "").strip()
    other_mode = request.args.get("otherMode", "none")

    if not year.isdigit() or not (1788 <= int(year) <= 2100):
        def err():
            yield "data: " + json.dumps({"type": "error", "message": "Invalid year"}) + "\n\n"
        return Response(err(), mimetype="text/event-stream")

    cache_key = (year, other_mode)

    if cache_key in results_cache:
        def cached():
            yield "data: " + json.dumps({"type": "done", "data": results_cache[cache_key]}) + "\n\n"
        return Response(cached(), mimetype="text/event-stream")

    # Translate otherMode string → boolean flags for run_scraper
    otherAsDem = (other_mode == "dem")
    otherAsRep = (other_mode == "rep")

    progress_queue = queue.Queue()

    def scrape_thread():
        run_scraper(year, progress_queue, otherAsDem=otherAsDem, otherAsRep=otherAsRep)

    thread = threading.Thread(target=scrape_thread, daemon=True)
    thread.start()

    def event_stream():
        while True:
            try:
                msg = progress_queue.get(timeout=60)
                if msg["type"] == "done":
                    results_cache[cache_key] = msg["data"]
                yield "data: " + json.dumps(msg) + "\n\n"
                if msg["type"] in ("done", "error"):
                    break
            except queue.Empty:
                yield "data: " + json.dumps({"type": "heartbeat"}) + "\n\n"

    return Response(event_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True)