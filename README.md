# Octopus Energy Data Tools

A set of Python scripts for fetching, analysing, and simulating home energy data
from the [Octopus Energy REST API](https://docs.octopus.energy/rest/guides/endpoints/).

---

## Requirements

- Python 3.9+
- `requests` library (`pip install requests`)

No other third-party dependencies are needed.

---

## Setup

Set two environment variables before running any script:

```bash
export OCTOPUS_API_KEY="sk_live_xxxxxxxxxxxxxxxxxxxx"
export OCTOPUS_ACCOUNT="A-XXXXXXXX"
```

| Variable | Where to find it |
|---|---|
| `OCTOPUS_API_KEY` | Octopus account → [Developer settings](https://octopus.energy/dashboard/developer/) |
| `OCTOPUS_ACCOUNT` | Top of your Octopus online account (format: `A-XXXXXXXX`) |

Your API key is used as the HTTP Basic Auth username with an empty password.
It gives read-only access to your own meter data.

---

## Scripts

### 1. `octopus_energy.py` — Fetch daily usage data

Fetches daily electricity import, electricity export (if registered), and gas
consumption from the Octopus API. Writes a CSV and prints a formatted table.

#### Usage

```bash
python3 octopus_energy.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--days N` | `30` | Fetch the last N days of data |
| `--from YYYY-MM-DD` | — | Start date (overrides `--days`) |
| `--to YYYY-MM-DD` | today | End date |
| `--csv FILE` | `octopus_energy.csv` | Output CSV filename |

#### Examples

```bash
# Last 30 days
python3 octopus_energy.py

# Last 90 days
python3 octopus_energy.py --days 90

# Full history from a specific date
python3 octopus_energy.py --from 2016-01-01

# Custom date range, custom output file
python3 octopus_energy.py --from 2025-01-01 --to 2025-12-31 --csv 2025.csv
```

#### Output CSV columns

| Column | Description |
|---|---|
| `date` | Calendar date (YYYY-MM-DD) |
| `type` | `Electricity import`, `Electricity export`, or `Gas` |
| `kwh` | Consumption in kWh for that day |
| `identifier` | MPAN (electricity) or MPRN (gas) meter point number |
| `serial` | Physical meter serial number |

#### Key variables (top of script)

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `https://api.octopus.energy` | Octopus API base URL |

---

### 2. `analyse_baseload.py` — Half-hourly baseload analysis

Fetches all half-hourly electricity consumption data and analyses it to estimate
your household baseload. Accounts for solar generation by calculating the sun's
elevation angle for your location and filtering out solar hours. Also produces a
time-of-day profile and per-night minimum table to identify always-on devices.

#### Usage

```bash
python3 analyse_baseload.py
```

No command-line arguments. The script fetches data directly from the API using
the environment variables above.

#### Output

- Printed report with overnight statistics, baseload estimate, monthly breakdown,
  and time-of-day profile
- `baseload_analysis.csv` — half-hourly records with solar flags and elevation angles
- `late_night_gaming.csv` — per-night deep-night averages flagged against baseload

#### Key variables (top of script)

| Variable | Default | Description |
|---|---|---|
| `MPAN` | `1100021680150` | Electricity meter point number |
| `SERIAL` | `21M0104038` | Electricity meter serial number |
| `LAT_RAD` | `52.4°N` | Latitude used for solar elevation (Kettering) |
| `BASE_URL` | `https://api.octopus.energy` | API base URL |

**Solar calculation variables** (in `solar_elevation()` and `is_solar_hour()`):

| Variable | Default | Description |
|---|---|---|
| `min_elevation` | `5.0°` | Minimum sun elevation to classify a slot as a solar period. Lower = more slots flagged as solar. |
| Longitude correction | `0.7°W` | Used in `solar_elevation()` to adjust solar noon for location |

**Analysis window** (in `main()`):

| Variable | Default | Description |
|---|---|---|
| `period_from` | `2025-11-26` | Start of data fetch (account move-in date) |
| `period_to` | `2026-05-02` | End of data fetch |
| Deep night window | `01:00–05:30 UTC` | Slots used for baseload estimation — when occupants are asleep and solar is zero |
| `BASELOAD_W` | `558` | 5th-percentile deep-night reading, used as the always-on floor |
| Gaming flag threshold | `700 W` | Deep-night average above this is flagged as a high-usage night |

#### Output CSV columns — `baseload_analysis.csv`

| Column | Description |
|---|---|
| `datetime_utc` | Slot start time in UTC |
| `kwh_per_half_hour` | Raw consumption reading from meter |
| `watts` | Equivalent average power (kWh × 2000) |
| `solar_period` | `yes` / `no` — whether the sun was above 5° elevation |
| `solar_elevation_deg` | Calculated sun angle in degrees |

#### Output CSV columns — `late_night_gaming.csv`

| Column | Description |
|---|---|
| `date` | Date of the deep-night window |
| `deep_night_avg_w` | Average watts between 01:00–05:30 UTC |
| `deep_night_max_w` | Highest half-hour reading in the window |
| `deep_night_min_w` | Lowest half-hour reading in the window |
| `extra_above_baseload_w` | `deep_night_avg_w − 558 W` (clamped to 0) |
| `flagged` | `yes` if deep-night average exceeded 700 W |

---

### 3. `simulate_battery.py` — Battery storage simulation

Simulates an EcoFlow Delta 2 Max + Extra Battery (4 kWh) charged from Economy 7
cheap-rate hours and estimated solar excess, powering the home office and gaming PC.
Uses the half-hourly import data from `baseload_analysis.csv` and the gaming-night
data from `late_night_gaming.csv`.

#### Usage

```bash
python3 simulate_battery.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--price £` | `1350` | Purchase price in £ — used to calculate payback period |
| `--csv FILE` | `battery_simulation.csv` | Output CSV filename |

#### Examples

```bash
# Run with default purchase price
python3 simulate_battery.py

# Compare payback at different prices
python3 simulate_battery.py --price 1200
python3 simulate_battery.py --price 1800
```

#### Key variables (top of script)

**Battery hardware:**

| Variable | Default | Description |
|---|---|---|
| `CAPACITY_WH` | `4096` | Total battery capacity in Wh (2 × 2,048 Wh units) |
| `CHARGE_EFF` | `0.92` | AC-to-stored efficiency (92%) |
| `DISCHARGE_EFF` | `0.92` | Stored-to-output efficiency (92%) — round-trip ≈ 85% |
| `MAX_CHARGE_W` | `2400` | Maximum AC charge rate in watts |
| `MAX_SOLAR_W` | `1000` | Maximum solar input in watts |

**Economy 7 tariff (Octopus OE-FIX-12M-25-11-08-B):**

| Variable | Default | Description |
|---|---|---|
| `NIGHT_RATE` | `10.28` | E7 cheap-rate unit price (p/kWh) |
| `DAY_RATE_1` | `30.93` | Day-rate unit price before 1 Apr 2026 (p/kWh) |
| `DAY_RATE_2` | `27.43` | Day-rate unit price from 1 Apr 2026 (p/kWh) |
| `RATE_CHANGE` | `2026-04-01` | Date the day rate changed |
| `E7_START` | `30` (mins) | E7 window start: 00:30 local UK time |
| `E7_END` | `450` (mins) | E7 window end: 07:30 local UK time |

> **Note:** E7 hours vary by meter programming and region. The East Midlands
> standard is 00:30–07:30 but check your meter information card or contact
> Octopus to confirm your exact window.

**Modelled office + gaming PC load:**

| Variable | Default | Description |
|---|---|---|
| `SERVER_W` | `150` | Home server always-on draw (W) |
| `NETWORK_W` | `30` | Router, switch, etc. always-on (W) |
| `PC_IDLE_W` | `100` | Gaming PC at idle (W) |
| `OFFICE_EXTRA_W` | `100` | Extra office gear (monitors, laptop) weekdays 09:00–18:00 (W) |

Gaming session loads (applied to evenings before each flagged deep-night date):

| Intensity flag | Extra load above idle | Session window |
|---|---|---|
| HIGH (`extra > 400 W`) | +450 W | 19:00–23:30 local |
| MODERATE (`200–400 W`) | +300 W | 19:00–22:30 local |
| LOW (`< 200 W`) | +180 W | 19:00–21:30 local |

**Solar excess estimation:**

| Variable | Default | Description |
|---|---|---|
| `BASELOAD_W` | `558` | Whole-house baseload (W) — when import drops below this during solar hours, the difference is treated as solar excess available for charging |

This is a **conservative** estimate: it only counts excess when the panels are
generating more than the entire house needs. Actual solar generation is likely
higher.

**Simulation strategy:**

- During E7 window: battery charges at up to 2,400 W from the cheap-rate grid.
  Load is served from the grid (also cheap).
- Outside E7: battery discharges to supply the office/gaming load first; grid
  covers any shortfall at the day rate.
- Solar charging occurs whenever solar elevation > 5° and import is below baseload.

#### Output CSV columns — `battery_simulation.csv`

| Column | Description |
|---|---|
| `datetime_utc` | Slot start time (UTC) |
| `soc_wh` | Battery state of charge at end of slot (Wh) |
| `load_w` | Modelled office + gaming load (W) |
| `battery_supply_w` | Load served from battery (W) |
| `grid_supply_w` | Load served from grid (W) |
| `e7_charge_w` | Power drawn from grid to charge battery (W) |
| `solar_charge_w` | Estimated solar power charging battery (W) |

---

## Data flow

```
Octopus Energy API
       │
       ▼
octopus_energy.py  ──────────────────►  octopus_energy.csv
       │                                 (daily totals)
       │
       ▼
analyse_baseload.py  ────────────────►  baseload_analysis.csv
                                         (half-hourly + solar flags)
                     ────────────────►  late_night_gaming.csv
                                         (per-night high-usage flags)
                            │
                            ▼
                   simulate_battery.py  ►  battery_simulation.csv
                                            (half-hourly simulation)
```

---

## Adapting for a different location

If you move or want to use these scripts elsewhere, update:

1. **`analyse_baseload.py`** — change `LAT_RAD` and the longitude correction
   inside `solar_elevation()` to match your location
2. **`analyse_baseload.py`** — update `MPAN` and `SERIAL` (or rely on
   `octopus_energy.py` auto-discovery from the account endpoint)
3. **`simulate_battery.py`** — update `E7_START` / `E7_END` if your Economy 7
   window differs from 00:30–07:30
4. **`simulate_battery.py`** — update `NIGHT_RATE`, `DAY_RATE_1/2`, `RATE_CHANGE`
   to match your tariff (fetch live from the Octopus API
   `/v1/products/<product>/electricity-tariffs/<tariff>/` endpoints)
