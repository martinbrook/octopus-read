#!/usr/bin/env python3
"""
Generate comparison charts and a schematic showing the impact of putting
the bedroom fan on a 2-hour timer instead of running it all night.

Outputs (all PNG):
  chart_time_of_day.png   — average watts per half-hour slot, before vs after
  chart_monthly.png       — monthly deep-night averages, before vs after
  chart_daily_trend.png   — each night's deep-night average over time
  chart_energy_cost.png   — annual energy & cost breakdown
  schematic.png           — device load schematic, before vs after
"""

import csv
import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import numpy as np
from collections import defaultdict

# ── Constants ────────────────────────────────────────────────────────────────
BASELOAD_W   = 558
FAN_HOURS_BEFORE = 8    # 22:00–06:00
FAN_HOURS_AFTER  = 2    # 22:00–00:00
NIGHT_RATE_P = 10.28
DAY_RATE_P   = 28.0     # blended approximate for display
NIGHTS_PER_YEAR = 250   # 69% × 365

BST_START = datetime.datetime(2026, 3, 29, 1, 0, tzinfo=datetime.timezone.utc)

BEFORE_COL = "#E05C5C"   # red-ish
AFTER_COL  = "#4CAF7D"   # green
BASE_COL   = "#5B9BD5"   # blue
E7_COL     = "#FFF3CD"   # pale amber
SOLAR_COL  = "#FFF9C4"   # pale yellow

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 150,
})


# ── Data loaders ─────────────────────────────────────────────────────────────

def to_local(dt_utc):
    if dt_utc >= BST_START:
        return dt_utc + datetime.timedelta(hours=1)
    return dt_utc


