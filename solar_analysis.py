#!/usr/bin/env python3
"""
Analyse solar generation and export meter readings alongside Octopus import data
to produce a complete home energy picture.

Inputs  : hardcoded meter readings + octopus_energy.csv (daily import/gas)
Outputs : console summary + 4 PNG charts
  chart_solar_generation.png  — generation per meter-reading period
  chart_energy_balance.png    — annual energy flow (sources vs uses)
  chart_monthly_balance.png   — month-by-month import / self-consumption / export
  chart_solar_sankey.png      — visual energy flow diagram
"""

import csv
import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
from collections import defaultdict

# ── Meter readings ────────────────────────────────────────────────────────────

# Cumulative generation meter (kWh)
GENERATION_READINGS = [
    ("2025-02-28", 37371.2),
    ("2025-05-30", 38438.6),
    ("2025-09-01", 39547.5),
    ("2025-12-01", 40043.3),
    ("2026-02-27", 40275.3),
]

# Cumulative export meter (kWh)
EXPORT_READINGS = [
    ("2021-06-30",    0.0),
    ("2026-05-03", 2426.0),
]

# ── Colours ───────────────────────────────────────────────────────────────────
GEN_COL    = "#F9A825"   # solar yellow
IMPORT_COL = "#1565C0"   # grid blue
EXP_COL    = "#00897B"   # export teal
SELF_COL   = "#43A047"   # self-consumption green
CONS_COL   = "#6A1B9A"   # total consumption purple
DARK_BG    = "#1E2A3A"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 150,
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_readings(readings):
    return [(datetime.date.fromisoformat(d), v) for d, v in readings]


def interpolate_gen(target_date, readings):
    """Estimate cumulative generation at target_date by linear interpolation."""
    dates = [r[0] for r in readings]
    vals  = [r[1] for r in readings]
    if target_date <= dates[0]:
        rate = (vals[1] - vals[0]) / (dates[1] - dates[0]).days
        return vals[0] - (dates[0] - target_date).days * rate
    if target_date >= dates[-1]:
        rate = (vals[-1] - vals[-2]) / (dates[-1] - dates[-2]).days
        return vals[-1] + (target_date - dates[-1]).days * rate
    for i in range(1, len(dates)):
        if dates[i-1] <= target_date <= dates[i]:
            frac = (target_date - dates[i-1]).days / (dates[i] - dates[i-1]).days
            return vals[i-1] + frac * (vals[i] - vals[i-1])


def gen_between(d1, d2, readings):
    return interpolate_gen(d2, readings) - interpolate_gen(d1, readings)


def load_daily_import(path="octopus_energy.csv"):
    """Return dict of date → kWh for electricity import."""
    data = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["type"] == "Electricity import":
                data[datetime.date.fromisoformat(r["date"])] = float(r["kwh"])
    return data


# ── Core calculations ─────────────────────────────────────────────────────────

