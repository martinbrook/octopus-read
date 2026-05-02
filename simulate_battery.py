#!/usr/bin/env python3
"""
Simulate an EcoFlow Delta 2 Max + Extra Battery (4 kWh total) charged from
Economy 7 cheap-rate hours and solar excess, powering the home office and
gaming PC.

Inputs  : baseload_analysis.csv, late_night_gaming.csv
Outputs : console summary + battery_simulation.csv

Assumptions:
  - E7 window: 00:30-07:30 local UK time (East Midlands standard)
  - Round-trip efficiency: 85% (charge 92% × discharge 92%)
  - Office load: server 150W + networking 30W + PC idle 100W always-on,
    +100W office gear weekdays 09:00-18:00
  - Gaming load: modelled from late_night_gaming.csv intensity flags,
    applied to the evening before each flagged deep-night date
  - Solar excess: estimated from import dropping below baseload (558W)
    during solar hours — conservative; actual panels likely generate more
  - Battery charges during E7; load served from grid during E7 (cheap anyway)
  - Outside E7: battery discharges to serve load; grid covers deficit
"""

import csv
import argparse
import datetime
from collections import defaultdict

# ── Battery specs ────────────────────────────────────────────────────────────
CAPACITY_WH   = 4096     # EcoFlow Delta 2 Max + 1 extra battery
CHARGE_EFF    = 0.92     # AC→stored
DISCHARGE_EFF = 0.92     # stored→output  (round-trip ≈ 85%)
MAX_CHARGE_W  = 2400     # max AC charge rate
MAX_SOLAR_W   = 1000     # max solar input

# ── Tariff ───────────────────────────────────────────────────────────────────
NIGHT_RATE  = 10.28      # p/kWh  E7 cheap rate
DAY_RATE_1  = 30.93      # p/kWh  before 1 Apr 2026
DAY_RATE_2  = 27.43      # p/kWh  from 1 Apr 2026
RATE_CHANGE = datetime.date(2026, 4, 1)

# ── E7 window (local UK time, minutes from midnight) ─────────────────────────
E7_START = 30            # 00:30
E7_END   = 7 * 60 + 30  # 07:30

# ── Modelled always-on load (home office + gaming PC) ────────────────────────
SERVER_W       = 150     # home server 24/7
NETWORK_W      = 30      # router, switch, etc.
PC_IDLE_W      = 100     # gaming PC at idle
OFFICE_EXTRA_W = 100     # monitors + work laptop weekdays 09:00-18:00

# ── Solar excess threshold ───────────────────────────────────────────────────
BASELOAD_W = 558         # 5th-percentile deep-night — established earlier

SLOT_H = 0.5             # 30-minute slots

# ── UK DST: BST starts last Sunday March 2026 = 29 Mar 01:00 UTC ─────────────
BST_START = datetime.datetime(2026, 3, 29, 1, 0, tzinfo=datetime.timezone.utc)


# ── Helpers ──────────────────────────────────────────────────────────────────

def to_local(dt_utc):
    if dt_utc >= BST_START:
        return dt_utc + datetime.timedelta(hours=1)
    return dt_utc


def is_e7(dt_utc):
    local = to_local(dt_utc)
    m = local.hour * 60 + local.minute
    return E7_START <= m < E7_END


def day_rate(date):
    return DAY_RATE_2 if date >= RATE_CHANGE else DAY_RATE_1


# ── Data loaders ─────────────────────────────────────────────────────────────

