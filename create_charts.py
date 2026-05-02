#!/usr/bin/env python3
"""
Generate before/after comparison charts showing the combined impact of:
  1. Fan heater on a 2-hour timer (instead of all night)
  2. EcoFlow Delta 2 Max 4kWh battery charged from E7 + solar

Before = actual measured grid import, no changes
After  = grid import after both changes applied

Outputs (PNG):
  chart_time_of_day.png
  chart_monthly.png
  chart_daily.png
  chart_savings.png
  schematic.png
"""

import csv
import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from collections import defaultdict

# ── Colours ───────────────────────────────────────────────────────────────────
BEFORE_COL  = "#E05C5C"
AFTER_COL   = "#4CAF7D"
BATT_COL    = "#F39C12"
FAN_COL     = "#9B59B6"
SOLAR_COL   = "#F9E79F"
GRID_COL    = "#5B9BD5"
E7_BG       = "#FFF8E1"
SOL_BG      = "#F9FBE7"
DARK_BG     = "#1E2A3A"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 150,
})

# ── Constants ─────────────────────────────────────────────────────────────────
BASELOAD_W   = 558
NIGHT_RATE   = 10.28
DAY_RATE_1   = 30.93
DAY_RATE_2   = 27.43
RATE_CHANGE  = datetime.date(2026, 4, 1)
SLOT_H       = 0.5
BST_START    = datetime.datetime(2026, 3, 29, 1, 0, tzinfo=datetime.timezone.utc)


def to_local(dt_utc):
    if dt_utc >= BST_START:
        return dt_utc + datetime.timedelta(hours=1)
    return dt_utc


def tariff_rate(date, is_e7):
    if is_e7:
        return NIGHT_RATE
    return DAY_RATE_2 if date >= RATE_CHANGE else DAY_RATE_1


def is_e7(dt_utc):
    local = to_local(dt_utc)
    mins = local.hour * 60 + local.minute
    return 30 <= mins < 450  # 00:30–07:30


# ── Data loading ──────────────────────────────────────────────────────────────

