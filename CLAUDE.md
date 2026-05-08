# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Python scripts for fetching, analysing, and simulating home energy data from the Octopus Energy REST API. The project covers electricity import, solar generation, battery storage simulation, and before/after impact visualisation for a home with solar panels and an EcoFlow battery.

## Dependencies

- Python 3.9+
- `requests` — `pip install requests` (only runtime dependency)
- `matplotlib` and `numpy` — only needed for `create_charts.py` and `solar_analysis.py` (install via `pip install matplotlib numpy`)

No `requirements.txt`, `pyproject.toml`, or virtual environment — run scripts directly.

## Running the scripts (pipeline order)

Scripts are sequential — later scripts consume CSV output from earlier ones. Always run in order:

```bash
# 1. Fetch daily electricity/gas data from Octopus API
export OCTOPUS_API_KEY="sk_live_xxx"
export OCTOPUS_ACCOUNT="A-XXXXXXXX"
python3 octopus_energy.py --from 2025-11-26 --csv octopus_energy.csv

# 2. Analyse half-hourly baseload (calls Octopus API directly)
python3 analyse_baseload.py

# 3. Simulate battery discharging strategy
python3 simulate_battery.py --price 1750

# 4a. Solar generation & export analysis (reads octopus_energy.csv)
python3 solar_analysis.py

# 4b. Before/after comparison charts (reads baseload_analysis.csv + battery_simulation.csv)
python3 create_charts.py
```

## Key scripts and data flow

```
octopus_energy.py        → octopus_energy.csv     (daily import/export/gas totals)
analyse_baseload.py      → baseload_analysis.csv  (half-hourly kWh + solar flags)
                         → late_night_gaming.csv  (per-night high-usage flags)
simulate_battery.py      → battery_simulation.csv (half-hourly battery simulation)
solar_analysis.py        → 4 PNG charts (generation, balance, monthly, sankey)
create_charts.py         → 5 PNG charts (time-of-day, monthly, daily, savings, schematic)
parse_sbfspot.py         → daily_solar.csv        (from SBFspot inverter output)
```

## Key hardcoded values to update when adapting

- `octopus_energy.py` — `BASE_URL` (line 21), nothing else is location-specific
- `analyse_baseload.py` — `MPAN`, `SERIAL`, `LAT_RAD` (lines 14–16), analysis window dates (line 98)
- `simulate_battery.py` — battery spec, tariff rates (lines 30–55), E7 window, load estimates
- `solar_analysis.py` — `GENERATION_READINGS`, `EXPORT_READINGS` (lines 27–38)
- `create_charts.py` — tariff rates and baseload (lines 48–54) match `simulate_battery.py`

## Home Assistant Energy Management

The `homeassistant/` directory contains the Home Assistant configuration for real-time energy management:
automating EcoFlow battery charging via Economy 7 tariff and solar diversion, with a live energy flow dashboard.

- `homeassistant/configuration.yaml` — Integrations (Octopus, Tapo, SBFspot, EcoFlow, Shelly), input numbers, recorder, Lovelace resources
- `homeassistant/sensors.yaml` — Template sensors (is_cheap_rate, excess_solar, net_grid, home_consumption, battery status, divert_status)
- `homeassistant/automations.yaml` — E7 charging start/end, solar diversion, dynamic AC charge rate, safety controls
- `homeassistant/dashboards/energy-flow.yaml` — Lovelace dashboard YAML (energy flow card, gauges, entity lists, history graphs)
- `homeassistant/DEPLOYMENT.md` — Deployment guide
- `homeassistant/PLAN.md` — Project plan

Entity ID note: Shelly entity IDs contain a hex device ID that is unknown until install. The placeholder
`sensor.shelly_em_x_power` is used in sensors.yaml — replace with the actual entity from Developer Tools > States.

## Code style

- All scripts are standalone, no imports beyond the standard library + requests
- Scripts use the `if __name__ == "__main__": main()` idiom
- No tests, no linting configuration — each script is run interactively
- Charts use `matplotlib.use("Agg")` (non-interactive backend)
