#!/usr/bin/env python3
"""
Fetch daily electricity import and export data from the Octopus Energy API.

Set these environment variables before running:
  OCTOPUS_API_KEY      - your API key (found in your Octopus account)
  OCTOPUS_ACCOUNT      - your account number (e.g. A-XXXXXXXX)

Usage:
  python3 octopus_energy.py [--days N] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
"""

import os
import sys
import argparse
import datetime
import requests


BASE_URL = "https://api.octopus.energy"


def api_get(path, api_key, params=None):
    """Make an authenticated GET request and return parsed JSON."""
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, auth=(api_key, ""), params=params, timeout=30)
    if resp.status_code == 401:
        sys.exit("Authentication failed — check your OCTOPUS_API_KEY.")
    if resp.status_code == 404:
        sys.exit(f"Not found: {url}")
    resp.raise_for_status()
    return resp.json()


def fetch_all_pages(path, api_key, params=None):
    """Collect all results across paginated responses."""
    results = []
    params = dict(params or {})
    params.setdefault("page_size", 1500)
    next_path = path
    while next_path:
        data = api_get(next_path, api_key, params)
        results.extend(data.get("results", []))
        next_url = data.get("next")
        if next_url:
            # Strip base URL so api_get can prepend it again
            next_path = next_url.replace(BASE_URL, "")
            params = {}  # next URL already carries its own query string
        else:
            next_path = None
    return results


def get_account(account_number, api_key):
    return api_get(f"/v1/accounts/{account_number}/", api_key)


def get_consumption(mpan_or_mprn, meter_serial, api_key, period_from, period_to, fuel="electricity"):
    if fuel == "electricity":
        path = f"/v1/electricity-meter-points/{mpan_or_mprn}/meters/{meter_serial}/consumption/"
    else:
        path = f"/v1/gas-meter-points/{mpan_or_mprn}/meters/{meter_serial}/consumption/"
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


def find_meters(account):
    """Return list of (mpan, serial, is_export) for electricity meters."""
    meters = []
    for prop in account.get("properties", []):
        for ep in prop.get("electricity_meter_points", []):
            mpan = ep["mpan"]
            is_export = ep.get("is_export", False)
            for m in ep.get("meters", []):
                meters.append((mpan, m["serial_number"], is_export))
    return meters


def main():
    parser = argparse.ArgumentParser(description="Fetch daily Octopus Energy usage and export data.")
    parser.add_argument("--days", type=int, default=30, help="Number of past days to fetch (default: 30)")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="Start date (overrides --days)")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="End date (default: today)")
    args = parser.parse_args()

    api_key = os.environ.get("OCTOPUS_API_KEY", "").strip()
    account_number = os.environ.get("OCTOPUS_ACCOUNT", "").strip()
    if not api_key:
        sys.exit("Set OCTOPUS_API_KEY environment variable to your Octopus API key.")
    if not account_number:
        sys.exit("Set OCTOPUS_ACCOUNT environment variable to your account number (e.g. A-XXXXXXXX).")

    today = datetime.date.today()
    period_to = args.date_to or today.isoformat()
    if args.date_from:
        period_from = args.date_from
    else:
        period_from = (today - datetime.timedelta(days=args.days)).isoformat()

    print(f"Fetching account details for {account_number}...")
    account = get_account(account_number, api_key)

    meters = find_meters(account)
    if not meters:
        sys.exit("No electricity meters found on this account.")

    import_meters = [(mpan, serial) for mpan, serial, export in meters if not export]
    export_meters = [(mpan, serial) for mpan, serial, export in meters if export]

    print(f"Period: {period_from} to {period_to}\n")

    # --- Import consumption ---
    for mpan, serial in import_meters:
        print(f"Electricity import — MPAN: {mpan}, Meter: {serial}")
        data = get_consumption(mpan, serial, api_key, period_from, period_to)
        if not data:
            print("  No data returned for this period.\n")
            continue
        rows = []
        total = 0.0
        for entry in data:
            date = entry["interval_start"][:10]
            kwh = round(entry["consumption"], 3)
            total += kwh
            rows.append((date, f"{kwh:.3f}"))
        print(format_table(rows, ["Date", "kWh"]))
        print(f"\n  Total: {total:.3f} kWh over {len(rows)} day(s)\n")

    # --- Export ---
    for mpan, serial in export_meters:
        print(f"Electricity export — MPAN: {mpan}, Meter: {serial}")
        data = get_consumption(mpan, serial, api_key, period_from, period_to)
        if not data:
            print("  No data returned for this period.\n")
            continue
        rows = []
        total = 0.0
        for entry in data:
            date = entry["interval_start"][:10]
            kwh = round(entry["consumption"], 3)
            total += kwh
            rows.append((date, f"{kwh:.3f}"))
        print(format_table(rows, ["Date", "kWh exported"]))
        print(f"\n  Total: {total:.3f} kWh over {len(rows)} day(s)\n")

    if not export_meters:
        print("No export meter found on this account.")


if __name__ == "__main__":
    main()