def compute(gen_r, exp_r, daily_import):
    gen_readings = parse_readings(gen_r)
    exp_readings = parse_readings(exp_r)

    # Overall export rate from full export meter history
    total_exp  = exp_readings[-1][1] - exp_readings[0][1]
    exp_days   = (exp_readings[-1][0] - exp_readings[0][0]).days
    annual_exp = total_exp / exp_days * 365

    total_gen_yr = (gen_readings[-1][1] - gen_readings[0][1]) / \
                   (gen_readings[-1][0] - gen_readings[0][0]).days * 365
    export_rate  = annual_exp / total_gen_yr   # fraction of generation exported
    self_rate    = 1.0 - export_rate

    # Generation per measurement period
    periods = []
    for i in range(1, len(gen_readings)):
        d1, v1 = gen_readings[i-1]
        d2, v2 = gen_readings[i]
        kwh  = v2 - v1
        days = (d2 - d1).days
        periods.append({
            "label": f"{d1.strftime('%d %b %y')} → {d2.strftime('%d %b %y')}",
            "d1": d1, "d2": d2,
            "kwh": kwh, "days": days,
            "daily": kwh / days,
        })

    # Monthly energy balance using Octopus import data
    import_by_month = defaultdict(float)
    for d, kwh in daily_import.items():
        import_by_month[d.strftime("%Y-%m")] += kwh

    months_in_data = sorted(import_by_month)
    monthly = []
    for m in months_in_data:
        # Start/end of calendar month within data range
        y, mo = int(m[:4]), int(m[5:])
        d_start = datetime.date(y, mo, 1)
        if mo == 12:
            d_end = datetime.date(y+1, 1, 1)
        else:
            d_end = datetime.date(y, mo+1, 1)
        gen_kwh   = gen_between(d_start, d_end, gen_readings)
        imp_kwh   = import_by_month[m]
        exp_kwh   = gen_kwh * export_rate
        self_kwh  = gen_kwh * self_rate
        total_kwh = imp_kwh + self_kwh
        monthly.append({
            "month": m,
            "label": datetime.date(y, mo, 1).strftime("%b %Y"),
            "import": imp_kwh,
            "generation": gen_kwh,
            "export": exp_kwh,
            "self_consumption": self_kwh,
            "total_consumption": total_kwh,
            "solar_fraction": self_kwh / total_kwh * 100 if total_kwh > 0 else 0,
        })

    # Whole-period summary (Octopus period)
    all_dates = sorted(daily_import)
    period_start, period_end = all_dates[0], all_dates[-1]
    period_days = (period_end - period_start).days + 1
    period_gen  = gen_between(period_start, period_end, gen_readings)
    period_imp  = sum(daily_import.values())
    period_exp  = period_gen * export_rate
    period_self = period_gen * self_rate
    period_cons = period_imp + period_self

    return {
        "periods":      periods,
        "monthly":      monthly,
        "export_rate":  export_rate,
        "self_rate":    self_rate,
        "annual_gen":   total_gen_yr,
        "annual_exp":   annual_exp,
        "annual_self":  total_gen_yr * self_rate,
        "period_start": period_start,
        "period_end":   period_end,
        "period_days":  period_days,
        "period_gen":   period_gen,
        "period_imp":   period_imp,
        "period_exp":   period_exp,
        "period_self":  period_self,
        "period_cons":  period_cons,
        "total_export_reading": total_exp,
    }


# ── Console report ────────────────────────────────────────────────────────────

