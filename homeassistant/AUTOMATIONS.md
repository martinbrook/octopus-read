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

Runs when excess solar crosses above 400W and battery < max_charge_soc. Uses a **proportional controller**:

```
charge_rate = clamp(gain × excess_solar, 200, 1200)
```

With gain = 0.6, the charge rate naturally converges to a stable equilibrium where the EcoFlow's total AC draw matches available solar.

| Excess Solar | Charge Rate | Notes |
|---|---|---|
| 0–333 W | 200 W (minimum) | No meaningful surplus for charging |
| 333–500 W | 200–300 W | Small surplus |
| 500–833 W | 300–500 W | Moderate surplus |
| 833–1200 W | 500–720 W | Strong surplus |
| 1200–2000 W | 720–1200 W | Excellent surplus |
| > 2000 W | 1200 W (max) | Cap reached |

**Oscillation prevention:** The automation has a 10-second delay and only fires on significant solar changes (above 400W), not on every state change. This gives the EcoFlow time to ramp up (takes ~15s) before re-evaluating, matching the human approach of waiting for the system to settle before adjusting again.

Tune the gain: higher (0.7–0.8) = faster charge but may oscillate; lower (0.4–0.5) = slower charge but more stable.

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
| E7 Smart Charge | Sets + checks | Sets dynamic value at 01:30, only turns Tapo on if battery < max_charge_soc |
| E7 Charging End | Resets it | Always sets back to 80% |
| E7 Charging Full Stop | Yes | Stops when battery >= max_charge_soc - 2 |
| Dynamic AC Charge Rate | Yes | Only fires when battery < max_charge_soc |
| Tapo State Recovery | Yes | E7 branch checks battery < max_charge_soc |

The smart charge target sets it once at 01:30 and the E7 end automation resets it to 80% at 08:30.
