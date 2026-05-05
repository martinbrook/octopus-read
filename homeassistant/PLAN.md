# Home Assistant Energy Management — Plan

## Goal

Automate battery charging from the grid during cheap Economy 7 hours (00:30–07:30 at 10.28p/kWh) and during daytime solar excess periods, then discharge the battery to power office loads, reducing reliance on the grid at the day rate (27.43p/kWh). Provide a real-time energy flow dashboard.

## Architecture

```
Solar (SMA SB 3000HF) → DB → Grid → Octopus Home Mini
                                                  ├─ Tapo P110 ── EcoFlow Delta 2 Max ── Office loads
```

Key constraints:
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
| Octopus Home Mini | 5-minute whole-house consumption data |

### Software

| Integration | Source | Purpose |
|-------------|--------|---------|
| `habuild/haos-sbfspot` | HA Add-on Store | Bluetooth poll SMA inverter |
| `hassio-ecoflow-cloud` | HACS `tolwi/hassio-ecoflow-cloud` | EcoFlow sensors, switches, number entities |
| `tapo_p110` | HACS `sihks123/tapo_p110` | Tapo P110 LAN control |
| `HomeAssistant-OctopusEnergy` | HACS `BottlecapDave/HomeAssistant-OctopusEnergy` | Octopus tariff + 5-min consumption data |
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
├── configuration.yaml       # Main config: integrations, input numbers, recorder, Lovelace resources
├── secrets.yaml             # API keys, Tapo credentials, meter details (not committed to git)
├── sensors.yaml             # Template sensors: is_cheap_rate, excess_solar, divert_status, etc.
├── automations.yaml         # E7 start/end, solar diversion start/end, safety controls
├── dashboards/
│   └── energy-flow.yaml     # Lovelace dashboard: energy flow, gauges, entity lists, history graphs
└── DEPLOYMENT.md            # Step-by-step deployment guide
└── PLAN.md                  # This file
```

## Energy Economics (Daily Estimate)

| Phase | Energy (kWh) | Cost/Revenue (p) | Net (p) |
|-------|-------------|-------------------|---------|
| E7 charge | ~10 (4300 Wh usable, ~4.8 kWh stored at 85% eff) | 10.28p | –49 |
| Discharge to office | ~4.1 (4300 Wh usable, ~4.9 kWh output at 85% eff) | replaces 27.43p | +134 |
| Solar diversion (est.) | 1–2 kWh/day | earns ~8p export rate | +8–16 |
| **Net daily savings** | | | **~90–165p** |

## Implementation Steps

1. Reserve static IP for Tapo P110 in router DHCP
2. Create Tapo app-specific password in Tapo app
3. Install `habuild/haos-sbfspot` add-on, verify Bluetooth connection to SMA inverter
4. Install `hassio-ecoflow-cloud` via HACS, configure EcoFlow credentials via UI
5. Install `tapo_p110` via HACS, configure with LAN IP and app credentials
6. Install `HomeAssistant-OctopusEnergy` via HACS, verify consumption + tariff entities
7. Install `energy-flow-card-v2` and `button-card` via HACS
8. Copy config files to `~/.homeassistant/`, fill in secrets
9. Start/restart Home Assistant, verify entity IDs in Developer Tools > States
10. Import dashboard YAML
11. Enable automations, test each trigger manually
12. One-day monitoring pass — verify all Tapo transitions and dashboard displays
13. Tune thresholds based on observed behaviour

## Verification Checklist

- [ ] SBFspot connects to SMA inverter (check add-on logs)
- [ ] Tapo responds to on/off commands from HA UI
- [ ] EcoFlow shows real-time SOC, power, all sensors in Developer Tools > States
- [ ] Octopus shows current tariff rate matching Octopus app
- [ ] Home Mini consumption updates every 5 minutes
- [ ] All template sensors show numeric/boolean states (no "unknown")
- [ ] At 00:30: `is_cheap_rate` becomes true, Tapo turns on if battery < 90%
- [ ] At 07:30: `is_cheap_rate` becomes false, Tapo turns off
- [ ] Sunny day: excess > 100W triggers Tapo on (outside E7)
- [ ] Cloud cover: excess < 50W turns Tapo off
- [ ] Battery at 90%: Tapo turns off regardless of E7/solar
- [ ] Dashboard displays all entities with correct values and colours
- [ ] EcoFlow min_discharge_level = 20% (firmware-level protection)