def load_baseload(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            dt = datetime.datetime.strptime(r["datetime_utc"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            rows.append({
                "dt":       dt,
                "import_w": float(r["watts"]),
                "solar":    r["solar_period"] == "yes",
            })
    return rows


def load_gaming(path):
    data = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            data[datetime.date.fromisoformat(r["date"])] = {
                "flagged": r["flagged"] == "yes",
                "extra_w": int(r["extra_above_baseload_w"]),
            }
    return data


# ── Load profile ─────────────────────────────────────────────────────────────

def gaming_extra_w(local_dt, gaming_evenings):
    """Extra gaming-PC watts above idle for this slot, based on prior analysis."""
    entry = gaming_evenings.get(local_dt.date())
    if not entry or not entry["flagged"]:
        return 0
    extra = entry["extra_w"]
    mins = local_dt.hour * 60 + local_dt.minute
    if extra > 400:                           # HIGH — intensive late session
        if 19 * 60 <= mins <= 23 * 60 + 30:
            return 450
    elif extra > 200:                         # MODERATE
        if 19 * 60 <= mins <= 22 * 60 + 30:
            return 300
    else:                                     # LOW
        if 19 * 60 <= mins <= 21 * 60 + 30:
            return 180
    return 0


def office_gaming_load(dt_utc, gaming_evenings):
    """Total modelled load (W) for home office + gaming PC at this UTC slot."""
    local = to_local(dt_utc)
    mins  = local.hour * 60 + local.minute
    load  = SERVER_W + NETWORK_W + PC_IDLE_W   # 280W always-on
    if local.weekday() < 5 and 9 * 60 <= mins < 18 * 60:
        load += OFFICE_EXTRA_W
    load += gaming_extra_w(local, gaming_evenings)
    return load


def solar_excess_w(import_w, is_solar):
    """Estimate solar power available to charge battery (W)."""
    if not is_solar:
        return 0
    # Conservative: excess only when import drops below whole-house baseload,
    # implying solar > instantaneous demand
    return min(max(0.0, BASELOAD_W - import_w), MAX_SOLAR_W)


# ── Simulation ────────────────────────────────────────────────────────────────

def simulate(baseload, gaming_data, purchase_price):
    # Evening gaming sessions: flagged deep-night date X → session on evening X-1
    gaming_evenings = {
        date - datetime.timedelta(days=1): entry
        for date, entry in gaming_data.items()
    }

    soc = CAPACITY_WH * 0.5   # start at 50 %

    total_load_wh           = 0.0
    battery_supply_wh       = 0.0
    grid_supply_wh          = 0.0
    e7_stored_wh            = 0.0
    solar_stored_wh         = 0.0
    cost_with_p             = 0.0
    cost_without_p          = 0.0

    by_day    = defaultdict(lambda: dict(load=0.0, battery=0.0, grid=0.0,
                                         e7=0.0, solar=0.0))
    out_rows  = []

    for slot in baseload:
        dt       = slot["dt"]
        import_w = slot["import_w"]
        is_sol   = slot["solar"]
        local_d  = to_local(dt).date()
        dr       = day_rate(local_d)
        e7_now   = is_e7(dt)

        load_w  = office_gaming_load(dt, gaming_evenings)
        load_wh = load_w * SLOT_H

        # Cost if no battery (E7 load served at cheap rate, daytime at day rate)
        cost_without_p += (load_wh / 1000) * (NIGHT_RATE if e7_now else dr)

        # ── 1. E7 grid → battery ───────────────────────────────────────────
        e7_wh = 0.0
        if e7_now and soc < CAPACITY_WH:
            store  = min(CAPACITY_WH - soc, MAX_CHARGE_W * SLOT_H * CHARGE_EFF)
            grid_drawn = store / CHARGE_EFF
            soc   += store
            e7_wh  = store
            e7_stored_wh  += store
            cost_with_p   += (grid_drawn / 1000) * NIGHT_RATE
            by_day[local_d]["e7"] += store

        # ── 2. Solar → battery ─────────────────────────────────────────────
        sol_w  = solar_excess_w(import_w, is_sol)
        sol_wh = 0.0
        if sol_w > 0 and soc < CAPACITY_WH:
            store  = min(CAPACITY_WH - soc, sol_w * SLOT_H * CHARGE_EFF)
            soc   += store
            sol_wh = store
            solar_stored_wh += store
            by_day[local_d]["solar"] += store
        # Solar is free — no cost added

        # ── 3. Battery → load (outside E7 window only) ────────────────────
        bat_wh  = 0.0
        grid_wh = load_wh
        if not e7_now and soc > 0:
            can_deliver = min(soc * DISCHARGE_EFF, load_wh)
            bat_wh  = can_deliver
            soc    -= bat_wh / DISCHARGE_EFF
            grid_wh = load_wh - bat_wh

        # During E7: load served from cheap grid, battery is charging
        # Cost is still night rate (same as without battery during E7)
        if e7_now:
            cost_with_p += (grid_wh / 1000) * NIGHT_RATE
        else:
            cost_with_p += (grid_wh / 1000) * dr

        battery_supply_wh += bat_wh
        grid_supply_wh    += grid_wh
        total_load_wh     += load_wh
        by_day[local_d]["load"]    += load_wh
        by_day[local_d]["battery"] += bat_wh
        by_day[local_d]["grid"]    += grid_wh

        out_rows.append({
            "datetime_utc":    dt.strftime("%Y-%m-%d %H:%M"),
            "soc_wh":          round(soc),
            "load_w":          round(load_w),
            "battery_supply_w": round(bat_wh / SLOT_H),
            "grid_supply_w":   round(grid_wh / SLOT_H),
            "e7_charge_w":     round(e7_wh / SLOT_H),
            "solar_charge_w":  round(sol_wh / SLOT_H),
        })

    return {
        "by_day":             by_day,
        "total_load_wh":      total_load_wh,
        "battery_supply_wh":  battery_supply_wh,
        "grid_supply_wh":     grid_supply_wh,
        "e7_stored_wh":       e7_stored_wh,
        "solar_stored_wh":    solar_stored_wh,
        "cost_with_p":        cost_with_p,
        "cost_without_p":     cost_without_p,
        "out_rows":           out_rows,
        "purchase_price":     purchase_price,
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(r):
    by_day       = r["by_day"]
    n_days       = len(by_day)
    total        = r["total_load_wh"]
    bat          = r["battery_supply_wh"]
    grid         = r["grid_supply_wh"]
    e7_s         = r["e7_stored_wh"]
    sol_s        = r["solar_stored_wh"]
    cost_with    = r["cost_with_p"]
    cost_without = r["cost_without_p"]
    price        = r["purchase_price"]

    saving_p     = cost_without - cost_with
    annual_sav   = (saving_p / n_days) * 365
    payback_yrs  = (price * 100) / annual_sav if annual_sav > 0 else float("inf")

    days_full    = sum(1 for d in by_day.values() if d["load"] > 0 and d["battery"] / d["load"] >= 0.95)
    days_partial = sum(1 for d in by_day.values() if d["load"] > 0 and 0.5 <= d["battery"] / d["load"] < 0.95)

    print("=" * 62)
    print("BATTERY SIMULATION — EcoFlow Delta 2 Max + Extra (4 kWh)")
    print(f"Purchase price: £{price:.0f}")
    print("=" * 62)
    print(f"\nPeriod  : {min(by_day)} → {max(by_day)}  ({n_days} days)")
    print()
    print("── MODELLED LOAD (home office + gaming PC) ──────────────")
    print(f"  Avg daily load      : {total/n_days/1000:.2f} kWh/day")
    print(f"  Total over period   : {total/1000:.1f} kWh")
    print()
    print("── BATTERY COVERAGE ─────────────────────────────────────")
    print(f"  From battery        : {bat/1000:.1f} kWh  ({100*bat/total:.1f}% of load)")
    print(f"    via E7 charging   : {e7_s/1000:.1f} kWh stored")
    print(f"    via solar excess  : {sol_s/1000:.1f} kWh stored (conservative)")
    print(f"  From grid           : {grid/1000:.1f} kWh  ({100*grid/total:.1f}% of load)")
    print()
    print(f"  Days fully covered  : {days_full} / {n_days}")
    print(f"  Days partly covered : {days_partial} / {n_days}")
    print(f"  Days short (<50%)   : {n_days - days_full - days_partial} / {n_days}")
    print()
    print("── COST COMPARISON ──────────────────────────────────────")
    print(f"  Without battery     : £{cost_without/100:.2f} over {n_days} days")
    print(f"  With battery        : £{cost_with/100:.2f} over {n_days} days")
    print(f"  Saving (period)     : £{saving_p/100:.2f}")
    print(f"  Estimated annual    : £{annual_sav/100:.0f}/year")
    print()
    print("── PAYBACK ──────────────────────────────────────────────")
    print(f"  Purchase price      : £{price:.0f}")
    print(f"  Payback period      : {payback_yrs:.1f} years")
    print()
    print("  Note: Solar estimate is conservative (import-suppression")
    print("  method). Actual solar generation likely higher → shorter")
    print("  payback. Excludes whole-house benefit of battery backup.")
    print()

    # Monthly breakdown
    by_month = defaultdict(lambda: dict(load=0.0, battery=0.0, days=0))
    for date, d in by_day.items():
        key = date.strftime("%Y-%m")
        by_month[key]["load"]    += d["load"]
        by_month[key]["battery"] += d["battery"]
        by_month[key]["days"]    += 1

    print("── MONTHLY BREAKDOWN ────────────────────────────────────")
    print(f"  {'Month':<10}  {'Load kWh':>9}  {'Bat kWh':>8}  {'Coverage':>9}  {'Days':>5}")
    for m in sorted(by_month):
        d = by_month[m]
        cov = 100 * d["battery"] / d["load"] if d["load"] > 0 else 0
        print(f"  {m:<10}  {d['load']/1000:>8.1f}  {d['battery']/1000:>8.1f}  {cov:>8.1f}%  {d['days']:>5}")


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\nDetailed half-hourly output → {path}  ({len(rows)} rows)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Simulate 4kWh battery for home office + gaming PC")
    parser.add_argument("--price", type=float, default=1350.0, help="Purchase price £ (default 1350)")
    parser.add_argument("--csv",   default="battery_simulation.csv", help="Output CSV path")
    args = parser.parse_args()

    print("Loading data …")
    baseload     = load_baseload("baseload_analysis.csv")
    gaming_data  = load_gaming("late_night_gaming.csv")
    print(f"  {len(baseload)} half-hour slots, {len(gaming_data)} nights of gaming data\n")

    results = simulate(baseload, gaming_data, args.price)
    report(results)
    write_csv(results["out_rows"], args.csv)


if __name__ == "__main__":
    main()
