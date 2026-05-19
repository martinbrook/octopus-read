# Home Assistant Energy Management — Plan

## Goal

Automate battery charging from the grid during cheap Economy 7 hours (00:30–07:30 at 10.28p/kWh) and during daytime solar excess periods, then discharge the battery to power office loads, reducing reliance on the grid at the day rate (27.43p/kWh). Provide a real-time energy flow dashboard.

## Architecture

```
Solar (SMA SB 3000HF) → DB → Grid → Shelly EM 120A (CT1 = house main)
                                                  ├─ Tapo P110 ── EcoFlow Delta 2 Max ── Office loads
```

Key constraints:
- The Shelly EM 120A provides real-time net grid flow (positive = importing, negative = exporting) — this replaces the Octopus Home Mini as the primary power sensor
- The Octopus Home Mini integration is retained for potential future use but is not the source for real-time power data
- The EcoFlow is **not connected to the distribution board** — it only powers office loads plugged into its AC output sockets
- The Tapo P110 sits between the wall socket and the EcoFlow AC input, acting as the charge gate
- Solar diversion path: solar → SMA → grid export → Tapo → EcoFlow charges (uses export tariff, then re-discharges at a savings vs day rate)

## Components

### Hardware

| Item | Role |
|------|------|
| SMA SB 3000HF inverter (12 No Znsoline panels) | Solar generation, DB-wired, Bluetooth monitored via SBFspot |
| EcoFlow Delta 2 Max + 2x Extra batteries | 6.144 kWh total, powers office loads |
| Tapo P110 smart plug | Controls mains power to EcoFlow AC input |
| Shelly EM 120A | Real-time net grid flow (CT1 on house main) — primary power sensor |
| Octopus Home Mini | 5-minute consumption data — retained but not used for real-time power |

### Software

| Integration | Source | Purpose |
|-------------|--------|---------|
| `habuild/haos-sbfspot` | HA Add-on Store | Bluetooth poll SMA inverter |
| `hassio-ecoflow-cloud` | HACS `tolwi/hassio-ecoflow-cloud` | EcoFlow sensors, switches, number entities |
| `tapo_p100` | HACS `petretiandrea/tapo_p100` | Tapo P110 LAN control (UI-configured, no YAML) |
| `HomeAssistant-OctopusEnergy` | HACS `BottlecapDave/HomeAssistant-OctopusEnergy` | Octopus tariff rates + consumption data |
| `Shelly` (built-in) | Auto-discover via mDNS | Shelly EM 120A — net grid flow, voltage, current, energy |
| `energy-flow-card-v2` | HACS | Animated energy flow visualisation |
| `button-card` | HACS | Conditional formatting dashboard buttons |

## Strategy

### E7 Charging (00:30–07:30)

The Tapo is turned ON at 00:30 when the cheap rate starts, if the battery SOC is below 90%.
This charges the battery at up to 2400W from the grid at 10.28p/kWh, filling to ~90% (~4300 Wh usable).

The Tapo turns OFF at 07:30 when the cheap rate ends, or early if the battery reaches 90% first.

### Solar Diversion (daytime, non-E7)

When solar production exceeds home consumption by more than 100W, the Tapo is turned ON
so the EcoFlow charges from grid export revenue. This captures value from otherwise free solar.

When excess drops below 50W (cloud cover, hysteresis) or the battery reaches 90%, the Tapo turns OFF.

If the battery SOC drops below 25%, the diversion threshold is lowered to 50W to encourage recharge.

### Dynamic AC Charge Rate

The `Dynamic AC Charge Rate` automation sets the EcoFlow `AC Charging Power` number entity based on
excess solar (Shelly EM net grid + SBFspot solar):

| Excess Solar | AC Charge Rate | Grid Import | Notes |
|-------------|----------------|-------------|-------|
| 0–99 W      | ≤ 200 W       | 0 W         | Below threshold, no charge |
| 100–299 W   | ≤ 200 W       | 0 W         | Tier capped at excess solar |
| 300–499 W   | ≤ 500 W       | 0 W         | Tier capped at excess solar |
| 500–999 W   | ≤ 1000 W      | 0 W         | Tier capped at excess solar |
| 1000–1499 W | ≤ 1500 W      | 0 W         | Tier capped at excess solar |
| 1500+ W     | ≤ 2000 W      | 0 W         | Max tier, capped at excess solar |

Rate = `min(tier_value, excess_solar_watts)` — zero grid import guaranteed. Triggers when excess solar
crosses 30 W threshold, condition battery < 90%. Entity: `number.ecoflow_ecoflow_delta_2_max_ac_charging_power`

### Discharge

The EcoFlow discharges automatically to power office loads from its AC output sockets.
The firmware's `min_discharge_level = 20%` protects against deep discharge.

## Battery Targets

| Parameter | Value | Reason |
|-----------|-------|--------|
| Max charge SOC | 90% | Avoids slow last 10% of E7 charge, reduces degradation |
| Min discharge SOC | 20% | Firmware-level protection, preserves battery life |
| Usable capacity | ~4300 Wh | (90% – 20%) of 6144 Wh |
| Max charge rate | 2400W | EcoFlow firmware limit |
| Round-trip efficiency | ~85% | 92% charge × 92% discharge |

