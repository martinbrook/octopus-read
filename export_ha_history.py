"""Export Home Assistant sensor history as CSV for spreadsheet analysis.

Tracks battery charge rate, AC output, charge rate setting, grid feed power,
and excess solar to help diagnose oscillation in the solar diversion system.

Usage:
  python3 export_ha_history.py [/path/to/db] [hours] [output.csv]

Defaults:
  DB:     ~/.homeassistant/home-assistant_v2.db
  Hours:  24
  Output: stdout
"""

import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime


# Entity IDs to export — verify these match your actual entities
SENSORS = [
    ("sensor.delta_battery_charge_rate", "Bat_Charge_W"),
    ("sensor.delta_ac_out_power", "AC_Out_W"),
    ("number.delta_ac_charging_power", "Charge_Setting_W"),
    ("sensor.net_grid_watts", "Grid_W"),
    ("sensor.excess_solar_watts", "Excess_Solar_W"),
    ("sensor.target_charging_power", "Target_W"),
]


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "~/.homeassistant/home-assistant_v2.db"
    db_path = db_path.replace("~", str(__import__("pathlib").Path.home()))

    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    query = """
        SELECT entity_id, state, last_updated
        FROM states
        WHERE entity_id IN ({})
          AND last_updated >= datetime('now', '-{} hours')
        ORDER BY last_updated ASC
    """.format(", ".join("?" for _ in SENSORS), hours)

    cur.execute(query, [e[0] for e in SENSORS])
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No data found for requested sensors in the time window.")
        print("Check entity IDs in Developer Tools > States.")
        return

    # Group by entity and rounded minute, taking first value per interval
    data = defaultdict(dict)
    for entity_id, state_str, ts_str in rows:
        try:
            ts = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue
        minute_key = ts.replace(second=0, microsecond=0)
        if entity_id not in data[minute_key]:
            data[minute_key][entity_id] = (
                float(state_str) if state_str and state_str != "unknown" and state_str != "unavailable" else None
            )

    sorted_times = sorted(data.keys())

    out = sys.stdout
    if len(sys.argv) > 3:
        out = open(sys.argv[3], "w", newline="")

    writer = csv.writer(out)
    writer.writerow(["time_utc"] + [e[1] for e in SENSORS])

    for ts in sorted_times:
        row = [ts.strftime("%Y-%m-%d %H:%M:%S UTC")]
        for entity_id, _ in SENSORS:
            val = data[ts].get(entity_id, None)
            row.append(f"{val:.1f}" if val is not None else "")
        writer.writerow(row)

    if out is not sys.stdout:
        out.close()

    print(f"Wrote {len(sorted_times)} rows to {sys.argv[3] if len(sys.argv) > 3 else 'stdout'}", file=sys.stderr)
    print(f"Period: {sorted_times[0]} to {sorted_times[-1]} UTC")


if __name__ == "__main__":
    main()
