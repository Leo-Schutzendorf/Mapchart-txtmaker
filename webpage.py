from flask import Flask, render_template, request
import requests
import json

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Region shift support  (uses specialRegions.py)
# ---------------------------------------------------------------------------
# Import every list variable from specialRegions as a dict { region_name: [county_ids] }.
import specialRegions as _sr
import inspect as _inspect

REGION_COUNTIES: dict = {
    name: val
    for name, val in _inspect.getmembers(_sr)
    if isinstance(val, list) and not name.startswith('_')
}

# Build a reverse lookup: county_id -> list of region names it belongs to.
# This lets the shift logic find affected counties in O(1) per county.
COUNTY_TO_REGIONS: dict = {}
for _rname, _counties in REGION_COUNTIES.items():
    for _county in _counties:
        COUNTY_TO_REGIONS.setdefault(_county, []).append(_rname)


def apply_region_shifts(county_margins: dict, region_shifts: dict) -> dict:
    """
    Apply region-level margin shifts on top of already-shifted county margins.

    Parameters
    ----------
    county_margins : dict
        Mapping of county_id -> current margin value (positive = Rep, negative = Dem).
        This dict is mutated in-place and also returned.
    region_shifts : dict
        Mapping of region_name -> shift amount (-100 ... +100).
        Only non-zero entries need to be present; extras are silently ignored.

    Returns
    -------
    dict
        The mutated county_margins dict.

    Integration notes
    -----------------
    In your /api/stream and /api/results routes, after you have already applied
    stateShifts to the raw county margins, call this function before you bucket
    counties into Dem / Rep / Other groups:

        region_shifts = json.loads(request.args.get('regionShifts', '{}'))
        apply_region_shifts(county_margins, region_shifts)

    Region shifts stack additively on top of state shifts.  If Bay_Area is
    shifted -10 and California is shifted +5, a Bay Area county gets net -5.
    """
    active = {rname: amt for rname, amt in region_shifts.items() if amt != 0}
    if not active:
        return county_margins

    for county_id in list(county_margins.keys()):
        regions_for_county = COUNTY_TO_REGIONS.get(county_id, [])
        total_shift = sum(active.get(r, 0) for r in regions_for_county)
        if total_shift:
            county_margins[county_id] = county_margins[county_id] + total_shift

    return county_margins


def get_region_shifts_from_request() -> dict:
    """
    Read the 'regionShifts' query parameter sent by the front-end and return
    it as a plain dict.  Missing or malformed values default to an empty dict.

    Usage in a route:
        region_shifts = get_region_shifts_from_request()
        apply_region_shifts(county_margins, region_shifts)
    """
    raw = request.args.get('regionShifts', '{}')
    try:
        shifts = json.loads(raw)
        return {k: int(v) for k, v in shifts.items() if v != 0}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}