## Configuration Files

```
homeassistant/
├── energy_management.yaml   # Package: integrations, input numbers, recorder, non-template sensor
├── sensors.yaml             # Template sensors (included via template: !include)
├── automations.yaml         # E7 start/end, solar diversion, dynamic AC charge rate, safety
├── dashboards/
│   └── energy-flow.yaml     # Lovelace dashboard: energy flow, gauges, entity lists, history graphs
├── DEPLOYMENT.md            # Step-by-step deployment guide
└── PLAN.md                  # This file
```

Notes:
- `secrets.yaml` is no longer used — Tapo credentials are configured via the HA UI (tapo_p100 integration)
- `sensors.yaml` uses `template: !include` format (list of `- sensor:` blocks), not the deprecated `- platform: template` syntax
- `battery_stored_today_kwh` uses `platform: integration` and is defined in `energy_management.yaml`, not `sensors.yaml`

The `energy_management.yaml` package is loaded via `homeassistant: packages: energy: !include energy_management.yaml` in the existing `configuration.yaml`. This keeps the energy management setup separate from the existing Home Assistant configuration (TLS, default integrations, scripts, scenes).

## Energy Economics (Daily Estimate)

| Phase | Energy (kWh) | Cost/Revenue (p) | Net (p) |
|-------|-------------|-------------------|---------|
| E7 charge | ~10 (4300 Wh usable, ~4.8 kWh stored at 85% eff) | 10.28p | –49 |
| Discharge to office | ~4.1 (4300 Wh usable, ~4.9 kWh output at 85% eff) | replaces 27.43p | +134 |
| Solar diversion (est.) | 1–2 kWh/day | earns ~8p export rate | +8–16 |
| **Net daily savings** | | | **~90–165p** |

## Implementation Steps

1. Reserve static IP for Tapo P110 in router DHCP
2. Create Tapo app-specific password in Tapo app (Settings > Privacy > App Password)
3. Wire Shelly EM, CT1 clamp on house main feed (arrow toward house)
4. Install Shelly integration (built-in, auto-discovered via mDNS)
5. Verify Shelly EM readings: `sensor.shellyem_485519d6c52f_channel_1_power`, `_voltage` in Developer Tools > States
6. Install `habuild/haos-sbfspot` add-on, verify Bluetooth connection to SMA inverter
7. Install `hassio-ecoflow-cloud` via HACS, configure EcoFlow credentials via UI
8. Install `tapo_p100` via HACS, configure Tapo credentials via UI (no YAML config)
9. Install `HomeAssistant-OctopusEnergy` via HACS, configure API credentials via UI
10. Install `energy-flow-card-v2` and `button-card` via HACS
11. SCP config files to HA server: `energy_management.yaml`, `sensors.yaml`, `automations.yaml`, `dashboards/` to `/config/`
12. Add `homeassistant: packages: energy: !include energy_management.yaml` to existing `configuration.yaml` on server
13. Start/restart Home Assistant, verify entity IDs in Developer Tools > States
14. Import dashboard YAML
15. Find phone device ID (Settings > Devices & Services > Devices → `mobile_app_<name>`)
16. Update `notify.mobile_app_<your_phone>` in automations.yaml with actual device ID
17. Enable automations, test each trigger manually including Dynamic AC Charge Rate
18. One-day monitoring pass — verify all Tapo transitions, dynamic charge rate, and dashboard displays
19. Tune thresholds based on observed behaviour

## Verification Checklist

- [ ] Shelly EM installed, CT1 oriented toward house
- [ ] `sensor.shellyem_485519d6c52f_channel_1_power` shows correct net grid flow (positive = importing, negative = exporting)
- [ ] Shelly voltage matches mains (~230 V)
- [ ] SBFspot connects to SMA inverter (check add-on logs)
- [ ] Tapo responds to on/off commands from HA UI
- [ ] EcoFlow shows real-time SOC, power, all sensors in Developer Tools > States
- [ ] `number.ecoflow_ecoflow_delta_2_max_ac_charging_power` entity exists and accepts `set_value`
- [ ] Octopus shows current tariff rate matching Octopus app
- [ ] All template sensors show numeric/boolean states (no "unknown")
- [ ] `home_consumption_watts` shows reasonable values (~558 W night baseload)
- [ ] `excess_solar_watts` > 0 during export periods
- [ ] At 00:30: `is_cheap_rate` becomes true, Tapo turns on if battery < 90%
- [ ] At 07:30: `is_cheap_rate` becomes false, Tapo turns off
- [ ] Sunny day: excess > 100W triggers Tapo on (outside E7)
- [ ] Cloud cover: excess < 50W turns Tapo off
- [ ] Battery at 90%: Tapo turns off regardless of E7/solar
- [ ] Dynamic AC charge rate adjusts: always ≤ excess solar, zero grid import, max 2000 W
- [ ] No grid-import charging: excess < 50W → rate returns to 200W minimum
- [ ] Dashboard displays all entities with correct values and colours
- [ ] EcoFlow min_discharge_level = 20% (firmware-level protection)