def print_report(r):
    print("=" * 62)
    print("SOLAR GENERATION & EXPORT ANALYSIS")
    print("=" * 62)
    print("\n── GENERATION PERIODS ──────────────────────────────────")
    for p in r["periods"]:
        season = ""
        mid = p["d1"] + datetime.timedelta(days=p["days"]//2)
        if mid.month in (3,4,5):   season = "Spring"
        elif mid.month in (6,7,8): season = "Summer"
        elif mid.month in (9,10,11): season = "Autumn"
        else:                       season = "Winter"
        print(f"  {p['label']:<30}  {p['kwh']:>7.1f} kWh  "
              f"{p['daily']:>5.2f} kWh/day  [{season}]")

    print(f"\n── ANNUAL ESTIMATES ────────────────────────────────────")
    print(f"  Generation      : {r['annual_gen']:>7.0f} kWh/year")
    print(f"  Export          : {r['annual_exp']:>7.0f} kWh/year  ({r['export_rate']*100:.1f}% of gen)")
    print(f"  Self-consumption: {r['annual_self']:>7.0f} kWh/year  ({r['self_rate']*100:.1f}% of gen)")
    print(f"  Total export to date: {r['total_export_reading']:.0f} kWh  (Jun 2021 → May 2026)")

    print(f"\n── OCTOPUS PERIOD ({r['period_start']} → {r['period_end']}, "
          f"{r['period_days']} days) ──")
    print(f"  Grid import (measured)  : {r['period_imp']:>7.0f} kWh  "
          f"({r['period_imp']/r['period_days']:.1f} kWh/day)")
    print(f"  Solar generation (est.) : {r['period_gen']:>7.0f} kWh  "
          f"({r['period_gen']/r['period_days']:.2f} kWh/day)")
    print(f"  Self-consumption (est.) : {r['period_self']:>7.0f} kWh  "
          f"({r['period_self']/r['period_days']:.2f} kWh/day)")
    print(f"  Export (est.)           : {r['period_exp']:>7.0f} kWh  "
          f"({r['period_exp']/r['period_days']:.2f} kWh/day)")
    print(f"  Total consumption (est.): {r['period_cons']:>7.0f} kWh  "
          f"({r['period_cons']/r['period_days']:.1f} kWh/day)")
    print(f"  Solar self-sufficiency  : {r['period_self']/r['period_cons']*100:.1f}%")

    print(f"\n── MONTHLY BREAKDOWN ───────────────────────────────────")
    print(f"  {'Month':<10} {'Import':>8} {'Gen':>7} {'Self':>7} {'Export':>7} "
          f"{'Total':>8} {'Solar%':>7}")
    for m in r["monthly"]:
        print(f"  {m['label']:<10} {m['import']:>7.1f}  {m['generation']:>6.1f}  "
              f"{m['self_consumption']:>6.1f}  {m['export']:>6.1f}  "
              f"{m['total_consumption']:>7.1f}  {m['solar_fraction']:>6.1f}%")


# ── Chart 1: Generation periods ───────────────────────────────────────────────

def chart_generation(r):
    periods = r["periods"]
    labels  = [p["label"] for p in periods]
    kwh     = [p["kwh"]   for p in periods]
    daily   = [p["daily"] for p in periods]

    season_colors = []
    for p in periods:
        mid = p["d1"] + datetime.timedelta(days=p["days"]//2)
        m = mid.month
        if m in (3,4,5):   season_colors.append("#FFA726")   # spring orange
        elif m in (6,7,8): season_colors.append("#FFEE58")   # summer yellow
        elif m in (9,10,11): season_colors.append("#AB47BC") # autumn purple
        else:               season_colors.append("#42A5F5")  # winter blue

    fig, ax1 = plt.subplots(figsize=(12, 5))
    x = np.arange(len(labels))
    bars = ax1.bar(x, kwh, color=season_colors, alpha=0.85, edgecolor="white", linewidth=1)

    ax1.set_ylabel("Total generation per period (kWh)", color="black")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15, ha="right", fontsize=8.5)

    # Daily rate on secondary axis
    ax2 = ax1.twinx()
    ax2.plot(x, daily, color=GEN_COL, marker="o", lw=2, ms=8, zorder=5,
             label="Daily average (kWh/day)")
    ax2.set_ylabel("Average daily generation (kWh/day)", color=GEN_COL)
    ax2.tick_params(axis="y", colors=GEN_COL)

    # Bar labels
    for bar, k, d in zip(bars, kwh, daily):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 8,
                 f"{k:.0f} kWh", ha="center", fontsize=8.5, fontweight="bold")
        ax2.annotate(f"{d:.2f}", (bar.get_x() + bar.get_width()/2, d),
                     textcoords="offset points", xytext=(0, 10),
                     ha="center", fontsize=8, color=GEN_COL)

    # Season legend
    legend_patches = [
        mpatches.Patch(color="#FFA726", label="Spring"),
        mpatches.Patch(color="#FFEE58", label="Summer"),
        mpatches.Patch(color="#AB47BC", label="Autumn"),
        mpatches.Patch(color="#42A5F5", label="Winter"),
    ]
    ax1.legend(handles=legend_patches, loc="upper right", fontsize=8)
    ax1.set_title(
        f"Solar generation per meter-reading period\n"
        f"Annual avg: {r['annual_gen']:.0f} kWh/yr  |  "
        f"Export rate: {r['export_rate']*100:.1f}%  |  "
        f"Self-consumption: {r['self_rate']*100:.1f}%",
        fontsize=11)
    plt.tight_layout()
    plt.savefig("chart_solar_generation.png")
    plt.close()
    print("Saved chart_solar_generation.png")


# ── Chart 2: Annual energy balance ───────────────────────────────────────────

