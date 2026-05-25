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

## Daytime — Outside E7

### Dynamic AC Charge Rate

Runs when excess solar > 30W and battery < max_charge_soc. Sets EcoFlow AC charge rate proportional to excess solar:

| Excess Solar | AC Charge Rate | Notes |
|---|---|---|
| 30–300 W | 200 W | Small surplus |
| 300–500 W | 500 W | Moderate surplus |
| 500–1000 W | 1000 W | Strong surplus |
| 1000–1500 W | 1500 W | Very strong surplus |
| > 1500 W | 2000 W (capped) | Maximum charge rate |

Rate is `min(tier, excess_solar_watts)` — never charges from grid.

### Solar Diversion Start

Excess solar > 100W and Tapo off → **turn Tapo on**.

EcoFlow BMS handles the rest:
- Battery below max_charge_soc → charges battery
- Battery full → passes excess directly to office loads

### Solar Diversion End

Excess solar < 50W and Tapo on → **turn Tapo off**.

50W hysteresis gap prevents rapid toggling when excess solar hovers near 100W.

## Every 15 Minutes — Tapo State Recovery

Catches reboots or lost state:

- **E7 branch** — If E7 active + battery < max_charge_soc + Tapo off → turn on
- **Solar branch** — If NOT E7 + excess solar > 100W + Tapo off → turn on
- Otherwise → no action

## Safety — Low Battery Warning (Any Time)

If battery < min_discharge_soc (15%) → notification sent.

---

## Key Dependency: max_charge_soc

`input_number.max_charge_soc` is the single control point for the entire system:

| Automation | Uses max_charge_soc? | How |
|---|---|---|
| E7 Charging Start | Yes | Only fires when battery < max_charge_soc |
| E7 Smart Charge Target | Sets it | Dynamic value at 01:30, reset at 08:30 |
| E7 Charging End | Resets it | Always sets back to 80% |
| E7 Charging Full Stop | Yes | Stops when battery >= max_charge_soc - 2 |
| Dynamic AC Charge Rate | Yes | Only fires when battery < max_charge_soc |
| Tapo State Recovery | Yes | E7 branch checks battery < max_charge_soc |

The smart charge target sets it once at 01:30 and the E7 end automation resets it to 80% at 08:30.
