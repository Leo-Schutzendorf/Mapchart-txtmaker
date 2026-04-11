from flask import Flask, jsonify, render_template, Response, request
import json
import threading
import queue
import time
import csv
import math
app = Flask(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────
# Keyed by (year, otherAsDem, otherAsRep) so different reassignment modes are
# cached separately.  To add a new per-run option, add it to the cache key here
# and pass it through the stream endpoint below.
results_cache = {}


# ─── CSV-based data loader ────────────────────────────────────────────────────
# Reads pre-scraped 2024 results from a local CSV instead of hitting Wikipedia.
# The CSV must have these columns:
#   County__State_Code, Republican_Votes, Republican_Pct,
#   Democrat_Votes, Democrat_Pct, Other_Votes, Other_Pct, Total_Votes
#
# otherAsDem / otherAsRep: when True, all non-D/R votes are folded into that
# party's total before deciding a county winner.
CSV_PATH = "2024results.csv"

def run_scraper(year, progress_queue, otherAsDem=False, otherAsRep=False, state_shifts=None):
    """Load 2024 county results from the local CSV and bucket them for MapChart.

    state_shifts: dict mapping state name (e.g. "Alabama") to a signed integer
    shift amount (-100..+100).  Positive = shift toward Republican, negative =
    shift toward Democrat.  Applied to each county's raw Dem/Rep percentages
    after normal bucketing; the county is removed from its original bucket and
    re-inserted into the correct shifted one.
    """
    import pandas as pd
    if state_shifts is None:
        state_shifts = {}

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

    def bucket_county(path_id, pct, party):
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
        for lo, hi, idx in ranges:
            if int(lo) <= int(float(pct)) < int(hi):
                buckets[party][idx].append(path_id)
                return

    # ── Load CSV ───────────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        progress_queue.put({"type": "error", "message": f"CSV not found: {CSV_PATH}"})
        return

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

    with open(str(year) + 'results.csv', mode='r') as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    '''
    Reads County__State_Code, Winner, and Winner_Pct columns by name
    so column order doesn't matter and the header row is skipped automatically.
    '''
    for county in rows:
        bucket_county(county['County__State_Code'], county['Winner_Pct'], county['Winner'])

    # ── Apply state-level shifts ───────────────────────────────────────────────
    # For each shifted state, re-derive winner+pct for every county in that
    # state from the raw Dem/Rep vote percentages, then move the county to the
    # correct new bucket.  The shift is a signed percentage-point offset applied
    # to the two-party split:
    #   shifted_dem_pct = dem_pct + shift   (negative shift → more dem)
    #   shifted_rep_pct = rep_pct - shift   (positive shift → more rep)
    # Both are clamped so neither drops below 0, giving effective 100% caps.
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
        bucket_ranges = [(30,40,0),(40,50,1),(50,60,2),(60,70,3),(70,80,4),(80,90,5),(90,101,6)]

        # Index rows by County__State_Code for fast lookup
        row_by_code = {r['County__State_Code']: r for r in rows}

        for state_name, shift in state_shifts.items():
            if shift == 0:
                continue
            # Find all counties belonging to this state (prefix = postal code + "__")
            state_prefix = postalCodes.get(state_name)
            if not state_prefix:
                continue

            for code, row in row_by_code.items():
                # CSV county codes are "CountyName__ST" (double underscore + postal code)
                if not code.endswith('__' + state_prefix):
                    continue

                try:
                    dem_pct = float(row.get('Democrat_Pct') or 0)
                    rep_pct = float(row.get('Republican_Pct') or 0)
                except (ValueError, TypeError):
                    continue

                # Apply shift to the two-party split.
                # shift > 0 → more Republican; shift < 0 → more Democrat.
                new_dem = max(0.0, dem_pct - shift)
                new_rep = max(0.0, rep_pct + shift)

                # Clamp so neither exceeds 100
                if new_rep > 100:
                    new_rep = 100.0
                    new_dem = 0.0
                if new_dem > 100:
                    new_dem = 100.0
                    new_rep = 0.0

                # Determine new winner and winning pct
                if new_rep > new_dem:
                    new_winner = 'Republican'
                    new_pct = new_rep
                elif new_dem > new_rep:
                    new_winner = 'Democrat'
                    new_pct = new_dem
                else:
                    # Exact tie — leave in tie bucket (don't move)
                    continue

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

    # ── Build final MapChart JSON output ───────────────────────────────────────
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
    """Check whether a cached result exists for this year + reassignment mode + shifts."""
    year        = request.args.get("year", "").strip()
    other_mode  = request.args.get("otherMode", "none")  # "dem", "rep", or "none"
    shifts_raw  = request.args.get("stateShifts", "{}")  # JSON string, e.g. '{"Alabama":30}'

    if not year.isdigit() or not (1788 <= int(year) <= 2100):
        return jsonify({"error": "Invalid year"}), 400

    try:
        state_shifts = json.loads(shifts_raw)
        # Normalise: drop zero-shift entries so cache keys match
        state_shifts = {k: int(v) for k, v in state_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        state_shifts = {}

    # Cache key includes shifts so each unique combination is stored separately
    cache_key = (year, other_mode, json.dumps(state_shifts, sort_keys=True))
    if cache_key in results_cache:
        return jsonify({"status": "cached", "data": results_cache[cache_key]})

    return jsonify({"status": "use_stream"}), 202


@app.route("/api/stream")
def stream():
    """Server-Sent Events endpoint — streams progress updates then final data.

    Query parameters:
      year        – four-digit election year (required)
      otherMode   – how to handle non-R/D votes:
                      "dem"  → otherAsDem=True
                      "rep"  → otherAsRep=True
                      "none" → show third parties separately (default)
      stateShifts – JSON object mapping state names to signed integer shift
                    amounts, e.g. '{"Alabama": 30}'.  Positive = toward
                    Republican, negative = toward Democrat.
    """
    year        = request.args.get("year", "").strip()
    other_mode  = request.args.get("otherMode", "none")
    shifts_raw  = request.args.get("stateShifts", "{}")

    if not year.isdigit() or not (1788 <= int(year) <= 2100):
        def err():
            yield "data: " + json.dumps({"type": "error", "message": "Invalid year"}) + "\n\n"
        return Response(err(), mimetype="text/event-stream")

    try:
        state_shifts = json.loads(shifts_raw)
        state_shifts = {k: int(v) for k, v in state_shifts.items() if int(v) != 0}
    except (ValueError, TypeError):
        state_shifts = {}

    cache_key = (year, other_mode, json.dumps(state_shifts, sort_keys=True))

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
                    state_shifts=state_shifts)

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