def chart_energy_balance(r):
    ag  = r["annual_gen"]
    ae  = r["annual_exp"]
    asc = r["annual_self"]
    # Estimate annual import from Octopus period (winter-heavy — scale up)
    # Use period data but note it's winter-biased
    ai  = r["period_imp"] / r["period_days"] * 365
    atc = ai + asc

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    # ── Left: Sources ──
    ax = axes[0]
    sources = [ag, ai]
    source_labels = [f"Solar generation\n{ag:.0f} kWh/yr", f"Grid import\n{ai:.0f} kWh/yr"]
    source_colors = [GEN_COL, IMPORT_COL]
    wedges, texts, autotexts = ax.pie(
        sources, labels=source_labels, colors=source_colors,
        autopct="%1.1f%%", startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 9},
    )
    for at in autotexts:
        at.set_fontweight("bold")
        at.set_fontsize(10)
    ax.set_title(f"Energy sources\n(total {ag+ai:.0f} kWh/yr)", fontsize=11)

    # ── Right: Uses ──
    ax2 = axes[1]
    uses = [asc, ae, ai]
    use_labels = [
        f"Self-consumed\n{asc:.0f} kWh/yr  ({r['self_rate']*100:.0f}% of solar)",
        f"Exported to grid\n{ae:.0f} kWh/yr  ({r['export_rate']*100:.0f}% of solar)",
        f"From grid\n{ai:.0f} kWh/yr",
    ]
    use_colors = [SELF_COL, EXP_COL, IMPORT_COL]
    wedges2, texts2, autotexts2 = ax2.pie(
        uses, labels=use_labels, colors=use_colors,
        autopct="%1.1f%%", startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 9},
    )
    for at in autotexts2:
        at.set_fontweight("bold")
        at.set_fontsize(10)
    ax2.set_title(f"Energy uses\n(total consumption {atc:.0f} kWh/yr)", fontsize=11)

    plt.suptitle("Annual home energy balance — estimated from meter readings",
                 fontsize=12, y=1.01)
    plt.tight_layout()
    plt.savefig("chart_energy_balance.png", bbox_inches="tight")
    plt.close()
    print("Saved chart_energy_balance.png")


# ── Chart 3: Monthly energy balance ──────────────────────────────────────────

