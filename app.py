from flask import Flask, jsonify, render_template, Response, request, send_file
import json
import threading
import queue
import time
import csv
import os
import math
app = Flask(__name__)
import specialRegions

# ─── Paths ────────────────────────────────────────────────────────────────────
# All CSV / JSON files live next to this script, regardless of which directory
# Python is invoked from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Cache ────────────────────────────────────────────────────────────────────
# Keyed by (year, otherAsDem, otherAsRep) so different other reassignment modes are
# cached separately.  To add a new per-run option, add it to the cache key here
# and pass it through the stream endpoint below.
results_cache = {}


# ─── CSV-based data loader ────────────────────────────────────────────────────
# Reads pre-scraped results from a local CSV instead of hitting Wikipedia.
# The CSV must have these columns:
#   County__State_Code, Republican_Votes, Republican_Pct,
#   Democrat_Votes, Democrat_Pct, Other_Votes, Other_Pct, Total_Votes
#
# otherAsDem / otherAsRep: when True, all non-D/R votes are folded into that
# party's total before deciding a county winner.
#
# year == "0" is the special user-uploaded data mode.  After applying all
# shifts the function writes the shifted results back out to 0results.csv so
# the user can download or re-use them.

def run_scraper(year, progress_queue, otherAsDem=False, otherAsRep=False, state_shifts=None, region_shifts=None, switchColors=False):
    """Load county results from the local CSV and bucket them for MapChart.

    state_shifts: dict mapping state name (e.g. "Alabama") to a signed integer
    shift amount (-100..+100).  Positive = shift toward Republican, negative =
    shift toward Democrat.  Applied to each county's raw Dem/Rep percentages
    after normal bucketing; the county is removed from its original bucket and
    re-inserted into the correct shifted one.
    """
    import pandas as pd
    if state_shifts is None:
        state_shifts = {}
    if region_shifts is None:
        region_shifts = {}

    # Switch party colors; Democrats are now red and Republicans blue
    # (controlled by the switchColors parameter passed in from the request)

    # ── Vote-bucket lists ──────────────────────────────────────────────────────
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
    Other_30_40 = []; Other_40_50 = []; Other_50_60 = []
    Other_60_70 = []; Other_70_80 = []; Other_80_90 = []; Other_90_100 = []

    tie = []

    def bucket_county(path_id, pct, party, dem_pct=None, rep_pct=None):
        ranges = [(0,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,101,6)]
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

        if otherAsRep or otherAsDem:
            # Recalculate winner using redistributed votes
            r = float(rep_pct) if rep_pct is not None else 0.0
            d = float(dem_pct) if dem_pct is not None else 0.0

            if otherAsRep:
                # All non-Dem votes go to Republican
                new_rep = 100.0 - d
                new_dem = d
            else:  # otherAsDem
                # All non-Rep votes go to Democrat
                new_dem = 100.0 - r
                new_rep = r

            if new_rep > new_dem:
                eff_party, eff_pct = 'Republican', new_rep
            elif new_dem > new_rep:
                eff_party, eff_pct = 'Democrat', new_dem
            else:
                tie.append(path_id)
                return
        else:
            eff_party, eff_pct = party, float(pct)

        for lo, hi, idx in ranges:
            if lo <= int(eff_pct) < hi:
                buckets[eff_party][idx].append(path_id)
                return


    # ── Load CSV ───────────────────────────────────────────────────────────────
    CSV_PATH = os.path.join(BASE_DIR, str(year) + 'results.csv')
    try:
        pd.read_csv(CSV_PATH)  # quick existence/parse check
    except FileNotFoundError:
        progress_queue.put({"type": "error", "message": f"CSV not found: {CSV_PATH}"})
        return

    postalCodes = {
        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
        "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
        "District_of_Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
        "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
        "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
        "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
        "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
        "New_Hampshire": "NH", "New_Jersey": "NJ", "New_Mexico": "NM", "New_York": "NY",
        "North_Carolina": "NC", "North_Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
        "Oregon": "OR", "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC",
        "South_Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington_state": "WA",
        "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"
    }

    with open(CSV_PATH, mode='r', encoding="utf-8") as file:
        reader = csv.DictReader(file)
        # fieldnames must be captured after DictReader reads the header row.
        # Accessing reader.fieldnames triggers the header read before list().
        fieldnames = reader.fieldnames
        rows = list(reader)

    # ── Bucket every county from the CSV ──────────────────────────────────────
    # Reads County__State_Code, Winner, and Winner_Pct columns by name
    # so column order doesn't matter and the header row is skipped automatically.
    for county in rows:
        bucket_county(
            county['County__State_Code'],
            county['Winner_Pct'],
            county['Winner'],
            dem_pct=county.get('Democrat_Pct'),
            rep_pct=county.get('Republican_Pct'),
        )

        """For counties that didn't exist yet, use the county it was part of."""
        if str(year) != "0":
            if county['County__State_Code']=="Yuma__AZ" and int(year)<1984:
                bucket_county("La_Paz__AZ", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
                
            if county['County__State_Code']=="Maui__HI" and int(year)<1992:
                bucket_county("Kalawao__HI", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
                
            if county['County__State_Code']=="Valencia__NM" and int(year)<1984:
                bucket_county("Cibola__NM", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))

            """Virginia has a lot of these"""
            if county['County__State_Code']=="Prince_William__VA" and int(year)<1976:
                bucket_county("Manassas__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
                bucket_county("Manassas_Park__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
            if county['County__State_Code']=="York__VA" and int(year)<1976:
                bucket_county("Poquoson__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
            if county['County__State_Code']=="Roanoke_Co___VA" and int(year)<1968:
                bucket_county("Salem__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
            if county['County__State_Code']=="Rockbridge__VA" and int(year)<1968:
                bucket_county("Lexington__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))
            if county['County__State_Code']=="Rockbridge__VA" and int(year)<1964:
                bucket_county("Chesapeake__VA", county['Winner_Pct'], county['Winner'],
                              dem_pct=county.get('Democrat_Pct'), rep_pct=county.get('Republican_Pct'))

    # ── Track per-county shifts for CSV output ─────────────────────────────────
    # This dict is populated by whichever shift block runs below, then used
    # at the end to write 0results.csv (only when year == "0").
    county_shifts_applied = {}  # code -> shift amount actually used

    # ── Apply state-level shifts ───────────────────────────────────────────────
    # For each shifted state, re-derive winner+pct for every county in that
    # state from the raw Dem/Rep vote percentages, then move the county to the
    # correct new bucket.  The shift is a signed percentage-point offset applied
    # to the two-party split:
    #   new_dem = dem_pct - shift   (positive shift → less Dem)
    #   new_rep = rep_pct + shift   (positive shift → more Rep)
    # Both are clamped so neither drops below 0 or exceeds 100.
    if state_shifts:
        # Build all bucket lists in order so we can search/remove by value
        all_buckets = {
            'Republican': [Republican_30_40, Republican_40_50, Republican_50_60,
                           Republican_60_70, Republican_70_80, Republican_80_90,
                           Republican_90_100],
            'Democrat':   [Democrat_30_40, Democrat_40_50, Democrat_50_60,
                           Democrat_60_70, Democrat_70_80, Democrat_80_90,
                           Democrat_90_100],
        }
        bucket_ranges = [(30,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,69420,6)]

        # Index rows by County__State_Code for fast lookup
        row_by_code = {r['County__State_Code']: r for r in rows}

        for state_name, shift in state_shifts.items():
            if shift == 0:
                continue
            # Find all counties belonging to this state (suffix = "__" + postal code)
            state_prefix = postalCodes.get(state_name)
            if not state_prefix:
                continue

            for code, row in row_by_code.items():
                if not code.endswith('__' + state_prefix):
                    continue

                try:
                    dem_pct = float(row.get('Democrat_Pct') or 0)
                    rep_pct = float(row.get('Republican_Pct') or 0)
                except (ValueError, TypeError):
                    continue

                # Apply shift to the raw two-party split.
                # shift > 0 → more Republican; shift < 0 → more Democrat.
                new_dem_pct = max(0.0, dem_pct - shift)
                new_rep_pct = max(0.0, rep_pct + shift)

                # Clamp so neither exceeds 100
                if new_rep_pct > 100:
                    new_rep_pct = 100.0
                    new_dem_pct = 0.0
                if new_dem_pct > 100:
                    new_dem_pct = 100.0
                    new_rep_pct = 0.0

                # Apply other-vote redistribution on top of the shifted values.
                if otherAsRep:
                    new_rep_pct = 100.0 - new_dem_pct
                elif otherAsDem:
                    new_dem_pct = 100.0 - new_rep_pct

                # Determine new winner and winning pct
                if new_rep_pct > new_dem_pct:
                    new_winner = 'Republican'
                    new_pct = new_rep_pct
                elif new_dem_pct > new_rep_pct:
                    new_winner = 'Democrat'
                    new_pct = new_dem_pct
                else:
                    # Exact tie — leave in tie bucket (don't move)
                    continue

                # Track the shift for CSV output
                county_shifts_applied[code] = shift

                # Remove county from whichever bucket it's currently in
                for party_buckets in all_buckets.values():
                    for b in party_buckets:
                        if code in b:
                            b.remove(code)

                # Also check tie list
                if code in tie:
                    tie.remove(code)

                # Insert into the correct new bucket
                for lo, hi, idx in bucket_ranges:
                    if lo <= new_pct < hi:
                        all_buckets[new_winner][idx].append(code)
                        break
                else:
                    # 100% edge case — put in the top bucket
                    all_buckets[new_winner][6].append(code)

    elif region_shifts:
        # ── Apply region-level shifts ──────────────────────────────────────────
        # Runs after state shifts with an elif so both cannot be active
        # simultaneously (combining them would cause difficult-to-track bugs).
        # Uses the county lists from specialRegions.py to find which counties
        # belong to each region, then re-buckets them like the state-shift logic.
        import specialRegions as _sr
        import inspect as _inspect

        # Build region_name -> [county_codes] from specialRegions module
        region_counties = {
            name: val
            for name, val in _inspect.getmembers(_sr)
            if isinstance(val, list) and not name.startswith('_')
        }

        # Build reverse lookup: county_code -> total shift (summed across all regions it's in)
        county_region_shift: dict = {}
        for region_name, shift in region_shifts.items():
            if shift == 0:
                continue
            counties = region_counties.get(region_name, [])
            for code in counties:
                county_region_shift[code] = county_region_shift.get(code, 0) + shift

        if county_region_shift:
            all_buckets_r = {
                'Republican': [Republican_30_40, Republican_40_50, Republican_50_60,
                               Republican_60_70, Republican_70_80, Republican_80_90,
                               Republican_90_100],
                'Democrat':   [Democrat_30_40, Democrat_40_50, Democrat_50_60,
                               Democrat_60_70, Democrat_70_80, Democrat_80_90,
                               Democrat_90_100],
            }
            bucket_ranges_r = [(30,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,101,6)]
            row_by_code_r = {r['County__State_Code']: r for r in rows}

            for code, shift in county_region_shift.items():
                row = row_by_code_r.get(code)
                if row is None:
                    continue

                try:
                    dem_pct = float(row.get('Democrat_Pct') or 0)
                    rep_pct = float(row.get('Republican_Pct') or 0)
                except (ValueError, TypeError):
                    continue

                new_dem_pct = max(0.0, dem_pct - shift)
                new_rep_pct = max(0.0, rep_pct + shift)

                if new_rep_pct > 100:
                    new_rep_pct = 100.0; new_dem_pct = 0.0
                if new_dem_pct > 100:
                    new_dem_pct = 100.0; new_rep_pct = 0.0

                if otherAsRep:
                    new_rep_pct = 100.0 - new_dem_pct
                elif otherAsDem:
                    new_dem_pct = 100.0 - new_rep_pct

                if new_rep_pct > new_dem_pct:
                    new_winner, new_pct = 'Republican', new_rep_pct
                elif new_dem_pct > new_rep_pct:
                    new_winner, new_pct = 'Democrat', new_dem_pct
                else:
                    continue  # tie — leave as-is

                # Track the shift for CSV output
                county_shifts_applied[code] = shift

                # Remove from current bucket
                for party_buckets in all_buckets_r.values():
                    for b in party_buckets:
                        if code in b:
                            b.remove(code)
                if code in tie:
                    tie.remove(code)

                # Insert into new bucket
                for lo, hi, idx in bucket_ranges_r:
                    if lo <= new_pct < hi:
                        all_buckets_r[new_winner][idx].append(code)
                        break
                else:
                    all_buckets_r[new_winner][6].append(code)

    # ── Write newresults.csv ──────────
    # All original columns are preserved; Democrat_Pct, Republican_Pct,
    # Winner, and Winner_Pct are recalculated to reflect any applied
    # state/region shifts AND otherAsDem/otherAsRep reassignment.
    # Must create this csv every time
    with open(os.path.join(BASE_DIR, "newresults.csv"), 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            code    = row['County__State_Code']
            out_row = dict(row)  # copy all original columns
            try:
                dem_pct = float(row.get('Democrat_Pct') or 0)
                rep_pct = float(row.get('Republican_Pct') or 0)
                total_votes = int(row.get("Total_Votes") or 0)
            except (ValueError, TypeError):
                writer.writerow(out_row)
                continue

            # 1. Apply any state/region shift for this county
            shift   = county_shifts_applied.get(code, 0)
            new_dem_pct = max(0.0, min(100.0, dem_pct - shift))
            new_rep_pct = max(0.0, min(100.0, rep_pct + shift))

            new_dem = max(0.0, min(total_votes, int(0.01*new_dem_pct*total_votes)))
            new_rep = max(0.0, min(total_votes, int(0.01*new_rep_pct*total_votes)))

            # 2. Apply other-vote reassignment on top of the shift
            if otherAsRep or otherAsDem:
                try:
                    other_pct = float(row.get('Other_Pct') or 0)
                except (ValueError, TypeError):
                    other_pct = 0.0

                # new_party_pct = max(0,100-new_otherParty_pct)
                if otherAsRep:
                    new_rep_pct = max(0, 100.0 - new_dem_pct)
                elif otherAsDem:
                    new_dem_pct = max(0, 100.0 - new_rep_pct)

                # Recalculate raw vote totals from the updated percentages
                new_dem = round(0.01 * new_dem_pct * total_votes)
                new_rep = round(0.01 * new_rep_pct * total_votes)

                # Zero out other columns in the output row (only if present in CSV)
                keep = {'County__State_Code', 'Total_Votes', 'Winner', 'Winner_Pct',
                        'Democrat_Votes', 'Democrat_Pct', 'Republican_Votes', 'Republican_Pct'}
                for field in fieldnames:
                    if field not in keep:
                        if 'Votes' in field:
                            out_row[field] = 0
                        elif 'Pct' in field:
                            out_row[field] = 0.0

            # 3. Derive winner from the final values
            if new_rep_pct > new_dem_pct:
                new_winner, new_pct = 'Republican', new_rep_pct
            elif new_dem_pct > new_rep_pct:
                new_winner, new_pct = 'Democrat', new_dem_pct
            else:
                new_winner = out_row['Winner']
                new_pct    = float(out_row['Winner_Pct'])

            out_row['Democrat_Votes']   = int(new_dem)
            out_row['Republican_Votes'] = int(new_rep)
            out_row['Democrat_Pct']     = round(new_dem_pct, 4)
            out_row['Republican_Pct']   = round(new_rep_pct, 4)
            out_row['Winner']           = new_winner
            out_row['Winner_Pct']       = round(new_pct, 4)

            writer.writerow(out_row)
    # ── Write StateLevel.json ─────────────────────────────────────────────────
    # Aggregates county-level results up to the state level and writes a
    # YAPms-format JSON file that can be loaded into yapms.com.
    #
    # The winner of each state is whichever party accumulated the most raw votes
    # across all its counties (after any shifts/reassignments are applied).
    # Third-party candidates (Other, Wallace, Perot, Unpledged) are fully
    # supported: if a third party wins the state vote total it appears as the
    # winner, and a matching candidate entry is added to the candidates array.
    #
    # Margin tier is based on the winner's share of the *total* state vote
    # (not just the two-party split) so it reflects genuine dominance:
    #   0 = Safe      (winner ≥ 60 % of total)
    #   1 = Likely    (55–60 %)
    #   2 = Lean      (52–55 %)
    #   3 = Toss-up   (< 52 %, or any state won by a third party)

    import uuid as _uuid

    # ── Electoral-vote counts by year and YAPms region id ─────────────────────
    # Each sub-dict must exactly match what YAPms stores internally for that
    # year's "results" map — if value/count don't match the built-in permaVal,
    # YAPms treats the difference as unassigned and creates ghost electors.
    # ME/NE district splits (me-01, me-02, ne-01…ne-03) only exist from 1972+;
    # DC (dc) only from 1964+.  Earlier years omit those keys entirely.
    # Source: official NARA/FEC apportionment records.
    EV_BY_YEAR = {
        1948: {
            "al":11,"az":4, "ar":9, "ca":25,"co":6, "ct":8, "de":3,
            "fl":8, "ga":12,"id":4, "il":28,"in":13,"ia":10,"ks":8,
            "ky":11,"la":10,"me-al":5,"md":8, "ma":16,"mi":19,"mn":11,
            "ms":9, "mo":15,"mt":4, "nv":3, "nh":4, "nj":16,"nm":4,
            "ny":47,"nc":14,"nd":4, "oh":25,"ok":10,"or":6, "pa":35,
            "ri":4, "sc":8, "sd":4, "tn":12,"tx":23,"ut":4, "vt":3,
            "va":11,"wa":8, "wv":8, "wi":12,"wy":3,
        },
        1952: {
            "al":11,"ak":0, "az":4, "ar":8, "ca":32,"co":6, "ct":8,
            "de":3, "fl":10,"ga":12,"hi":0, "id":4, "il":27,"in":13,
            "ia":10,"ks":8, "ky":10,"la":10,"me-al":5,"md":9, "ma":16,
            "mi":20,"mn":11,"ms":8, "mo":13,"mt":4, "nv":3, "nh":4,
            "nj":16,"nm":4, "ny":45,"nc":14,"nd":4, "oh":25,"ok":8,
            "or":6, "pa":32,"ri":4, "sc":8, "sd":4, "tn":11,"tx":24,
            "ut":4, "vt":3, "va":12,"wa":9, "wv":8, "wi":12,"wy":3,
        },
        1956: {
            "al":11,"ak":0, "az":4, "ar":8, "ca":32,"co":6, "ct":8,
            "de":3, "fl":10,"ga":12,"hi":0, "id":4, "il":27,"in":13,
            "ia":10,"ks":8, "ky":10,"la":10,"me-al":5,"md":9, "ma":16,
            "mi":20,"mn":11,"ms":8, "mo":13,"mt":4, "nv":3, "nh":4,
            "nj":16,"nm":4, "ny":45,"nc":14,"nd":4, "oh":25,"ok":8,
            "or":6, "pa":32,"ri":4, "sc":8, "sd":4, "tn":11,"tx":24,
            "ut":4, "vt":3, "va":12,"wa":9, "wv":8, "wi":12,"wy":3,
        },
        1960: {
            "al":11,"ak":3, "az":4, "ar":8, "ca":32,"co":6, "ct":8,
            "de":3, "fl":10,"ga":12,"hi":3, "id":4, "il":27,"in":13,
            "ia":10,"ks":8, "ky":10,"la":10,"me-al":5,"md":9, "ma":16,
            "mi":20,"mn":11,"ms":8, "mo":13,"mt":4, "nv":3, "nh":4,
            "nj":16,"nm":4, "ny":45,"nc":14,"nd":4, "oh":25,"ok":8,
            "or":6, "pa":32,"ri":4, "sc":8, "sd":4, "tn":11,"tx":24,
            "ut":4, "vt":3, "va":12,"wa":9, "wv":8, "wi":12,"wy":3,
        },
        1964: {
            "al":10,"ak":3, "az":5, "ar":6, "ca":40,"co":6, "ct":8,
            "dc":3, "de":3, "fl":14,"ga":12,"hi":4, "id":4, "il":26,
            "in":13,"ia":9, "ks":7, "ky":9, "la":10,"me-al":4,"md":10,
            "ma":14,"mi":21,"mn":10,"ms":7, "mo":12,"mt":4, "nv":3,
            "nh":4, "nj":17,"nm":4, "ny":43,"nc":13,"nd":4, "oh":26,
            "ok":8, "or":6, "pa":29,"ri":4, "sc":8, "sd":4, "tn":11,
            "tx":25,"ut":4, "vt":3, "va":12,"wa":9, "wv":7, "wi":12,
            "wy":3,
        },
        1968: {
            "al":10,"ak":3, "az":5, "ar":6, "ca":40,"co":6, "ct":8,
            "dc":3, "de":3, "fl":14,"ga":12,"hi":4, "id":4, "il":26,
            "in":13,"ia":9, "ks":7, "ky":9, "la":10,"me-al":4,"md":10,
            "ma":14,"mi":21,"mn":10,"ms":7, "mo":12,"mt":4, "nv":3,
            "nh":4, "nj":17,"nm":4, "ny":43,"nc":13,"nd":4, "oh":26,
            "ok":8, "or":6, "pa":29,"ri":4, "sc":8, "sd":4, "tn":11,
            "tx":25,"ut":4, "vt":3, "va":12,"wa":9, "wv":7, "wi":12,
            "wy":3,
        },
        1972: {
            "al":9, "ak":3, "az":6, "ar":6, "ca":45,"co":7, "ct":8,
            "dc":3, "de":3, "fl":17,"ga":12,"hi":4, "id":4, "il":26,
            "in":13,"ia":8, "ks":7, "ky":9, "la":10,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":14,"mi":21,"mn":10,"ms":7, "mo":12,"mt":4,
            "nv":3, "nh":4, "nj":17,"nm":4, "ny":41,"nc":13,"nd":3,
            "oh":25,"ok":8, "or":6, "pa":27,"ri":4, "sc":8, "sd":4,
            "tn":10,"tx":26,"ut":4, "vt":3, "va":11,"wa":9, "wv":6,
            "wi":11,"wy":3,
        },
        1976: {
            "al":9, "ak":3, "az":6, "ar":6, "ca":45,"co":7, "ct":8,
            "dc":3, "de":3, "fl":17,"ga":12,"hi":4, "id":4, "il":26,
            "in":13,"ia":8, "ks":7, "ky":9, "la":10,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":14,"mi":21,"mn":10,"ms":7, "mo":12,"mt":4,
            "nv":3, "nh":4, "nj":17,"nm":4, "ny":41,"nc":13,"nd":3,
            "oh":25,"ok":8, "or":6, "pa":27,"ri":4, "sc":8, "sd":4,
            "tn":10,"tx":26,"ut":4, "vt":3, "va":11,"wa":9, "wv":6,
            "wi":11,"wy":3,
        },
        1980: {
            "al":9, "ak":3, "az":6, "ar":6, "ca":45,"co":7, "ct":8,
            "dc":3, "de":3, "fl":17,"ga":12,"hi":4, "id":4, "il":26,
            "in":13,"ia":8, "ks":7, "ky":9, "la":10,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":14,"mi":21,"mn":10,"ms":7, "mo":12,"mt":4,
            "nv":3, "nh":4, "nj":17,"nm":4, "ny":41,"nc":13,"nd":3,
            "oh":25,"ok":8, "or":6, "pa":27,"ri":4, "sc":8, "sd":4,
            "tn":10,"tx":26,"ut":4, "vt":3, "va":11,"wa":9, "wv":6,
            "wi":11,"wy":3,
        },
        1984: {
            "al":9, "ak":3, "az":7, "ar":6, "ca":47,"co":8, "ct":8,
            "dc":3, "de":3, "fl":21,"ga":12,"hi":4, "id":4, "il":24,
            "in":12,"ia":8, "ks":7, "ky":9, "la":10,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":13,"mi":20,"mn":10,"ms":7, "mo":11,"mt":4,
            "nv":4, "nh":4, "nj":16,"nm":5, "ny":36,"nc":13,"nd":3,
            "oh":23,"ok":8, "or":7, "pa":25,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":29,"ut":5, "vt":3, "va":12,"wa":10,"wv":6,
            "wi":11,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        1988: {
            "al":9, "ak":3, "az":7, "ar":6, "ca":47,"co":8, "ct":8,
            "dc":3, "de":3, "fl":21,"ga":12,"hi":4, "id":4, "il":24,
            "in":12,"ia":8, "ks":7, "ky":9, "la":10,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":13,"mi":20,"mn":10,"ms":7, "mo":11,"mt":4,
            "nv":4, "nh":4, "nj":16,"nm":5, "ny":36,"nc":13,"nd":3,
            "oh":23,"ok":8, "or":7, "pa":25,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":29,"ut":5, "vt":3, "va":12,"wa":10,"wv":6,
            "wi":11,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        1992: {
            "al":9, "ak":3, "az":8, "ar":6, "ca":54,"co":8, "ct":8,
            "dc":3, "de":3, "fl":25,"ga":13,"hi":4, "id":4, "il":22,
            "in":12,"ia":7, "ks":6, "ky":8, "la":9,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":12,"mi":18,"mn":10,"ms":7, "mo":11,"mt":3,
            "nv":4, "nh":4, "nj":15,"nm":5, "ny":33,"nc":14,"nd":3,
            "oh":21,"ok":8, "or":7, "pa":23,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":32,"ut":5, "vt":3, "va":13,"wa":11,"wv":5,
            "wi":11,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        1996: {
            "al":9, "ak":3, "az":8, "ar":6, "ca":54,"co":8, "ct":8,
            "dc":3, "de":3, "fl":25,"ga":13,"hi":4, "id":4, "il":22,
            "in":12,"ia":7, "ks":6, "ky":8, "la":9,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":12,"mi":18,"mn":10,"ms":7, "mo":11,"mt":3,
            "nv":4, "nh":4, "nj":15,"nm":5, "ny":33,"nc":14,"nd":3,
            "oh":21,"ok":8, "or":7, "pa":23,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":32,"ut":5, "vt":3, "va":13,"wa":11,"wv":5,
            "wi":11,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2000: {
            "al":9, "ak":3, "az":8, "ar":6, "ca":54,"co":8, "ct":8,
            "dc":3, "de":3, "fl":25,"ga":13,"hi":4, "id":4, "il":22,
            "in":12,"ia":7, "ks":6, "ky":8, "la":9,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":12,"mi":18,"mn":10,"ms":7, "mo":11,"mt":3,
            "nv":4, "nh":4, "nj":15,"nm":5, "ny":33,"nc":14,"nd":3,
            "oh":21,"ok":8, "or":7, "pa":23,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":32,"ut":5, "vt":3, "va":13,"wa":11,"wv":5,
            "wi":11,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2004: {
            "al":9, "ak":3, "az":10,"ar":6, "ca":55,"co":9, "ct":7,
            "dc":3, "de":3, "fl":27,"ga":15,"hi":4, "id":4, "il":21,
            "in":11,"ia":7, "ks":6, "ky":8, "la":9,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":12,"mi":17,"mn":10,"ms":6, "mo":11,"mt":3,
            "nv":5, "nh":4, "nj":15,"nm":5, "ny":31,"nc":15,"nd":3,
            "oh":20,"ok":7, "or":7, "pa":21,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":34,"ut":5, "vt":3, "va":13,"wa":11,"wv":5,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2008: {
            "al":9, "ak":3, "az":10,"ar":6, "ca":55,"co":9, "ct":7,
            "dc":3, "de":3, "fl":27,"ga":15,"hi":4, "id":4, "il":21,
            "in":11,"ia":7, "ks":6, "ky":8, "la":9,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":12,"mi":17,"mn":10,"ms":6, "mo":11,"mt":3,
            "nv":5, "nh":4, "nj":15,"nm":5, "ny":31,"nc":15,"nd":3,
            "oh":20,"ok":7, "or":7, "pa":21,"ri":4, "sc":8, "sd":3,
            "tn":11,"tx":34,"ut":5, "vt":3, "va":13,"wa":11,"wv":5,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2012: {
            "al":9, "ak":3, "az":11,"ar":6, "ca":55,"co":9, "ct":7,
            "dc":3, "de":3, "fl":29,"ga":16,"hi":4, "id":4, "il":20,
            "in":11,"ia":6, "ks":6, "ky":8, "la":8,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":11,"mi":16,"mn":10,"ms":6, "mo":10,"mt":3,
            "nv":6, "nh":4, "nj":14,"nm":5, "ny":29,"nc":15,"nd":3,
            "oh":18,"ok":7, "or":7, "pa":20,"ri":4, "sc":9, "sd":3,
            "tn":11,"tx":38,"ut":6, "vt":3, "va":13,"wa":12,"wv":5,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2016: {
            "al":9, "ak":3, "az":11,"ar":6, "ca":55,"co":9, "ct":7,
            "dc":3, "de":3, "fl":29,"ga":16,"hi":4, "id":4, "il":20,
            "in":11,"ia":6, "ks":6, "ky":8, "la":8,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":11,"mi":16,"mn":10,"ms":6, "mo":10,"mt":3,
            "nv":6, "nh":4, "nj":14,"nm":5, "ny":29,"nc":15,"nd":3,
            "oh":18,"ok":7, "or":7, "pa":20,"ri":4, "sc":9, "sd":3,
            "tn":11,"tx":38,"ut":6, "vt":3, "va":13,"wa":12,"wv":5,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2020: {
            "al":9, "ak":3, "az":11,"ar":6, "ca":55,"co":9, "ct":7,
            "dc":3, "de":3, "fl":29,"ga":16,"hi":4, "id":4, "il":20,
            "in":11,"ia":6, "ks":6, "ky":8, "la":8,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":11,"mi":16,"mn":10,"ms":6, "mo":10,"mt":3,
            "nv":6, "nh":4, "nj":14,"nm":5, "ny":29,"nc":15,"nd":3,
            "oh":18,"ok":7, "or":7, "pa":20,"ri":4, "sc":9, "sd":3,
            "tn":11,"tx":38,"ut":6, "vt":3, "va":13,"wa":12,"wv":5,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
        2024: {
            "al":9, "ak":3, "az":11,"ar":6, "ca":54,"co":10,"ct":7,
            "dc":3, "de":3, "fl":30,"ga":16,"hi":4, "id":4, "il":19,
            "in":11,"ia":6, "ks":6, "ky":8, "la":8,
            "me-al":2,"me-01":1,"me-02":1,
            "md":10,"ma":11,"mi":15,"mn":10,"ms":6, "mo":10,"mt":4,
            "nv":6, "nh":4, "nj":14,"nm":5, "ny":28,"nc":16,"nd":3,
            "oh":17,"ok":7, "or":8, "pa":19,"ri":4, "sc":9, "sd":3,
            "tn":11,"tx":40,"ut":6, "vt":3, "va":13,"wa":12,"wv":4,
            "wi":10,"wy":3,
            "ne-al":2,"ne-01":1,"ne-02":1,"ne-03":1,
        },
    }

    # Look up the correct EV table for this election year.
    # Fall back to 2024 apportionment for any year not in the table
    # (e.g. user-uploaded custom CSVs with year=0).
    EV_BY_REGION = EV_BY_YEAR.get(int(year), EV_BY_YEAR[2024])

    # ── Postal code → YAPms region id(s) ──────────────────────────────────────
    # Most states map 1-to-1.  ME and NE are split into at-large + CD ids;
    # since county data doesn't break down by CD, all of the state's counties
    # are aggregated together and the same winner is applied to every id.
    POSTAL_TO_REGIONS = {
        "AL": ["al"], "AK": ["ak"], "AZ": ["az"], "AR": ["ar"], "CA": ["ca"],
        "CO": ["co"], "CT": ["ct"], "DE": ["de"], "DC": ["dc"], "FL": ["fl"],
        "GA": ["ga"], "HI": ["hi"], "ID": ["id"], "IL": ["il"], "IN": ["in"],
        "IA": ["ia"], "KS": ["ks"], "KY": ["ky"], "LA": ["la"],
        "ME": ["me-al", "me-01", "me-02"],
        "MD": ["md"], "MA": ["ma"], "MI": ["mi"], "MN": ["mn"], "MS": ["ms"],
        "MO": ["mo"], "MT": ["mt"],
        "NE": ["ne-al", "ne-01", "ne-02", "ne-03"],
        "NV": ["nv"], "NH": ["nh"], "NJ": ["nj"], "NM": ["nm"], "NY": ["ny"],
        "NC": ["nc"], "ND": ["nd"], "OH": ["oh"], "OK": ["ok"], "OR": ["or"],
        "PA": ["pa"], "RI": ["ri"], "SC": ["sc"], "SD": ["sd"], "TN": ["tn"],
        "TX": ["tx"], "UT": ["ut"], "VT": ["vt"], "VA": ["va"], "WA": ["wa"],
        "WV": ["wv"], "WI": ["wi"], "WY": ["wy"],
    }

    # ── Third-party display metadata ───────────────────────────────────────────
    # Maps the CSV Winner value to the human-readable name and four YAPms margin
    # colors (safe → toss-up, darkest → lightest).  Each entry also gets a
    # stable UUID generated once below so every state they win shares one id.
    THIRD_PARTY_META = {
        # George Wallace's American Independent Party (1968)
        "Wallace":   {"name": "Wallace",   "colors": ["#5c1a7a", "#732d94", "#8e4daa", "#a875c0"]},
        # Ross Perot's Reform Party runs (1992, 1996)
        "Perot":     {"name": "Perot",     "colors": ["#246624", "#2b8c2b", "#30a630", "#73d873"]},
        # Southern unpledged electors (1960, etc.)
        "Unpledged": {"name": "Unpledged", "colors": ["#806000", "#b38600", "#cc9900", "#e6b800"]},
        # All other third-party/independent candidates
        "Other":     {"name": "Other",     "colors": ["#cc5200", "#e65c00", "#ff6600", "#ff994d"]},
    }

    # ── Margin tier helper ─────────────────────────────────────────────────────
    # Uses the winner's share of the *total* vote (all parties) so that a narrow
    # plurality over a large third-party field is correctly shown as competitive.
    # Third-party winners always get tier 3 (toss-up) because a plurality win
    # in a multi-way race doesn't represent dominance in the same way.
    def _margin_tier(win_pct, is_third_party=False):
        # Use the same thresholds for all parties — third-party wins can be
        # landslides too (e.g. Wallace took some Southern states by wide margins).
        if win_pct >= 60: return 0  # Safe
        if win_pct >= 55: return 1  # Likely
        if win_pct >= 52: return 2  # Lean
        return 3                    # Toss-up

    # ── Accumulate vote totals per postal code ─────────────────────────────────
    # We track every party separately so that a third party that out-polls both
    # major parties in a state is correctly identified as the winner.
    # Keys: postal code string (e.g. "AL").
    # Values: dict of party_name -> total votes (float, derived from pct * total).
    state_votes = {}  # { postal: { party: float } }

    for row in rows:
        code = row.get('County__State_Code', '')
        parts = code.rsplit('__', 1)
        if len(parts) != 2:
            continue
        postal = parts[1]

        try:
            shift   = county_shifts_applied.get(code, 0)
            d_pct   = max(0.0, min(100.0, float(row.get('Democrat_Pct')   or 0) - shift))
            r_pct   = max(0.0, min(100.0, float(row.get('Republican_Pct') or 0) + shift))
            o_pct   = max(0.0, float(row.get('Other_Pct')     or 0))
            w_pct   = max(0.0, float(row.get('Wallace_Pct')   or 0))
            p_pct   = max(0.0, float(row.get('Perot_Pct')     or 0))
            u_pct   = max(0.0, float(row.get('Unpledged_Pct') or 0))
            total   = int(row.get('Total_Votes') or 0)
        except (ValueError, TypeError):
            continue

        # Apply other-vote redistribution if active.
        # When redistribution is on, all third-party percentages collapse to 0
        # because those votes have been folded into one of the major parties.
        if otherAsRep:
            r_pct = 100.0 - d_pct
            o_pct = w_pct = p_pct = u_pct = 0.0
        elif otherAsDem:
            d_pct = 100.0 - r_pct
            o_pct = w_pct = p_pct = u_pct = 0.0

        # Add this county's votes to the running state totals.
        party_tally = state_votes.setdefault(postal, {})
        party_tally['Democrat']   = party_tally.get('Democrat',   0) + d_pct * total / 100.0
        party_tally['Republican'] = party_tally.get('Republican', 0) + r_pct * total / 100.0
        party_tally['Other']      = party_tally.get('Other',      0) + o_pct * total / 100.0
        party_tally['Wallace']    = party_tally.get('Wallace',     0) + w_pct * total / 100.0
        party_tally['Perot']      = party_tally.get('Perot',       0) + p_pct * total / 100.0
        party_tally['Unpledged']  = party_tally.get('Unpledged',   0) + u_pct * total / 100.0

    # ── Assign stable UUIDs to any third parties that actually win a state ─────
    # We generate UUIDs efficiently: only parties that end up winning at least one
    # state get an entry, so irrelevant third parties don't clutter the JSON.
    # The UUIDs are deterministic within a run (generated once here, reused for
    # every state that party wins) but differ between runs — that's fine because
    # YAPms treats them as opaque identifiers.
    third_party_ids = {}  # party_name -> uuid string (populated on first win)

    # ── Build the states list ─────────────────────────────────────────────────
    state_regions     = []
    seen_region_ids   = set()

    for postal, region_ids in POSTAL_TO_REGIONS.items():
        tally     = state_votes.get(postal, {})
        total_v   = sum(tally.values())

        # Find the party with the most votes in this state.
        if total_v == 0:
            # No data for this state — fall back to Democrat (won't affect real maps).
            winner_party = 'Democrat'
            win_pct      = 50.0
        else:
            winner_party = max(tally, key=tally.get)
            win_pct      = tally[winner_party] / total_v * 100.0

        # Map the winning party name to its YAPms candidate id.
        is_third_party = winner_party not in ('Democrat', 'Republican')

        if winner_party == 'Democrat':
            winner_cand_id = "0"
        elif winner_party == 'Republican':
            winner_cand_id = "1"
        else:
            # Third-party winner: assign a UUID the first time we see this party win,
            # then reuse the same UUID for every subsequent state it wins.
            if winner_party not in third_party_ids:
                third_party_ids[winner_party] = str(_uuid.uuid4())
            winner_cand_id = third_party_ids[winner_party]

        tier = _margin_tier(win_pct, is_third_party=is_third_party)

        # Emit one region entry per YAPms id that maps to this postal code.
        for rid in region_ids:
            if rid in seen_region_ids:
                continue
            seen_region_ids.add(rid)
            ev = EV_BY_REGION.get(rid, 0)
            state_regions.append({
                "id":          rid,
                "value":       ev,
                "permaVal":    ev,
                "locked":      False,
                "permaLocked": False,
                "disabled":    False,
                # YAPms expects a single-element list here; count = EVs awarded.
                "candidates":  [{"id": winner_cand_id, "count": ev, "margin": tier}],
            })

    # Sort regions alphabetically by id for a tidy, diff-friendly file.
    state_regions.sort(key=lambda r: r["id"])

    # ── Build the candidates array ─────────────────────────────────────────────
    # Always include Democrat (id "0") and Republican (id "1").
    # Append a third-party entry for every party that actually won a state,
    # in the order they were first encountered above.
    yapms_candidates = [
        {
            "id":           "0",
            "name":         "Democrat" if not switchColors else "Republican",
            "defaultCount": 0,
            "margins": [
                {"color": "#1C408C"},  # Safe
                {"color": "#577CCC"},  # Likely
                {"color": "#8AAFFF"},  # Lean
                {"color": "#949BB3"},  # Toss-up
            ],
        },
        {
            "id":           "1",
            "name":         "Republican" if not switchColors else "Democrat",
            "defaultCount": 0,
            "margins": [
                {"color": "#BF1D29"},  # Safe
                {"color": "#FF5865"},  # Likely
                {"color": "#FF8B98"},  # Lean
                {"color": "#CF8980"},  # Toss-up
            ],
        },
    ]

    for party_name, cand_uuid in third_party_ids.items():
        meta = THIRD_PARTY_META.get(party_name, {
            # Fallback for any unexpected party name: neutral grey-green palette.
            "name":   party_name,
            "colors": ["#2e6b2e", "#3d8f3d", "#57b357", "#7fcc7f"],
        })
        yapms_candidates.append({
            "id":           cand_uuid,
            "name":         meta["name"],
            "defaultCount": 0,
            "margins": [{"color": c} for c in meta["colors"]],
        })

    # ── Determine YAPms year / variant strings ─────────────────────────────────
    # "results" variant tells YAPms to use its built-in SVG map for that year.
    # The EV counts in our regions must exactly match YAPms's stored permaVal
    # for that year — that's what EV_BY_YEAR above ensures, preventing ghost
    # electors from appearing when YAPms merges the imported data with its own.
    # Year 0 means user-uploaded CSV with no specific year; use 2024 map + blank.
    yapmscountyyear = 2023 #There are two county map options on YAPms: 2020 and 2023.
    if int(year) == 0:
        yapmsyear = "2024310"
        variant   = "blank"
    elif int(year) == 2024:
        yapmsyear = "2024310"
        variant   = "results"
    else:
        yapmsyear = str(year)
        variant   = "results"
        yapmscountyyear = 2020

    # ── Assemble and write the final YAPms JSON ────────────────────────────────
    yapms_state = {
        "map": {
            "country": "usa",
            "type":    "presidential",
            "year":    yapmsyear,
            "variant": variant,
        },
        "tossup": {
            "id":           "",
            "name":         "Tossup",
            "defaultCount": 0,
            "margins":      [{"color": "#cccccc"}],
        },
        "candidates": yapms_candidates,
        "regions":    state_regions,
    }

    with open(os.path.join(BASE_DIR, "StateLevel.json"), "w", encoding="utf-8") as f:
        json.dump(yapms_state, f, indent=2)

    # ── Build final MapChart JSON output ───────────────────────────────────────
    if switchColors:
        output = {"groups": {
            "#ffccd0": {"label": "Democratic 30-40%",  "paths": Democrat_30_40},
            "#f2b3be": {"label": "Democratic 40-50%",  "paths": Democrat_40_50},
            "#e27f90": {"label": "Democratic 50-60%",  "paths": Democrat_50_60},
            "#cc2f4a": {"label": "Democratic 60-70%",  "paths": Democrat_60_70},
            "#d40000": {"label": "Democratic 70-80%",  "paths": Democrat_70_80},
            "#aa0000": {"label": "Democratic 80-90%",  "paths": Democrat_80_90},
            "#800000": {"label": "Democratic 90-100%", "paths": Democrat_90_100},
            "#d3e7ff": {"label": "Republican 30-40%",  "paths": Republican_30_40},
            "#b9d7ff": {"label": "Republican 40-50%",  "paths": Republican_40_50},
            "#86b6f2": {"label": "Republican 50-60%",  "paths": Republican_50_60},
            "#4389e3": {"label": "Republican 60-70%",  "paths": Republican_60_70},
            "#1666cb": {"label": "Republican 70-80%",  "paths": Republican_70_80},
            "#0645b4": {"label": "Republican 80-90%",  "paths": Republican_80_90},
            "#003ab4": {"label": "Republican 90-100%", "paths": Republican_90_100},
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

    progress_queue.put({"type": "done", "data": output})




# ─── Routes ───────────────────────────────────────────────────────────────────
"""For shifting special regions"""

@app.route('/api/upload', methods=['POST'])
def upload_csv():
    """Accept a CSV file upload and save it as 0results.csv for use with year=0."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part in request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if not file.filename.lower().endswith('.csv'):
        return jsonify({"error": "Only CSV files are accepted"}), 400
    file.save(os.path.join(BASE_DIR, '0results.csv'))
    return jsonify({"status": "ok", "message": "Saved as 0results.csv"})


@app.route('/api/download-csv')
def download_csv():
    """Serve newresults.csv as a file download."""
    import os
    if not os.path.exists(os.path.join(BASE_DIR, 'newresults.csv')):
        return jsonify({"error": "No results CSV available yet. Generate an election first."}), 404
    return send_file(
        os.path.join(BASE_DIR, 'newresults.csv'),
        mimetype='text/csv',
        as_attachment=True,
        download_name='newresults.csv'
    )

@app.route('/api/download-state-json')
def download_state_json():
    """Serve StateLevel.json as a file download."""
    if not os.path.exists(os.path.join(BASE_DIR, 'StateLevel.json')):
        return jsonify({"error": "No StateLevel.json available yet. Generate an election first."}), 404
    return send_file(
        os.path.join(BASE_DIR, 'StateLevel.json'),
        mimetype='application/json',
        as_attachment=True,
        download_name='StateLevel.json'
    )


@app.route('/')
def index():
    regions = [name for name in dir(specialRegions) if not name.startswith('_')]
    return render_template('index.html', regions=regions)


@app.route("/api/results")
def results():
    """Check whether a cached result exists for this year + reassign other mode + shifts."""
    year          = request.args.get("year", "").strip()
    other_mode    = request.args.get("otherMode", "none")  # "dem", "rep", or "none"
    shifts_raw    = request.args.get("stateShifts", "{}")  # JSON string, e.g. '{"Alabama":30}'
    regions_raw   = request.args.get("regionShifts", "{}")
    switch_colors = request.args.get("switchColors", "false").lower() == "true"

    if not year.isdigit() or (int(year) != 0 and not (1788 <= int(year) <= 2100)):  # year=0 is user-uploaded data
        return jsonify({"error": "Invalid year"}), 400

    try:
        state_shifts = json.loads(shifts_raw)
        # Normalise: drop zero-shift entries so cache keys match
        state_shifts = {k: int(v) for k, v in state_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        state_shifts = {}

    try:
        region_shifts = json.loads(regions_raw)
        region_shifts = {k: int(v) for k, v in region_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        region_shifts = {}

    # Cache key includes shifts and switchColors so each unique combination is stored separately
    cache_key = (year, other_mode, json.dumps(state_shifts, sort_keys=True), json.dumps(region_shifts, sort_keys=True), switch_colors)
    if cache_key in results_cache:
        return jsonify({"status": "cached", "data": results_cache[cache_key]})

    return jsonify({"status": "use_stream"}), 202


@app.route("/api/stream")
def stream():
    """Server-Sent Events endpoint — streams progress updates then final data.

    Query parameters:
      year        – election year, or 0 for user-uploaded data (required)
      otherMode   – how to handle non-R/D votes:
                      "dem"  → otherAsDem=True
                      "rep"  → otherAsRep=True
                      "none" → show third parties separately (default)
      stateShifts – JSON object mapping state names to signed integer shift
                    amounts, e.g. '{"Alabama": 30}'.  Positive = toward
                    Republican, negative = toward Democrat.
    """
    year          = request.args.get("year", "").strip()
    other_mode    = request.args.get("otherMode", "none")
    shifts_raw    = request.args.get("stateShifts", "{}")
    regions_raw   = request.args.get("regionShifts", "{}")
    switch_colors = request.args.get("switchColors", "false").lower() == "true"

    if not year.isdigit() or (int(year) != 0 and not (1788 <= int(year) <= 2100)):
        def err():
            yield "data: " + json.dumps({"type": "error", "message": "Invalid year"}) + "\n\n"
        return Response(err(), mimetype="text/event-stream")

    try:
        state_shifts = json.loads(shifts_raw)
        state_shifts = {k: int(v) for k, v in state_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        state_shifts = {}

    try:
        region_shifts = json.loads(regions_raw)
        region_shifts = {k: int(v) for k, v in region_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        region_shifts = {}

    cache_key = (year, other_mode, json.dumps(state_shifts, sort_keys=True), json.dumps(region_shifts, sort_keys=True), switch_colors)

    if cache_key in results_cache:
        def cached():
            yield "data: " + json.dumps({"type": "done", "data": results_cache[cache_key]}) + "\n\n"
        return Response(cached(), mimetype="text/event-stream")

    otherAsDem = (other_mode == "dem")
    otherAsRep = (other_mode == "rep")

    progress_queue = queue.Queue()

    def scrape_thread():
        run_scraper(year, progress_queue,
                    otherAsDem=otherAsDem, otherAsRep=otherAsRep,
                    state_shifts=state_shifts, region_shifts=region_shifts,
                    switchColors=switch_colors)

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
    try: # deletes 0results.csv
        os.remove("C:/Users/leoth/Mapchart-txtmaker/0results.csv")
        print("File deleted successfully.")
    except FileNotFoundError:
        pass
    try: # deletes 0results.csv
        os.remove("C:/Users/leoth/Mapchart-txtmaker/StateLevel.json")
        print("File deleted successfully.")
    except FileNotFoundError:
        pass