def load_baseload(path="baseload_analysis.csv"):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            dt = datetime.datetime.strptime(r["datetime_utc"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            rows.append({
                "dt":       dt,
                "watts":    float(r["watts"]),
                "solar":    r["solar_period"] == "yes",
                "local":    to_local(dt),
            })
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


def fan_extra_for_date(local_dt, gaming):
    """Return the fan's extra load for this local datetime in the BEFORE scenario."""
    date = local_dt.date()
    entry = gaming.get(date)
    if not entry or not entry["flagged"]:
        # Also check next day (deep-night date is next calendar day after evening)
        next_date = date + datetime.timedelta(days=1)
        entry = gaming.get(next_date)
        if not entry or not entry["flagged"]:
            return 0
    return entry["extra_w"]


def compute_after_watts(watts_before, local_dt, gaming):
    """Subtract fan load for slots in 00:00–06:00 local on fan nights."""
    mins = local_dt.hour * 60 + local_dt.minute
    # Fan runs 22:00-00:00 in "after" scenario → slots 00:00-06:00 have no fan
    if 0 <= mins < 6 * 60:
        extra = fan_extra_for_date(local_dt, gaming)
        return max(BASELOAD_W * 0.5, watts_before - extra)  # floor at half baseload
    return watts_before


# ── Chart 1: Time-of-day profile ─────────────────────────────────────────────

def chart_time_of_day(baseload, gaming):
    by_slot_before = defaultdict(list)
    by_slot_after  = defaultdict(list)

    for r in baseload:
        local = r["local"]
        slot  = local.hour * 2 + local.minute // 30
        by_slot_before[slot].append(r["watts"])
        by_slot_after[slot].append(compute_after_watts(r["watts"], local, gaming))

    slots  = list(range(48))
    before = [np.mean(by_slot_before[s]) for s in slots]
    after  = [np.mean(by_slot_after[s])  for s in slots]
    labels = [f"{s//2:02d}:{(s%2)*30:02d}" for s in slots]

    fig, ax = plt.subplots(figsize=(14, 5))

    # Shade E7 window (00:30–07:30 local)
    ax.axvspan(1, 15, alpha=0.15, color=E7_COL, zorder=0, label="E7 cheap rate (00:30–07:30)")
    # Shade rough solar window
    ax.axvspan(14, 38, alpha=0.10, color=SOLAR_COL, zorder=0, label="Solar hours (approx)")

    ax.plot(slots, before, color=BEFORE_COL, lw=2, label="Before — fan all night")
    ax.plot(slots, after,  color=AFTER_COL,  lw=2, label="After — fan 2-hour timer", linestyle="--")
    ax.axhline(BASELOAD_W, color=BASE_COL, lw=1, linestyle=":", label=f"Baseload ({BASELOAD_W} W)")

    # Annotate the overnight saving zone
    ax.fill_between(slots, before, after, where=[b > a for b, a in zip(before, after)],
                    alpha=0.2, color=AFTER_COL, label="Energy saved")

    tick_every = 4
    ax.set_xticks(slots[::tick_every])
    ax.set_xticklabels(labels[::tick_every], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Average power (W)")
    ax.set_xlabel("Time of day (local UK time)")
    ax.set_title("Average power profile — before vs after fan timer\n(all 157 days averaged)", fontsize=12)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylim(0, None)

    plt.tight_layout()
    plt.savefig("chart_time_of_day.png")
    plt.close()
    print("Saved chart_time_of_day.png")


# ── Chart 2: Monthly deep-night averages ─────────────────────────────────────

def chart_monthly(gaming):
    by_month_before = defaultdict(list)
    by_month_after  = defaultdict(list)

    for date, entry in gaming.items():
        month = date.strftime("%b %Y")
        avg_before = entry["extra_w"] + BASELOAD_W if entry["flagged"] else BASELOAD_W + 50
        avg_after  = BASELOAD_W + 20  # fan off during deep night
        by_month_before[month].append(avg_before)
        by_month_after[month].append(avg_after)

    # Sort by calendar order
    all_months = sorted(set(list(by_month_before) + list(by_month_after)),
                        key=lambda m: datetime.datetime.strptime(m, "%b %Y"))

    before_vals = [np.mean(by_month_before[m]) for m in all_months]
    after_vals  = [np.mean(by_month_after[m])  for m in all_months]

    x = np.arange(len(all_months))
    width = 0.35

    fig, ax = plt.subplots(figsize=(11, 5))
    b1 = ax.bar(x - width/2, before_vals, width, color=BEFORE_COL, alpha=0.85, label="Before")
    b2 = ax.bar(x + width/2, after_vals,  width, color=AFTER_COL,  alpha=0.85, label="After (fan 2h timer)")
    ax.axhline(BASELOAD_W, color=BASE_COL, lw=1.5, linestyle="--", label=f"True baseload ({BASELOAD_W} W)")

    ax.set_xticks(x)
    ax.set_xticklabels(all_months, rotation=30, ha="right")
    ax.set_ylabel("Average deep-night consumption (W)\n[01:00–05:30 UTC]")
    ax.set_title("Monthly deep-night average — before vs after fan timer", fontsize=12)
    ax.legend(fontsize=9)
    ax.set_ylim(0, max(before_vals) * 1.2)

    # Value labels on bars
    for bar in b1:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
                f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=7, color=BEFORE_COL)
    for bar in b2:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
                f"{bar.get_height():.0f}", ha="center", va="bottom", fontsize=7, color=AFTER_COL)

    plt.tight_layout()
    plt.savefig("chart_monthly.png")
    plt.close()
    print("Saved chart_monthly.png")


# ── Chart 3: Daily deep-night trend ──────────────────────────────────────────

def chart_daily_trend(gaming):
    dates, before_vals, after_vals = [], [], []

    for date in sorted(gaming):
        entry = gaming[date]
        before = (BASELOAD_W + entry["extra_w"]) if entry["flagged"] else BASELOAD_W + 40
        after  = BASELOAD_W + 20
        dates.append(date)
        before_vals.append(before)
        after_vals.append(after)

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.scatter(dates, before_vals, color=BEFORE_COL, s=18, alpha=0.7, label="Before", zorder=3)
    ax.plot(dates, before_vals, color=BEFORE_COL, lw=0.6, alpha=0.4)

    ax.scatter(dates, after_vals, color=AFTER_COL, s=18, alpha=0.7, label="After (fan 2h timer)", zorder=3, marker="D")
    ax.plot(dates, after_vals, color=AFTER_COL, lw=0.6, alpha=0.4)

    ax.axhline(BASELOAD_W, color=BASE_COL, lw=1.5, linestyle="--",
               label=f"True baseload ({BASELOAD_W} W)")
    ax.axhline(700, color="orange", lw=1, linestyle=":",
               label="Fan detection threshold (700 W)")

    # Shade the "saving" region
    ax.fill_between(dates, before_vals, after_vals,
                    where=[b > a for b, a in zip(before_vals, after_vals)],
                    alpha=0.15, color=AFTER_COL)

    ax.set_ylabel("Deep-night average (W)  [01:00–05:30 UTC]")
    ax.set_xlabel("Date")
    ax.set_title("Nightly deep-night consumption — before vs after fan timer", fontsize=12)
    ax.legend(fontsize=9)
    plt.xticks(rotation=30, ha="right", fontsize=8)
    plt.tight_layout()
    plt.savefig("chart_daily_trend.png")
    plt.close()
    print("Saved chart_daily_trend.png")


# ── Chart 4: Annual energy & cost breakdown ───────────────────────────────────

def chart_energy_cost(gaming):
    flagged = [e for e in gaming.values() if e["flagged"]]
    avg_fan_w = np.mean([e["extra_w"] for e in flagged]) if flagged else 333

    # Annual energy (kWh)
    baseload_kwh   = BASELOAD_W / 1000 * 24 * 365
    fan_before_kwh = avg_fan_w / 1000 * FAN_HOURS_BEFORE * NIGHTS_PER_YEAR
    fan_after_kwh  = avg_fan_w / 1000 * FAN_HOURS_AFTER  * NIGHTS_PER_YEAR
    fan_saved_kwh  = fan_before_kwh - fan_after_kwh

    # Annual cost (£)
    baseload_cost   = baseload_kwh   * NIGHT_RATE_P / 100
    fan_before_cost = fan_before_kwh * NIGHT_RATE_P / 100
    fan_after_cost  = fan_after_kwh  * NIGHT_RATE_P / 100
    fan_saved_cost  = fan_before_cost - fan_after_cost

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    # ── Left: energy stacked bars ──
    ax = axes[0]
    cats = ["Before", "After"]
    base_vals = [baseload_kwh, baseload_kwh]
    fan_vals  = [fan_before_kwh, fan_after_kwh]

    ax.bar(cats, base_vals, color=BASE_COL, alpha=0.85, label=f"Baseload ({BASELOAD_W} W always-on)")
    ax.bar(cats, fan_vals, bottom=base_vals, color=BEFORE_COL, alpha=0.85,
           label="Fan heater (extra overnight load)")

    # Annotate savings
    ax.annotate(
        f"Saved\n{fan_saved_kwh:.0f} kWh/yr",
        xy=(0.5, baseload_kwh + fan_before_kwh / 2),
        xytext=(1.6, baseload_kwh + fan_before_kwh * 0.8),
        arrowprops=dict(arrowstyle="->", color="black", lw=1.5),
        fontsize=10, color=AFTER_COL, fontweight="bold",
        ha="center",
    )

    ax.set_ylabel("Annual energy (kWh)")
    ax.set_title("Annual electricity consumption\n(overnight load only)", fontsize=11)
    ax.legend(fontsize=8)
    for i, (b, f) in enumerate(zip(base_vals, fan_vals)):
        ax.text(i, b + f + 20, f"{b+f:.0f} kWh", ha="center", fontsize=10, fontweight="bold")

    # ── Right: cost stacked bars ──
    ax2 = axes[1]
    base_costs = [baseload_cost, baseload_cost]
    fan_costs  = [fan_before_cost, fan_after_cost]

    ax2.bar(cats, base_costs, color=BASE_COL, alpha=0.85, label="Baseload cost")
    ax2.bar(cats, fan_costs, bottom=base_costs, color=BEFORE_COL, alpha=0.85,
            label="Fan cost (at E7 night rate)")

    ax2.annotate(
        f"Saved\n£{fan_saved_cost:.0f}/yr",
        xy=(0.5, baseload_cost + fan_before_cost / 2),
        xytext=(1.6, baseload_cost + fan_before_cost * 0.8),
        arrowprops=dict(arrowstyle="->", color="black", lw=1.5),
        fontsize=10, color=AFTER_COL, fontweight="bold",
        ha="center",
    )

    ax2.set_ylabel("Annual cost (£)")
    ax2.set_title("Annual electricity cost\n(overnight load, E7 night rate)", fontsize=11)
    ax2.legend(fontsize=8)
    for i, (b, f) in enumerate(zip(base_costs, fan_costs)):
        ax2.text(i, b + f + 0.5, f"£{b+f:.0f}", ha="center", fontsize=10, fontweight="bold")

    plt.suptitle("Impact of fan timer — annual energy & cost comparison", fontsize=13, y=1.01)
    plt.tight_layout()
    plt.savefig("chart_energy_cost.png", bbox_inches="tight")
    plt.close()
    print("Saved chart_energy_cost.png")


# ── Chart 5: Schematic ────────────────────────────────────────────────────────

def draw_device(ax, x, y, label, watts, color, width=1.4, height=0.55):
    """Draw a labelled device box with wattage."""
    box = mpatches.FancyBboxPatch((x, y), width, height,
                                   boxstyle="round,pad=0.05",
                                   facecolor=color, edgecolor="white",
                                   linewidth=1.5, zorder=3)
    ax.add_patch(box)
    ax.text(x + width/2, y + height/2 + 0.07, label,
            ha="center", va="center", fontsize=8, fontweight="bold",
            color="white", zorder=4)
    ax.text(x + width/2, y + height/2 - 0.13, f"{watts} W",
            ha="center", va="center", fontsize=8, color="white", zorder=4)


def draw_timeline(ax, x, y, on_start, on_end, color, label, total_h=10):
    """Draw a 22:00–08:00 timeline bar showing when device is on."""
    bar_w = 4.0
    h = 0.22
    # Background (off)
    ax.add_patch(mpatches.Rectangle((x, y), bar_w, h,
                  facecolor="#DDDDDD", edgecolor="none", zorder=2))
    # On period
    frac_start = on_start / total_h
    frac_end   = on_end   / total_h
    ax.add_patch(mpatches.Rectangle(
        (x + frac_start * bar_w, y), (frac_end - frac_start) * bar_w, h,
        facecolor=color, edgecolor="none", alpha=0.85, zorder=3))
    # Labels
    ax.text(x - 0.1, y + h/2, "22:00", ha="right", va="center", fontsize=6.5, color="#555")
    ax.text(x + bar_w + 0.1, y + h/2, "08:00", ha="left",  va="center", fontsize=6.5, color="#555")
    ax.text(x + bar_w/2, y + h + 0.08, label,
            ha="center", va="bottom", fontsize=7, color=color, fontweight="bold")


def schematic():
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    fig.patch.set_facecolor("#1E2A3A")

    panels = [
        ("BEFORE", axes[0], "#C0392B", FAN_HOURS_BEFORE,
         "Fan heater runs\nall night (8 hrs)", "#E74C3C"),
        ("AFTER",  axes[1], "#27AE60", FAN_HOURS_AFTER,
         "Fan heater on\n2-hr timer", "#2ECC71"),
    ]

    for title, ax, accent, fan_hours, fan_note, fan_col in panels:
        ax.set_facecolor("#263544")
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 12)
        ax.axis("off")

        # Panel title
        ax.text(5, 11.4, title, ha="center", va="center",
                fontsize=22, fontweight="bold", color=accent)

        # ── House outline ──────────────────────────────────────────
        house_x, house_y, house_w, house_h = 0.4, 1.2, 9.2, 8.5
        roof_pts = np.array([[house_x, house_y + house_h],
                              [house_x + house_w/2, house_y + house_h + 1.6],
                              [house_x + house_w, house_y + house_h]])
        house = mpatches.FancyBboxPatch((house_x, house_y), house_w, house_h,
                                         boxstyle="square,pad=0",
                                         facecolor="#2C3E50", edgecolor=accent,
                                         linewidth=2, zorder=1)
        ax.add_patch(house)
        roof = plt.Polygon(roof_pts, closed=True, facecolor="#1A252F",
                           edgecolor=accent, linewidth=2, zorder=2)
        ax.add_patch(roof)

        # ── Solar panels on roof ──
        for i in range(4):
            px = 2.8 + i * 1.1
            py = house_y + house_h + 0.55
            panel = mpatches.FancyBboxPatch((px, py), 0.85, 0.55,
                                             boxstyle="round,pad=0.03",
                                             facecolor="#1A6E8E", edgecolor="#5DADE2",
                                             linewidth=1, zorder=3)
            ax.add_patch(panel)
            ax.text(px + 0.425, py + 0.275, "☀", ha="center", va="center",
                    fontsize=9, color="#F9E79F", zorder=4)
        ax.text(5, house_y + house_h + 1.3, "Solar panels",
                ha="center", fontsize=7, color="#5DADE2")

        # ── Devices ───────────────────────────────────────────────
        # Left column: always-on
        draw_device(ax, 0.7, 7.5, "Home Server", "150", "#2980B9")
        draw_device(ax, 0.7, 6.7, "Networking", "30",  "#2980B9")
        draw_device(ax, 0.7, 5.9, "Fridge/Freezer", "~80", "#2980B9")

        # Middle column: office + gaming
        draw_device(ax, 2.5, 7.5, "Gaming PC", "100–500", "#8E44AD")
        draw_device(ax, 2.5, 6.7, "Home Office", "100–200", "#8E44AD")
        draw_device(ax, 2.5, 5.9, "Monitors", "~60", "#8E44AD")

        # Right column: fan (colour changes before/after)
        fan_color = "#C0392B" if title == "BEFORE" else "#27AE60"
        draw_device(ax, 4.3, 7.5, "Fan Heater", f"~{333}", fan_color)

        # ── Battery / EcoFlow ──
        batt_col = "#F39C12"
        batt = mpatches.FancyBboxPatch((6.3, 5.7), 2.8, 1.8,
                                        boxstyle="round,pad=0.1",
                                        facecolor="#1A252F", edgecolor=batt_col,
                                        linewidth=2, zorder=3)
        ax.add_patch(batt)
        ax.text(7.7, 7.1, "EcoFlow", ha="center", fontsize=8,
                fontweight="bold", color=batt_col, zorder=4)
        ax.text(7.7, 6.8, "Delta 2 Max", ha="center", fontsize=7,
                color=batt_col, zorder=4)
        ax.text(7.7, 6.5, "4 kWh battery", ha="center", fontsize=7.5,
                color="white", zorder=4)
        # Battery level bar
        batt_fill = 0.6 if title == "BEFORE" else 0.8
        ax.add_patch(mpatches.Rectangle((6.6, 5.9), 2.2 * batt_fill, 0.3,
                     facecolor=batt_col, alpha=0.8, zorder=4))
        ax.add_patch(mpatches.Rectangle((6.6, 5.9), 2.2, 0.3,
                     facecolor="none", edgecolor=batt_col, linewidth=1, zorder=4))
        ax.text(7.7, 6.22, f"SoC ~{int(batt_fill*100)}%",
                ha="center", fontsize=7, color=batt_col, zorder=4)

        # ── Night timeline ─────────────────────────────────────────
        ax.text(5, 5.2, "Overnight activity (22:00 → 08:00):",
                ha="center", fontsize=8, color="#BDC3C7")
        # Always-on devices bar (full night)
        draw_timeline(ax, 3.0, 4.7, 0, 10, "#2980B9", "Always-on (server, fridge, PC idle)")
        # Gaming / office (evening only)
        draw_timeline(ax, 3.0, 4.2, 0, 2.5, "#8E44AD", "Gaming / office (stops ~00:30)")
        # Fan
        draw_timeline(ax, 3.0, 3.7, 0, fan_hours * 10/10,
                      fan_col, fan_note)

        # ── Load summary box ──────────────────────────────────────
        if title == "BEFORE":
            overnight_kwh = (280 + 333) * 8 / 1000
            overnight_cost = overnight_kwh * NIGHT_RATE_P / 100
            note = f"Fan runs 8 hrs → {333*8/1000:.1f} kWh/night"
            box_col = "#922B21"
        else:
            overnight_kwh = 280 * 8 / 1000 + 333 * 2 / 1000
            overnight_cost = overnight_kwh * NIGHT_RATE_P / 100
            note = f"Fan runs 2 hrs → {333*2/1000:.1f} kWh/night"
            box_col = "#1E8449"

        summary = mpatches.FancyBboxPatch((0.6, 1.4), 8.8, 1.85,
                                           boxstyle="round,pad=0.1",
                                           facecolor=box_col, edgecolor=accent,
                                           alpha=0.6, linewidth=1.5, zorder=3)
        ax.add_patch(summary)
        ax.text(5, 3.05, note, ha="center", fontsize=9,
                color="white", zorder=4, fontstyle="italic")
        ax.text(5, 2.65, f"Overnight energy used: {overnight_kwh:.2f} kWh",
                ha="center", fontsize=9.5, color="white", zorder=4)
        ax.text(5, 2.25, f"Overnight cost (E7 rate): {overnight_cost*100:.1f}p  /  £{overnight_cost:.3f}",
                ha="center", fontsize=9.5, color="white", zorder=4)
        ax.text(5, 1.72,
                f"Annual (fan nights ~250/yr): £{overnight_cost*250:.0f}",
                ha="center", fontsize=10, fontweight="bold", color=accent, zorder=4)

    # Saving callout between panels
    fan_before_cost = 333 * 8 / 1000 * NIGHT_RATE_P / 100 * 250
    fan_after_cost  = 333 * 2 / 1000 * NIGHT_RATE_P / 100 * 250
    saved = fan_before_cost - fan_after_cost
    fig.text(0.5, 0.5, f"Annual\nsaving\n£{saved:.0f}",
             ha="center", va="center", fontsize=14,
             fontweight="bold", color="#F1C40F",
             bbox=dict(boxstyle="round,pad=0.4", facecolor="#1E2A3A",
                       edgecolor="#F1C40F", linewidth=2))

    plt.suptitle("Home energy — fan heater timer: before vs after",
                 fontsize=15, color="white", y=1.01)
    plt.tight_layout(rect=[0, 0, 1, 1])
    plt.savefig("schematic.png", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print("Saved schematic.png")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading data …")
    baseload = load_baseload()
    gaming   = load_gaming()
    print(f"  {len(baseload)} half-hour slots, {len(gaming)} nightly records\n")

    print("Generating charts …")
    chart_time_of_day(baseload, gaming)
    chart_monthly(gaming)
    chart_daily_trend(gaming)
    chart_energy_cost(gaming)
    schematic()
    print("\nDone. All images saved to current directory.")


if __name__ == "__main__":
    main()