def chart_monthly_balance(r):
    monthly = r["monthly"]
    labels  = [m["label"] for m in monthly]
    imports = [m["import"]           for m in monthly]
    selfs   = [m["self_consumption"] for m in monthly]
    exports = [m["export"]           for m in monthly]
    fracs   = [m["solar_fraction"]   for m in monthly]
    x       = np.arange(len(labels))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                    gridspec_kw={"height_ratios": [3, 1]})

    # Stacked bars: import + self-consumption = total consumption
    b1 = ax1.bar(x, imports, color=IMPORT_COL, alpha=0.85, label="Grid import (measured)")
    b2 = ax1.bar(x, selfs, bottom=imports, color=SELF_COL, alpha=0.85,
                 label="Solar self-consumption (estimated)")

    # Export as separate bar below
    b3 = ax1.bar(x - 0.3, exports, width=0.25, color=EXP_COL, alpha=0.75,
                 label="Exported to grid (estimated)")

    # Generation line
    gen_vals = [m["generation"] for m in monthly]
    ax1.plot(x, gen_vals, color=GEN_COL, marker="D", lw=2, ms=7,
             zorder=5, label="Solar generation (estimated)")

    # Value labels on stacked bars
    for i, (imp, sc, tot) in enumerate(zip(imports, selfs,
                                           [i+s for i,s in zip(imports, selfs)])):
        ax1.text(x[i], tot + 4, f"{tot:.0f}", ha="center", fontsize=7.5,
                 fontweight="bold", color="#333")

    ax1.set_ylabel("Energy (kWh)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=25, ha="right")
    ax1.legend(fontsize=8, loc="upper right")
    ax1.set_title("Monthly home energy balance  (Octopus import period)", fontsize=12)
    ax1.set_ylim(0)

    # Solar fraction bar
    colors_frac = [SELF_COL if f >= 10 else "#AAAAAA" for f in fracs]
    ax2.bar(x, fracs, color=colors_frac, alpha=0.85, edgecolor="white")
    for i, f in enumerate(fracs):
        ax2.text(x[i], f + 0.3, f"{f:.1f}%", ha="center", fontsize=8,
                 fontweight="bold", color=SELF_COL)
    ax2.set_ylabel("Solar fraction\n(% of consumption)", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=25, ha="right")
    ax2.set_ylim(0, max(fracs) * 1.5)
    ax2.axhline(r["period_self"]/r["period_cons"]*100, color=SELF_COL,
                lw=1, linestyle="--", alpha=0.6)

    plt.tight_layout()
    plt.savefig("chart_monthly_balance.png")
    plt.close()
    print("Saved chart_monthly_balance.png")


# ── Chart 4: Energy flow diagram ─────────────────────────────────────────────

def chart_solar_sankey(r):
    """Custom energy flow diagram (no external libs needed)."""
    ag   = r["annual_gen"]
    ae   = r["annual_exp"]
    asc  = r["annual_self"]
    ai   = r["period_imp"] / r["period_days"] * 365
    atc  = ai + asc

    fig, ax = plt.subplots(figsize=(13, 7))
    ax.set_facecolor(DARK_BG)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")
    ax.set_title("Annual home energy flow  (estimated from meter readings)",
                 fontsize=13, color="white", pad=12)

    def flow_box(x, y, w, h, label, value, unit, color, text_color="white"):
        ax.add_patch(mpatches.FancyBboxPatch((x, y), w, h,
                      boxstyle="round,pad=0.1", facecolor=color,
                      edgecolor="white", linewidth=1.5, zorder=3))
        ax.text(x + w/2, y + h/2 + 0.12, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color=text_color, zorder=4)
        ax.text(x + w/2, y + h/2 - 0.18, f"{value:.0f} {unit}",
                ha="center", va="center", fontsize=10, color=text_color, zorder=4)

    def arrow(x1, y1, x2, y2, color, label="", lw=6, alpha=0.6):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=color,
                                    lw=lw, alpha=alpha,
                                    connectionstyle="arc3,rad=0.0"))
        if label:
            mx, my = (x1+x2)/2, (y1+y2)/2
            ax.text(mx, my + 0.18, label, ha="center", fontsize=8,
                    color=color, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=DARK_BG,
                              edgecolor="none", alpha=0.7))

    # Source boxes (left)
    flow_box(0.3, 4.5, 2.2, 1.2, "Solar Panels", ag, "kWh/yr", "#1A6E8E")
    flow_box(0.3, 2.5, 2.2, 1.2, "National Grid", ai, "kWh/yr", "#B71C1C")

    # Middle box: home
    flow_box(3.9, 2.8, 2.2, 1.8, "Your Home", atc, "kWh/yr consumed", "#263544")

    # Output boxes (right)
    flow_box(7.5, 4.3, 2.2, 1.2, "Self-consumed", asc, "kWh/yr", SELF_COL)
    flow_box(7.5, 2.8, 2.2, 1.2, "Grid import", ai, "kWh/yr", IMPORT_COL)
    flow_box(7.5, 1.2, 2.2, 1.2, "Exported", ae, "kWh/yr", EXP_COL)

    # Arrows: sources → home
    arrow(2.5, 5.1, 3.9, 4.2, GEN_COL,
          f"Solar → home\n{asc:.0f} kWh/yr\n({r['self_rate']*100:.0f}% of solar)", lw=8)
    arrow(2.5, 3.1, 3.9, 3.3, "#EF5350",
          f"Grid → home\n{ai:.0f} kWh/yr", lw=12)

    # Arrow: solar → export
    arrow(2.5, 5.1, 7.5, 1.8, EXP_COL,
          f"Solar → export\n{ae:.0f} kWh/yr\n({r['export_rate']*100:.0f}% of solar)", lw=3)

    # Arrows: home → outputs
    arrow(6.1, 4.2, 7.5, 4.9, SELF_COL, lw=8)
    arrow(6.1, 3.3, 7.5, 3.4, IMPORT_COL, lw=12)

    # Key stats
    stats = [
        f"Self-sufficiency:  {asc/atc*100:.1f}%  of consumption from solar",
        f"Self-consumption: {r['self_rate']*100:.1f}%  of solar used in home",
        f"Total generated:  {r['total_export_reading']:.0f} kWh  exported since Jun 2021",
    ]
    for i, s in enumerate(stats):
        ax.text(5.0, 0.85 - i*0.35, s, ha="center", fontsize=8.5,
                color="#BDC3C7", zorder=4)

    plt.tight_layout()
    plt.savefig("chart_solar_sankey.png", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print("Saved chart_solar_sankey.png")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    daily_import = load_daily_import()
    r = compute(GENERATION_READINGS, EXPORT_READINGS, daily_import)
    print_report(r)
    print("\nGenerating charts …")
    chart_generation(r)
    chart_energy_balance(r)
    chart_monthly_balance(r)
    chart_solar_sankey(r)
    print("Done.")


if __name__ == "__main__":
    main()
