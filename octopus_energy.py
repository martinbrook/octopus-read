#!/usr/bin/env python3
"""
Fetch daily electricity (import/export) and gas data from the Octopus Energy API.

Set these environment variables before running:
  OCTOPUS_API_KEY      - your API key (found in your Octopus account)
  OCTOPUS_ACCOUNT      - your account number (e.g. A-XXXXXXXX)

Usage:
  python3 octopus_energy.py [--days N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--csv FILE]
"""

import os
import sys
import csv
import argparse
import datetime
import requests


BASE_URL = "https://api.octopus.energy"


def api_get(path, api_key, params=None):
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, auth=(api_key, ""), params=params, timeout=30)
    if resp.status_code == 401:
        sys.exit("Authentication failed — check your OCTOPUS_API_KEY.")
    if resp.status_code == 404:
        sys.exit(f"Not found: {url}")
    resp.raise_for_status()
    return resp.json()


def fetch_all_pages(path, api_key, params=None):
    results = []
    params = dict(params or {})
    params.setdefault("page_size", 1500)
    next_path = path
    while next_path:
        data = api_get(next_path, api_key, params)
        results.extend(data.get("results", []))
        next_url = data.get("next")
        if next_url:
            next_path = next_url.replace(BASE_URL, "")
            params = {}
        else:
            next_path = None
    return results


def get_account(account_number, api_key):
    return api_get(f"/v1/accounts/{account_number}/", api_key)


def get_consumption(identifier, meter_serial, api_key, period_from, period_to, fuel="electricity"):
    if fuel == "electricity":
        path = f"/v1/electricity-meter-points/{identifier}/meters/{meter_serial}/consumption/"
    else:
        path = f"/v1/gas-meter-points/{identifier}/meters/{meter_serial}/consumption/"
    params = {
        "period_from": period_from,
        "period_to": period_to,
        "group_by": "day",
        "order_by": "period",
    }
    return fetch_all_pages(path, api_key, params)


def format_table(rows, headers):
    col_widths = [max(len(str(r[i])) for r in ([headers] + rows)) for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    lines = [fmt.format(*headers), "-" * (sum(col_widths) + 2 * (len(headers) - 1))]
    for row in rows:
        lines.append(fmt.format(*row))
    return "\n".join(lines)


def find_electricity_meters(account):
    """Return list of (mpan, serial, is_export) for all electricity meters."""
    meters = []
    for prop in account.get("properties", []):
        for ep in prop.get("electricity_meter_points", []):
            mpan = ep["mpan"]
            is_export = ep.get("is_export", False)
            for m in ep.get("meters", []):
                meters.append((mpan, m["serial_number"], is_export))
    return meters


def find_gas_meters(account):
    """Return list of (mprn, serial) for all gas meters."""
    meters = []
    for prop in account.get("properties", []):
        for gp in prop.get("gas_meter_points", []):
            mprn = gp["mprn"]
            for m in gp.get("meters", []):
                meters.append((mprn, m["serial_number"]))
    return meters


def fetch_meter_data(label, identifier, serial, api_key, period_from, period_to, fuel="electricity"):
    print(f"Fetching {label} — {identifier}, Meter: {serial}...")
    data = get_consumption(identifier, serial, api_key, period_from, period_to, fuel)
    rows = []
    for entry in data:
        rows.append({
            "date": entry["interval_start"][:10],
            "kwh": round(entry["consumption"], 3),
            "type": label,
            "identifier": identifier,
            "serial": serial,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Fetch daily Octopus Energy data.")
    parser.add_argument("--days", type=int, default=30, help="Number of past days (default: 30)")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="Start date (overrides --days)")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="End date (default: today)")
    parser.add_argument("--csv", dest="csv_file", metavar="FILE", help="Write results to a CSV file")
    args = parser.parse_args()

    api_key = os.environ.get("OCTOPUS_API_KEY", "").strip()
    account_number = os.environ.get("OCTOPUS_ACCOUNT", "").strip()
    if not api_key:
        sys.exit("Set OCTOPUS_API_KEY environment variable.")
    if not account_number:
        sys.exit("Set OCTOPUS_ACCOUNT environment variable.")

    today = datetime.date.today()
    period_to = args.date_to or today.isoformat()
    period_from = args.date_from or (today - datetime.timedelta(days=args.days)).isoformat()

    print(f"Fetching account details for {account_number}...")
    account = get_account(account_number, api_key)
    print(f"Period: {period_from} to {period_to}\n")

    elec_meters = find_electricity_meters(account)
    gas_meters = find_gas_meters(account)

    all_rows = []

    # Electricity import
    for mpan, serial, is_export in elec_meters:
        label = "Electricity export" if is_export else "Electricity import"
        rows = fetch_meter_data(label, mpan, serial, api_key, period_from, period_to, "electricity")
        all_rows.extend(rows)

    if not any(not exp for _, _, exp in elec_meters):
        print("No electricity import meter found.")
    if not any(exp for _, _, exp in elec_meters):
        print("No electricity export meter found on this account.")

    # Gas
    for mprn, serial in gas_meters:
        rows = fetch_meter_data("Gas", mprn, serial, api_key, period_from, period_to, "gas")
        all_rows.extend(rows)

    if not gas_meters:
        print("No gas meter found on this account.")

    print()

    # Group and display by type
    types_seen = []
    for row in all_rows:
        if row["type"] not in types_seen:
            types_seen.append(row["type"])

    for t in types_seen:
        subset = [r for r in all_rows if r["type"] == t]
        total = sum(r["kwh"] for r in subset)
        unit = "kWh"
        table_rows = [(r["date"], f"{r['kwh']:.3f}") for r in subset]
        print(f"{t}")
        print(format_table(table_rows, ["Date", unit]))
        print(f"\n  Total: {total:.3f} kWh over {len(subset)} day(s)\n")

    # CSV output
    csv_file = args.csv_file or "octopus_energy.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "type", "kwh", "identifier", "serial"])
        for row in all_rows:
            writer.writerow([row["date"], row["type"], f"{row['kwh']:.3f}", row["identifier"], row["serial"]])
    print(f"Data written to {csv_file} ({len(all_rows)} rows)")


if __name__ == "__main__":
    main()
