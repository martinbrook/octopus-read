# Automation Logic — Home Assistant Energy Management

From just before E7 cheap rate through daytime solar operation.

---

## 00:21 — Night (outside E7)

E7 rate not yet active. Tapo off. Battery at whatever level daytime left it.

## 01:30 — E7 Cheap Rate Starts

Two automations fire simultaneously:

### E7 Smart Charge

A single automation that sets `max_charge_soc` and charges if battery is below target:

Reads `sensor.energy_production_today_2` (the SMA inverter forecast — at 01:30 this is tomorrow's forecast):

| Solar Forecast Today | max_charge_soc Set To | Tapo Action |
|---|---|---|
| > 15 kWh (sunny) | 25% | Turn on if battery < 25% |
| 8–15 kWh (moderate) | 50% | Turn on if battery < 50% |
| < 8 kWh (cloudy) | 80% | Turn on if battery < 80% |

If battery is already at or above the target, max_charge_soc is set but Tapo stays off — no E7 is used.

Sends a persistent notification with the value. Because this is a single automation, the charge check runs **after** max_charge_soc is set — no race condition.

## 01:30 – 08:30 — E7 Window

EcoFlow charges via Tapo at whatever rate it chooses (AC charging defaults to EcoFlow's built-in strategy).

## 08:30 — E7 Cheap Rate Ends

### E7 Charging End

- Turns Tapo off
- Resets `max_charge_soc` back to **80%** for next day
- Battery should be at the target level (25%, 50%, or 80%)

## Prerequisite: EcoFlow Charging Mode

**Important:** For the `Dynamic AC Charge Rate` automation to take effect, the EcoFlow must be set to **"Custom"** charging mode (via the device hardware switch or EcoFlow app).

- **Max mode** — the EcoFlow BMS ignores the AC charge rate setting and charges at its default rate (~1000 W). This causes the charge rate to exceed available excess solar, killing the surplus, turning the Tapo off, and creating an oscillation loop.
- **Custom mode** — the BMS respects the `AC Charging Power` number entity set by Home Assistant. The dynamic rate automation only works in this mode.

## Daytime — Outside E7

### Dynamic AC Charge Rate

Two mechanisms work together:

**Initial setting** — When Solar Diversion Start turns the Tapo on, the charge rate is set to `SMA_output / 2` (conservative starting point).

**Ongoing adjustment** — Every 2 minutes, the automation incrementally adjusts the charge rate:

```
charge_rate += 0.3 × (-grid_flow)
```

This matches your manual method: observe grid feed, adjust charge rate to eliminate it. The 2-minute timer + 10-second delay lets the EcoFlow settle before re-evaluating, preventing oscillation.

| Grid Feed | Adjustment per cycle | Notes |
|---|---|---|
| -500 W (exporting) | +150 W | Increase charge rate |
| -200 W (exporting) | +60 W | Small increase |
| 0 W (balanced) | 0 W | Equilibrium reached |
| +100 W (importing) | -30 W | Decrease charge rate |
| +300 W (importing) | -90 W | Large decrease |

**Why this works:** At equilibrium, `grid_flow = 0` — all solar is being used (house loads + EcoFlow charging) with zero grid import or export. The 0.3 gain ensures convergence without overshoot. The 2-minute interval is much longer than the EcoFlow's ramp time (~15s), so the system has time to settle before each adjustment.

The 200 minimum charge rate ensures some charging happens even when solar is marginal. The 1200 maximum prevents over-optimistic settings.

### Solar Diversion Start

SMA inverter output > 100W and Tapo off → **turn Tapo on**. Sets initial charge rate to `SMA_output / 2`.

EcoFlow BMS handles the rest:
- Battery below max_charge_soc → charges battery
- Battery full → passes excess directly to office loads

### Solar Diversion End

SMA inverter output < 50W and Tapo on → **turn Tapo off**. Resets charge rate to 200W (minimum).

50W hysteresis gap prevents rapid toggling when SMA output hovers near 100W.

## Every 15 Minutes — Tapo State Recovery

Catches reboots or lost state:

- **E7 branch** — If E7 active + battery < max_charge_soc + Tapo off → turn on
- **Solar branch** — If NOT E7 + SMA output > 100W + Tapo off → turn on
- Otherwise → no action

## Safety — Low Battery Warning (Any Time)

If battery < min_discharge_soc (15%) → notification sent.

---

## Key Dependency: max_charge_soc

`input_number.max_charge_soc` is the single control point for the entire system:

| Automation | Uses max_charge_soc? | How |
|---|---|---|
| E7 Smart Charge | Sets + checks | Sets dynamic value at 01:30, only turns Tapo on if battery < max_charge_soc |
| E7 Charging End | Resets it | Always sets back to 80% |
| E7 Charging Full Stop | Yes | Stops when battery >= max_charge_soc - 2 |
| Dynamic AC Charge Rate | Yes | Only fires when battery < max_charge_soc |
| Tapo State Recovery | Yes | E7 branch checks battery < max_charge_soc |

The smart charge target sets it once at 01:30 and the E7 end automation resets it to 80% at 08:30.
