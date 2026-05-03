#!/usr/bin/env python3
"""
Parse SBFspot daily CSV files and produce a clean daily_solar.csv.

Run this on the machine where SBFspot stores its output, then copy
daily_solar.csv into the octopus-read directory for use by solar_analysis.py.

Usage:
    python3 parse_sbfspot.py [sbfspot_root_dir]

Default root: ~/inverter/sbfspot
Output:       daily_solar.csv in the current directory
"""

import csv
import sys
import os
import glob
import datetime
import re

SBFSPOT_DIR = os.path.expanduser("~/inverter/sbfspot")


def eu_float(s):
    """Parse a European-format number (comma decimal separator)."""
    return float(s.strip().replace(",", "."))


def parse_daily_file(path):
    """
    Parse one SBFspot daily CSV (MyPlant-YYYYMMDD.csv).

    Returns a dict with date, daily_kwh, peak_w, total_yield_kwh, or None
    if the file can't be parsed.
    """
    fname = os.path.basename(path)
    m = re.match(r"MyPlant-(\d{4})(\d{2})(\d{2})\.csv$", fname)
    if not m:
        return None
    date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    rows = []
    in_data = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("dd/MM/yyyy"):
                in_data = True
                continue
            if not in_data or not line:
                continue
            parts = line.split(";")
            if len(parts) < 3:
                continue
            try:
                total_kwh = eu_float(parts[1])
                power_kw  = eu_float(parts[2])
                rows.append((total_kwh, power_kw))
            except ValueError:
                continue

    if not rows:
        return None

    start_total = rows[0][0]
    end_total   = rows[-1][0]
    daily_kwh   = end_total - start_total
    peak_w      = max(r[1] for r in rows) * 1000

    return {
        "date":             date,
        "daily_kwh":        round(daily_kwh, 3),
        "peak_w":           round(peak_w),
        "total_yield_kwh":  end_total,
    }


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else SBFSPOT_DIR

    pattern = os.path.join(root, "*", "MyPlant-????????.csv")
    files   = sorted(glob.glob(pattern))

    if not files:
        sys.exit(f"No daily files found under {root}\n"
                 f"Looked for: {pattern}")

    print(f"Found {len(files)} daily files under {root}")

    results = []
    for path in files:
        row = parse_daily_file(path)
        if row is None:
            print(f"  SKIP (parse error): {os.path.basename(path)}")
            continue
        if row["daily_kwh"] < 0:
            print(f"  SKIP (negative yield): {os.path.basename(path)}")
            continue
        results.append(row)

    results.sort(key=lambda r: r["date"])

    out_path = "daily_solar.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "daily_kwh", "peak_w", "total_yield_kwh"])
        w.writeheader()
        w.writerows(results)

    # ── Summary ───────────────────────────────────────────────────────────────
    n          = len(results)
    total_kwh  = sum(r["daily_kwh"] for r in results)
    avg        = total_kwh / n if n else 0
    best       = max(results, key=lambda r: r["daily_kwh"]) if results else None
    worst      = min(results, key=lambda r: r["daily_kwh"]) if results else None

    print(f"\nWritten {n} days → {out_path}")
    print(f"\nPeriod  : {results[0]['date']} → {results[-1]['date']}  ({n} days)")
    print(f"Total   : {total_kwh:.1f} kWh")
    print(f"Average : {avg:.2f} kWh/day")
    if best:
        print(f"Best    : {best['date']}  {best['daily_kwh']:.3f} kWh  "
              f"(peak {best['peak_w']:.0f} W)")
    if worst:
        print(f"Worst   : {worst['date']}  {worst['daily_kwh']:.3f} kWh")

    # Lifetime total from the inverter counter
    if results:
        print(f"\nInverter lifetime total at end of last file: "
              f"{results[-1]['total_yield_kwh']:.3f} kWh")


if __name__ == "__main__":
    main()
