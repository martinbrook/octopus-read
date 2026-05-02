#!/usr/bin/env python3
"""
Analyse half-hourly electricity import data to estimate household baseload,
accounting for solar generation during daylight hours by focusing on
overnight consumption where solar contribution is zero.

Kettering, UK — lat 52.4°N, lon 0.7°W
"""

import os, sys, csv, math, datetime, requests
from collections import defaultdict

BASE_URL = "https://api.octopus.energy"
MPAN    = "1100021680150"
SERIAL  = "21M0104038"
LAT_RAD = math.radians(52.4)   # Kettering latitude


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_all(path, api_key, params=None):
    results = []
    params = dict(params or {})
    params.setdefault("page_size", 1500)
    next_path = path
    while next_path:
        r = requests.get(f"{BASE_URL}{next_path}", auth=(api_key, ""), params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        results.extend(d.get("results", []))
        nxt = d.get("next")
        next_path = nxt.replace(BASE_URL, "") if nxt else None
        params = {}
    return results


# ---------------------------------------------------------------------------
# Solar elevation helpers
# ---------------------------------------------------------------------------

def day_of_year(d):
    return d.timetuple().tm_yday


def solar_declination(doy):
    """Declination in radians (Spencer 1971)."""
    B = math.radians((360 / 365) * (doy - 81))
    return math.radians(23.45 * math.sin(B))


def solar_elevation(dt_utc):
    """Return solar elevation angle in degrees for Kettering at the given UTC datetime."""
    doy  = day_of_year(dt_utc.date())
    decl = solar_declination(doy)
    # Hour angle: solar noon ≈ 12:00 UTC + longitude correction (0.7°W → +0.047h)
    solar_hour = dt_utc.hour + dt_utc.minute / 60.0 + 0.7 / 15.0
    hour_angle = math.radians(15 * (solar_hour - 12))
    sin_elev = (math.sin(LAT_RAD) * math.sin(decl) +
                math.cos(LAT_RAD) * math.cos(decl) * math.cos(hour_angle))
    return math.degrees(math.asin(max(-1, min(1, sin_elev))))


def is_solar_hour(dt_utc, min_elevation=5.0):
    """True when the sun is meaningfully above the horizon (>5° elevation)."""
    return solar_elevation(dt_utc) >= min_elevation


# ---------------------------------------------------------------------------
# Parse timestamps robustly (handles Z and ±HH:MM offsets)
# ---------------------------------------------------------------------------

def parse_dt(s):
    s = s.replace("Z", "+00:00")
    # Python 3.11 handles ±HH:MM natively
    return datetime.datetime.fromisoformat(s)


def to_utc(dt):
    if dt.tzinfo is None:
        return dt
    return (dt - dt.utcoffset()).replace(tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("OCTOPUS_API_KEY", "").strip()
    if not api_key:
        sys.exit("Set OCTOPUS_API_KEY.")

    print("Fetching half-hourly electricity data …")
    raw = fetch_all(
        f"/v1/electricity-meter-points/{MPAN}/meters/{SERIAL}/consumption/",
        api_key,
        {"period_from": "2025-11-26", "period_to": "2026-05-02", "order_by": "period"},
    )
    print(f"  {len(raw)} half-hour slots fetched\n")

    records = []
    for r in raw:
        dt_utc = to_utc(parse_dt(r["interval_start"]))
        kwh    = r["consumption"]
        solar  = is_solar_hour(dt_utc)
        records.append({"dt": dt_utc, "kwh": kwh, "solar": solar})

    # -----------------------------------------------------------------------
    # 1. Overnight (no-solar) records — ground truth for baseload
    # -----------------------------------------------------------------------
    night = [r for r in records if not r["solar"]]
    day   = [r for r in records if r["solar"]]

    night_kwh  = [r["kwh"] for r in night]
    night_avg  = sum(night_kwh) / len(night_kwh)
    night_min  = min(night_kwh)
    night_med  = sorted(night_kwh)[len(night_kwh) // 2]
    # 10th percentile — filters out rare near-zero slots
    p10_idx    = int(0.10 * len(night_kwh))
    night_p10  = sorted(night_kwh)[p10_idx]

    print("=" * 60)
    print("OVERNIGHT (no-solar) CONSUMPTION — half-hour slots")
    print("=" * 60)
    print(f"  Slots analysed    : {len(night)}")
    print(f"  Average           : {night_avg*2000:.0f} W  ({night_avg:.4f} kWh/slot)")
    print(f"  Median            : {night_med*2000:.0f} W  ({night_med:.4f} kWh/slot)")
    print(f"  10th percentile   : {night_p10*2000:.0f} W  ({night_p10:.4f} kWh/slot)")
    print(f"  Minimum ever      : {night_min*2000:.0f} W  ({night_min:.4f} kWh/slot)")
    print()

    # -----------------------------------------------------------------------
    # 2. Per-night minimum (most conservative baseload estimate)
    # -----------------------------------------------------------------------
    by_date_night = defaultdict(list)
    for r in night:
        by_date_night[r["dt"].date()].append(r["kwh"])

    nightly_mins = [min(v) for v in by_date_night.values()]
    avg_nightly_min = sum(nightly_mins) / len(nightly_mins)
    med_nightly_min = sorted(nightly_mins)[len(nightly_mins) // 2]

    print("PER-NIGHT MINIMUM (each night's lowest half-hour)")
    print("-" * 60)
    print(f"  Nights analysed   : {len(nightly_mins)}")
    print(f"  Average of mins   : {avg_nightly_min*2000:.0f} W")
    print(f"  Median of mins    : {med_nightly_min*2000:.0f} W")
    print()

    # -----------------------------------------------------------------------
    # 3. Baseload estimate summary
    # -----------------------------------------------------------------------
    # Best estimate: median of per-night minimums (robust to outliers)
    baseload_w = med_nightly_min * 2 * 1000
    baseload_kwh_day = baseload_w / 1000 * 24

    print("=" * 60)
    print("ESTIMATED BASELOAD")
    print("=" * 60)
    print(f"  {baseload_w:.0f} W  ({baseload_kwh_day:.2f} kWh/day)")
    print()
    print("  Method: median of each night's lowest half-hour reading,")
    print("  which represents always-on devices (routers, fridges, ")
    print("  standby loads) with solar generation ruled out.")
    print()

    # -----------------------------------------------------------------------
    # 4. Monthly breakdown (night vs day avg, to show solar suppression)
    # -----------------------------------------------------------------------
    print("MONTHLY BREAKDOWN")
    print("-" * 60)
    print(f"  {'Month':<10}  {'Night avg':>10}  {'Day avg':>10}  {'Solar offset':>12}  {'Night slots':>11}")

    by_month_night = defaultdict(list)
    by_month_day   = defaultdict(list)
    for r in records:
        key = r["dt"].strftime("%Y-%m")
        (by_month_day if r["solar"] else by_month_night)[key].append(r["kwh"])

    for month in sorted(set(list(by_month_night) + list(by_month_day))):
        n_vals = by_month_night.get(month, [])
        d_vals = by_month_day.get(month, [])
        n_avg  = (sum(n_vals) / len(n_vals) * 2 * 1000) if n_vals else 0
        d_avg  = (sum(d_vals) / len(d_vals) * 2 * 1000) if d_vals else 0
        offset = n_avg - d_avg  # positive = daytime import suppressed by solar
        print(f"  {month:<10}  {n_avg:>8.0f} W  {d_avg:>8.0f} W  {offset:>+10.0f} W  {len(n_vals):>11}")
    print()

    # -----------------------------------------------------------------------
    # 5. Time-of-day profile (average W per half-hour slot across all days)
    # -----------------------------------------------------------------------
    print("TIME-OF-DAY AVERAGE PROFILE (all data, UTC)")
    print("-" * 60)
    by_slot = defaultdict(list)
    for r in records:
        slot = r["dt"].hour * 2 + r["dt"].minute // 30
        by_slot[slot].append(r["kwh"])

    print(f"  {'Time (UTC)':<12}  {'Avg W':>8}  {'Solar?':>7}")
    for slot in range(48):
        h = slot // 2
        m = (slot % 2) * 30
        vals = by_slot.get(slot, [])
        avg_w = (sum(vals) / len(vals) * 2 * 1000) if vals else 0
        # Check if this slot is typically solar (use Jan 1 equinox midpoint)
        sample_dt = datetime.datetime(2026, 3, 15, h, m, tzinfo=datetime.timezone.utc)
        sol = "yes" if is_solar_hour(sample_dt) else "   "
        print(f"  {h:02d}:{m:02d}         {avg_w:>8.0f}  {sol:>7}")
    print()

    # -----------------------------------------------------------------------
    # 6. Write detailed CSV
    # -----------------------------------------------------------------------
    with open("baseload_analysis.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime_utc", "kwh_per_half_hour", "watts", "solar_period",
                    "solar_elevation_deg"])
        for r in records:
            elev = solar_elevation(r["dt"])
            w.writerow([
                r["dt"].strftime("%Y-%m-%d %H:%M"),
                f"{r['kwh']:.4f}",
                f"{r['kwh']*2000:.1f}",
                "yes" if r["solar"] else "no",
                f"{elev:.1f}",
            ])
    print("Detailed half-hourly data written to baseload_analysis.csv")


if __name__ == "__main__":
    main()