def load_baseload(path="baseload_analysis.csv"):
    rows = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            dt = datetime.datetime.strptime(r["datetime_utc"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            rows[dt] = {
                "import_w": float(r["watts"]),
                "solar":    r["solar_period"] == "yes",
            }
    return rows


def load_battery_sim(path="battery_simulation.csv"):
    rows = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            dt = datetime.datetime.strptime(r["datetime_utc"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            rows[dt] = {
                "battery_w": float(r["battery_supply_w"]),
                "e7_w":      float(r["e7_charge_w"]),
                "solar_w":   float(r["solar_charge_w"]),
            }
    return rows


def load_gaming(path="late_night_gaming.csv"):
    data = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            data[datetime.date.fromisoformat(r["date"])] = {
                "flagged": r["flagged"] == "yes",
                "extra_w": int(r["extra_above_baseload_w"]),
            }
    return data


def fan_reduction(dt_utc, gaming):
    """Watts saved in 'after' scenario: fan off 00:00–06:00 local on fan nights."""
    local = to_local(dt_utc)
    mins  = local.hour * 60 + local.minute
    if not (0 <= mins < 360):   # only 00:00–06:00 local
        return 0.0
    entry = gaming.get(dt_utc.date())
    if entry and entry["flagged"]:
        return float(entry["extra_w"])
    return 0.0


# ── Build merged per-slot table ───────────────────────────────────────────────

def build_slots(baseload, batt_sim, gaming):
    slots = []
    for dt in sorted(baseload):
        local     = to_local(dt)
        b         = baseload[dt]
        bs        = batt_sim.get(dt, {"battery_w": 0, "e7_w": 0, "solar_w": 0})
        fan_red   = fan_reduction(dt, gaming)
        e7_now    = is_e7(dt)
        date_local = local.date()
        rate      = tariff_rate(date_local, e7_now)

        import_before = b["import_w"]
        # After: remove battery supply and fan load; add E7 charging draw
        import_after  = max(0.0, import_before - bs["battery_w"] + bs["e7_w"] - fan_red)

        cost_before = (import_before * SLOT_H / 1000) * rate
        cost_after  = (import_after  * SLOT_H / 1000) * rate

        slots.append({
            "dt":            dt,
            "local":         local,
            "slot_num":      local.hour * 2 + local.minute // 30,
            "date":          date_local,
            "month":         date_local.strftime("%b %Y"),
            "import_before": import_before,
            "import_after":  import_after,
            "fan_red":       fan_red,
            "battery_w":     bs["battery_w"],
            "e7_w":          bs["e7_w"],
            "solar_w":       bs["solar_w"],
            "cost_before":   cost_before,
            "cost_after":    cost_after,
            "solar":         b["solar"],
            "e7":            e7_now,
        })
    return slots


# ── Chart 1: Time-of-day profile ──────────────────────────────────────────────

def chart_time_of_day(slots):
    by_slot_before = defaultdict(list)
    by_slot_after  = defaultdict(list)
    for s in slots:
        n = s["slot_num"]
        by_slot_before[n].append(s["import_before"])
        by_slot_after[n].append(s["import_after"])

    nums   = list(range(48))
    before = [np.mean(by_slot_before[n]) for n in nums]
    after  = [np.mean(by_slot_after[n])  for n in nums]
    labels = [f"{n//2:02d}:{(n%2)*30:02d}" for n in nums]

    fig, ax = plt.subplots(figsize=(14, 5))

    # Background bands
    ax.axvspan(1, 15, alpha=0.12, color="#FFB300", zorder=0, label="E7 window (00:30–07:30)")
    ax.axvspan(14, 36, alpha=0.08, color="#8BC34A", zorder=0, label="Solar hours (approx)")

    ax.plot(nums, before, color=BEFORE_COL, lw=2.5, label="Before  (no changes)")
    ax.plot(nums, after,  color=AFTER_COL,  lw=2.5, linestyle="--",
            label="After  (battery + fan timer)")
    ax.axhline(BASELOAD_W, color=GRID_COL, lw=1, linestyle=":", alpha=0.7,
               label=f"True baseload ({BASELOAD_W} W)")

    # Shade saving zones
    ax.fill_between(nums, before, after,
                    where=[b > a for b, a in zip(before, after)],
                    alpha=0.25, color=AFTER_COL, label="Grid import saved")
    # Shade E7 charging overhead
    ax.fill_between(nums, before, after,
                    where=[a > b for b, a in zip(before, after)],
                    alpha=0.25, color=BATT_COL, label="E7 battery charging")

    # Annotations
    ax.annotate("Fan off\n(timer)", xy=(3, (before[3]+after[3])/2),
                xytext=(3, 1350), fontsize=8, color=FAN_COL, ha="center",
                arrowprops=dict(arrowstyle="->", color=FAN_COL, lw=1.2))
    ax.annotate("Battery\ndischarging", xy=(22, (before[22]+after[22])/2),
                xytext=(22, 1350), fontsize=8, color=AFTER_COL, ha="center",
                arrowprops=dict(arrowstyle="->", color=AFTER_COL, lw=1.2))
    ax.annotate("E7\ncharging", xy=(4, (before[4]+after[4])/2 + 60),
                xytext=(9, 1100), fontsize=8, color=BATT_COL, ha="center",
                arrowprops=dict(arrowstyle="->", color=BATT_COL, lw=1.2))

    ax.set_xticks(nums[::4])
    ax.set_xticklabels(labels[::4], rotation=40, ha="right", fontsize=8)
    ax.set_ylabel("Average grid import (W)")
    ax.set_xlabel("Time of day (local UK time)")
    ax.set_title("Average half-hourly grid import — before vs after\n"
                 "(battery + fan timer combined, 157-day average)", fontsize=12)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.set_ylim(0)
    plt.tight_layout()
    plt.savefig("chart_time_of_day.png")
    plt.close()
    print("Saved chart_time_of_day.png")


# ── Chart 2: Monthly grid import ─────────────────────────────────────────────

def chart_monthly(slots):
    by_month = defaultdict(lambda: {"before": 0.0, "after": 0.0})
    month_order = []
    for s in slots:
        m = s["month"]
        if m not in month_order:
            month_order.append(m)
        by_month[m]["before"] += s["import_before"] * SLOT_H / 1000
        by_month[m]["after"]  += s["import_after"]  * SLOT_H / 1000

    months  = month_order
    before  = [by_month[m]["before"] for m in months]
    after   = [by_month[m]["after"]  for m in months]
    savings = [b - a for b, a in zip(before, after)]
    x       = np.arange(len(months))
    w       = 0.35

    fig, ax = plt.subplots(figsize=(12, 5))
    b1 = ax.bar(x - w/2, before, w, color=BEFORE_COL, alpha=0.85, label="Before")
    b2 = ax.bar(x + w/2, after,  w, color=AFTER_COL,  alpha=0.85, label="After (battery + fan timer)")

    for i, (bv, av, sv) in enumerate(zip(before, after, savings)):
        ax.text(i - w/2, bv + 4, f"{bv:.0f}", ha="center", va="bottom", fontsize=7.5,
                color=BEFORE_COL, fontweight="bold")
        ax.text(i + w/2, av + 4, f"{av:.0f}", ha="center", va="bottom", fontsize=7.5,
                color=AFTER_COL,  fontweight="bold")
        ax.text(i, max(bv, av) + 25, f"−{sv:.0f} kWh", ha="center", fontsize=7,
                color="#333", style="italic")

    ax.set_xticks(x)
    ax.set_xticklabels(months, rotation=25, ha="right")
    ax.set_ylabel("Total grid import (kWh)")
    ax.set_title("Monthly grid electricity import — before vs after", fontsize=12)
    ax.legend(fontsize=9)
    ax.set_ylim(0, max(before) * 1.2)
    plt.tight_layout()
    plt.savefig("chart_monthly.png")
    plt.close()
    print("Saved chart_monthly.png")


# ── Chart 3: Daily import timeline ───────────────────────────────────────────

def chart_daily(slots):
    by_day = defaultdict(lambda: {"before": 0.0, "after": 0.0})
    for s in slots:
        d = s["date"]
        by_day[d]["before"] += s["import_before"] * SLOT_H / 1000
        by_day[d]["after"]  += s["import_after"]  * SLOT_H / 1000

    dates  = sorted(by_day)
    before = [by_day[d]["before"] for d in dates]
    after  = [by_day[d]["after"]  for d in dates]

    # 7-day rolling averages
    def rolling(vals, w=7):
        return [np.mean(vals[max(0, i-w+1):i+1]) for i in range(len(vals))]

    roll_b = rolling(before)
    roll_a = rolling(after)

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.fill_between(dates, before, after, alpha=0.15, color=AFTER_COL, label="Daily saving")
    ax.scatter(dates, before, color=BEFORE_COL, s=12, alpha=0.5, zorder=3)
    ax.scatter(dates, after,  color=AFTER_COL,  s=12, alpha=0.5, zorder=3)
    ax.plot(dates, roll_b, color=BEFORE_COL, lw=2, label="Before (7-day avg)")
    ax.plot(dates, roll_a, color=AFTER_COL,  lw=2, linestyle="--",
            label="After — battery + fan timer (7-day avg)")

    ax.set_ylabel("Daily grid import (kWh)")
    ax.set_xlabel("Date")
    ax.set_title("Daily grid import — before vs after", fontsize=12)
    ax.legend(fontsize=9)
    plt.xticks(rotation=30, ha="right", fontsize=8)
    plt.tight_layout()
    plt.savefig("chart_daily.png")
    plt.close()
    print("Saved chart_daily.png")


# ── Chart 4: Savings breakdown ────────────────────────────────────────────────

def chart_savings(slots):
    total_cost_before = sum(s["cost_before"] for s in slots)
    total_cost_after  = sum(s["cost_after"]  for s in slots)
    n_days = len(set(s["date"] for s in slots))

    # Attribute each saving to its source
    fan_saving_p    = sum((s["fan_red"] * SLOT_H / 1000) *
                          tariff_rate(s["date"], s["e7"]) for s in slots)
    batt_saving_p   = sum((s["battery_w"] * SLOT_H / 1000) *
                          tariff_rate(s["date"], s["e7"]) for s in slots)
    e7_cost_p       = sum((s["e7_w"] * SLOT_H / 1000) * NIGHT_RATE for s in slots)
    net_batt_p      = batt_saving_p - e7_cost_p

    annual = lambda p: p / n_days * 365 / 100

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    # ── Left: waterfall cost chart ──
    ax = axes[0]
    categories = ["Before", "Fan timer\nsaving", "Battery\nsaving", "E7 charge\ncost", "After"]
    base_cost  = total_cost_before / 100
    values     = [base_cost,
                  -fan_saving_p / 100,
                  -batt_saving_p / 100,
                  e7_cost_p / 100,
                  total_cost_after / 100]
    colors = [BEFORE_COL, FAN_COL, AFTER_COL, BATT_COL, AFTER_COL]

    # Running total for waterfall
    running = 0
    bottoms = []
    for i, v in enumerate(values):
        if i == 0 or i == len(values) - 1:
            bottoms.append(0)
        else:
            bottoms.append(running)
        if i == 0:
            running = v
        elif i == len(values) - 1:
            pass
        else:
            running += v

    bars = ax.bar(categories, [abs(v) for v in values], bottom=bottoms,
                  color=colors, alpha=0.85, edgecolor="white", linewidth=0.8)

    # Connector lines
    for i in range(len(values) - 2):
        top = bottoms[i] + abs(values[i]) if i == 0 else bottoms[i+1] + abs(values[i+1]) if values[i+1] < 0 else bottoms[i+1]
        if values[i+1] < 0:
            y = bottoms[i+1]
        else:
            y = bottoms[i+1] + abs(values[i+1])
        ax.plot([i + 0.4, i + 0.6], [bottoms[i] + abs(values[i]) if i == 0 else
                (bottoms[i] if values[i] < 0 else bottoms[i] + abs(values[i])),
                (bottoms[i] if values[i] < 0 else bottoms[i] + abs(values[i]))],
                color="#999", lw=0.8, linestyle=":")

    for bar, val, bot in zip(bars, values, bottoms):
        label = f"−£{abs(val):.2f}" if val < 0 else f"£{val:.2f}"
        ax.text(bar.get_x() + bar.get_width()/2,
                bot + abs(val) / 2,
                label, ha="center", va="center", fontsize=8.5,
                fontweight="bold", color="white")

    ax.set_ylabel(f"Cost over {n_days} days (£)")
    ax.set_title(f"Grid cost breakdown\n({n_days}-day period)", fontsize=11)
    ax.set_ylim(0)

    # ── Right: annualised bar chart ──
    ax2 = axes[1]
    items = [
        ("Without\nbattery or timer", annual(total_cost_before), BEFORE_COL),
        ("Fan timer\nonly", annual(total_cost_before - fan_saving_p), FAN_COL),
        ("Battery\nonly", annual(total_cost_before - net_batt_p), BATT_COL),
        ("Both\ncombined", annual(total_cost_after), AFTER_COL),
    ]
    labels2 = [i[0] for i in items]
    vals2   = [i[1] for i in items]
    cols2   = [i[2] for i in items]
    x2 = np.arange(len(labels2))
    bars2 = ax2.bar(x2, vals2, color=cols2, alpha=0.85, edgecolor="white")

    for bar, val in zip(bars2, vals2):
        ax2.text(bar.get_x() + bar.get_width()/2, val + 5,
                 f"£{val:.0f}/yr", ha="center", va="bottom", fontsize=9, fontweight="bold")

    # Saving arrows
    for i in range(1, len(vals2)):
        saving = vals2[0] - vals2[i]
        ax2.annotate("", xy=(i, vals2[i] + 2), xytext=(i, vals2[0] - 2),
                     arrowprops=dict(arrowstyle="<->", color="#555", lw=1.2))
        ax2.text(i + 0.35, (vals2[0] + vals2[i]) / 2,
                 f"−£{saving:.0f}/yr", fontsize=7.5, color="#333", va="center")

    ax2.set_xticks(x2)
    ax2.set_xticklabels(labels2, fontsize=9)
    ax2.set_ylabel("Estimated annual grid electricity cost (£)")
    ax2.set_title("Annualised cost — scenario comparison", fontsize=11)
    ax2.set_ylim(0, max(vals2) * 1.25)

    plt.suptitle("Financial impact of battery + fan timer", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.savefig("chart_savings.png", bbox_inches="tight")
    plt.close()
    print("Saved chart_savings.png")


# ── Chart 5: Schematic ────────────────────────────────────────────────────────

def schematic(slots):
    total_before = sum(s["import_before"] * SLOT_H / 1000 for s in slots)
    total_after  = sum(s["import_after"]  * SLOT_H / 1000 for s in slots)
    n_days       = len(set(s["date"] for s in slots))

    cost_before  = sum(s["cost_before"] for s in slots) / 100
    cost_after   = sum(s["cost_after"]  for s in slots) / 100
    total_saving = cost_before - cost_after
    annual_sav   = total_saving / n_days * 365

    fig, axes = plt.subplots(1, 2, figsize=(17, 10))
    fig.patch.set_facecolor(DARK_BG)

    for ax, side in zip(axes, ["BEFORE", "AFTER"]):
        ax.set_facecolor("#263544")
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 13)
        ax.axis("off")

        accent = BEFORE_COL if side == "BEFORE" else AFTER_COL
        ax.text(5, 12.5, side, ha="center", fontsize=22,
                fontweight="bold", color=accent)

        # House shell
        house = mpatches.FancyBboxPatch((0.5, 1.5), 9.0, 9.0,
                                         boxstyle="square,pad=0",
                                         facecolor="#2C3E50", edgecolor=accent,
                                         linewidth=2, zorder=1)
        ax.add_patch(house)
        roof_pts = np.array([[0.5, 10.5], [5.0, 12.2], [9.5, 10.5]])
        ax.add_patch(plt.Polygon(roof_pts, closed=True, facecolor="#1A252F",
                                 edgecolor=accent, linewidth=2, zorder=2))

        # Solar panels (on roof, both sides)
        for i, px in enumerate([2.2, 3.2, 4.2, 5.2, 6.2, 7.2]):
            py = 10.7 + (0.3 if i < 3 else 0.1)
            ax.add_patch(mpatches.FancyBboxPatch((px, py), 0.75, 0.48,
                          boxstyle="round,pad=0.02", facecolor="#1A6E8E",
                          edgecolor="#5DADE2", linewidth=1, zorder=3))
            ax.text(px + 0.375, py + 0.24, "☀", ha="center", va="center",
                    fontsize=8, color="#F9E79F", zorder=4)
        ax.text(5.0, 11.35, "Solar panels → free daytime charging (after)",
                ha="center", fontsize=6.5,
                color="#5DADE2" if side == "AFTER" else "#666", zorder=4)

        # ── Device boxes ─────────────────────────────────────────
        def device(x, y, label, watts, color, w=2.0, h=0.55):
            ax.add_patch(mpatches.FancyBboxPatch((x, y), w, h,
                          boxstyle="round,pad=0.05", facecolor=color,
                          edgecolor="white", linewidth=1.2, zorder=3))
            ax.text(x + w/2, y + h/2 + 0.08, label, ha="center", va="center",
                    fontsize=7.5, fontweight="bold", color="white", zorder=4)
            ax.text(x + w/2, y + h/2 - 0.12, watts, ha="center", va="center",
                    fontsize=7.5, color="white", alpha=0.9, zorder=4)

        device(0.7, 9.3, "Home Server", "150 W always-on", "#2980B9")
        device(0.7, 8.6, "Networking", "30 W always-on",   "#2980B9")
        device(0.7, 7.9, "Fridge/Freezer", "~80 W cycling", "#2980B9")
        device(3.1, 9.3, "Gaming PC", "100–500 W",          "#8E44AD")
        device(3.1, 8.6, "Home Office", "200–350 W (days)", "#8E44AD")
        device(3.1, 7.9, "Other loads", "~400 W avg",       "#8E44AD")

        fan_color = BEFORE_COL if side == "BEFORE" else "#27AE60"
        fan_label = "Fan Heater\n~333 W  ALL NIGHT" if side == "BEFORE" else "Fan Heater\n~333 W  2-HR TIMER"
        fan_bg    = mpatches.FancyBboxPatch((5.5, 7.8), 2.2, 1.2,
                                             boxstyle="round,pad=0.08",
                                             facecolor=fan_color, edgecolor="white",
                                             linewidth=1.5, alpha=0.9, zorder=3)
        ax.add_patch(fan_bg)
        ax.text(6.6, 8.7, "Fan Heater", ha="center", fontsize=8,
                fontweight="bold", color="white", zorder=4)
        ax.text(6.6, 8.35, "~333 W", ha="center", fontsize=8, color="white", zorder=4)
        ax.text(6.6, 8.0, "ALL NIGHT" if side == "BEFORE" else "2-HR TIMER",
                ha="center", fontsize=8, fontweight="bold",
                color="white" if side == "BEFORE" else "#FFD700", zorder=4)

        # ── Battery ───────────────────────────────────────────────
        if side == "AFTER":
            batt = mpatches.FancyBboxPatch((8.0, 7.5), 1.6, 2.5,
                                            boxstyle="round,pad=0.1",
                                            facecolor="#1A252F", edgecolor=BATT_COL,
                                            linewidth=2, zorder=3)
            ax.add_patch(batt)
            ax.text(8.8, 9.75, "EcoFlow", ha="center", fontsize=7.5,
                    fontweight="bold", color=BATT_COL, zorder=4)
            ax.text(8.8, 9.45, "4 kWh", ha="center", fontsize=7.5,
                    color="white", zorder=4)
            # Charge bar
            ax.add_patch(mpatches.Rectangle((8.2, 7.7), 1.2, 0.5,
                          facecolor="none", edgecolor=BATT_COL, linewidth=1, zorder=4))
            ax.add_patch(mpatches.Rectangle((8.2, 7.7), 0.96, 0.5,
                          facecolor=BATT_COL, alpha=0.75, zorder=4))
            ax.text(8.8, 8.42, "E7 charge\n00:30–07:30", ha="center",
                    fontsize=6.5, color=BATT_COL, zorder=4)
            ax.text(8.8, 8.1, "80%", ha="center", fontsize=7,
                    fontweight="bold", color=BATT_COL, zorder=4)
        else:
            ax.add_patch(mpatches.FancyBboxPatch((8.0, 7.5), 1.6, 2.5,
                          boxstyle="round,pad=0.1", facecolor="#1A252F",
                          edgecolor="#555", linewidth=1.5, linestyle="--", zorder=3))
            ax.text(8.8, 8.75, "No battery", ha="center", fontsize=7.5,
                    color="#666", zorder=4)

        # ── Grid connection ───────────────────────────────────────
        ax.annotate("", xy=(0.5, 6.8), xytext=(-0.3, 6.8),
                    arrowprops=dict(arrowstyle="->", color="#FFB300", lw=2.5))
        ax.text(-0.35, 6.8, "GRID", ha="center", fontsize=7,
                fontweight="bold", color="#FFB300", rotation=90, va="center")

        # ── Timeline bars (22:00 → 08:00) ────────────────────────
        ax.text(5.0, 7.3, "Overnight load profile (22:00 → 08:00):",
                ha="center", fontsize=7.5, color="#BDC3C7", zorder=4)

        def timeline(y, on_frac, color, label, total_w=6.5, x0=1.75):
            ax.add_patch(mpatches.Rectangle((x0, y), total_w, 0.22,
                          facecolor="#3D5166", edgecolor="none", zorder=2))
            ax.add_patch(mpatches.Rectangle((x0, y), total_w * on_frac, 0.22,
                          facecolor=color, edgecolor="none", alpha=0.85, zorder=3))
            ax.text(x0 - 0.1, y + 0.11, "22:00", ha="right",
                    va="center", fontsize=5.5, color="#AAA")
            ax.text(x0 + total_w + 0.1, y + 0.11, "08:00", ha="left",
                    va="center", fontsize=5.5, color="#AAA")
            ax.text(x0 + total_w / 2, y + 0.3, label,
                    ha="center", va="bottom", fontsize=6.5, color=color)

        timeline(6.65, 1.0,   "#2980B9", "Always-on (server, fridge, PC idle) — 280 W")
        timeline(6.15, 0.3,   "#8E44AD", "Gaming sessions (variable) — ~300–500 W")
        fan_frac = 1.0 if side == "BEFORE" else 0.2
        timeline(5.65, fan_frac, fan_color,
                 f"Fan heater — {'all night (8h)' if side == 'BEFORE' else '2-hr timer'}")

        # ── Summary box ───────────────────────────────────────────
        period_kwh = total_before if side == "BEFORE" else total_after
        period_cost = cost_before if side == "BEFORE" else cost_after
        ann_cost = period_cost / n_days * 365

        summary = mpatches.FancyBboxPatch((0.5, 1.6), 9.0, 3.5,
                                           boxstyle="round,pad=0.1",
                                           facecolor="#1A252F", edgecolor=accent,
                                           linewidth=1.5, alpha=0.85, zorder=3)
        ax.add_patch(summary)

        ax.text(5.0, 4.85, "SUMMARY", ha="center", fontsize=9,
                fontweight="bold", color=accent, zorder=4)
        rows = [
            (f"Grid import ({n_days} days):", f"{period_kwh:.0f} kWh"),
            (f"Avg daily import:", f"{period_kwh/n_days:.1f} kWh/day"),
            (f"Cost ({n_days} days):", f"£{period_cost:.2f}"),
            ("Estimated annual cost:", f"£{ann_cost:.0f}/yr"),
        ]
        for i, (label, val) in enumerate(rows):
            y = 4.45 - i * 0.55
            ax.text(1.2, y, label, ha="left", fontsize=8.5, color="#BDC3C7", zorder=4)
            ax.text(8.8, y, val, ha="right", fontsize=8.5,
                    fontweight="bold", color="white", zorder=4)

    # ── Central saving callout ────────────────────────────────────────────────
    fig.text(0.5, 0.42,
             f"Total saving\n£{total_saving:.0f}  /  {n_days} days\n\n"
             f"≈ £{annual_sav:.0f} / year",
             ha="center", va="center", fontsize=13,
             fontweight="bold", color="#F1C40F",
             bbox=dict(boxstyle="round,pad=0.5", facecolor=DARK_BG,
                       edgecolor="#F1C40F", linewidth=2.5))

    plt.suptitle("Home energy — before vs after  (battery + fan timer)",
                 fontsize=14, color="white", y=1.01)
    plt.tight_layout(rect=[0, 0, 1, 1])
    plt.savefig("schematic.png", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print("Saved schematic.png")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Loading data …")
    baseload = load_baseload()
    batt_sim = load_battery_sim()
    gaming   = load_gaming()
    print(f"  {len(baseload)} half-hour slots loaded\n")

    print("Building merged slot table …")
    slots = build_slots(baseload, batt_sim, gaming)
    n_days = len(set(s["date"] for s in slots))
    tot_b = sum(s["import_before"] * SLOT_H / 1000 for s in slots)
    tot_a = sum(s["import_after"]  * SLOT_H / 1000 for s in slots)
    print(f"  Before: {tot_b:.0f} kWh over {n_days} days  ({tot_b/n_days:.1f} kWh/day)")
    print(f"  After:  {tot_a:.0f} kWh over {n_days} days  ({tot_a/n_days:.1f} kWh/day)")
    print(f"  Saving: {tot_b-tot_a:.0f} kWh  ({(tot_b-tot_a)/tot_b*100:.1f}%)\n")

    print("Generating charts …")
    chart_time_of_day(slots)
    chart_monthly(slots)
    chart_daily(slots)
    chart_savings(slots)
    schematic(slots)
    print("\nDone.")


if __name__ == "__main__":
    main()
