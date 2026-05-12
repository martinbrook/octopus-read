# Home Assistant Energy Management — Deployment Guide

## Prerequisites

- Home Assistant running in a VM (already installed)
- SMA SB 3000HF inverter with Bluetooth (monitored via SBFspot)
- Tapo P110 smart plug (connected between wall socket and EcoFlow AC input)
- EcoFlow Delta 2 Max + 2x Extra batteries (6.144 kWh total)
- Shelly EM 120A on the house main (CT1 clamp measuring net grid flow)
- SMA inverter wired to the distribution board

## Step 1 — Install Integrations

Before starting Home Assistant, install these integrations:

### Add-ons (from HA Add-on Store)

| Add-on | Purpose |
|--------|---------|
| `habuild/haos-sbfspot` | Bluetooth polling of SMA SB 3000HF inverter |

### HACS Integrations

| Integration | Repository | Purpose |
|-------------|------------|---------|
| `hassio-ecoflow-cloud` | `tolwi/hassio-ecoflow-cloud` | EcoFlow sensors, switches, number entities |
| `tapo_p110` | `sihks123/tapo_p110` | Tapo P110 smart plug control |
| `HomeAssistant-OctopusEnergy` | `BottlecapDave/HomeAssistant-OctopusEnergy` | Octopus tariff rates and export rates |

### Built-in Integrations

| Integration | Purpose |
|-------------|---------|
| `Shelly` | Shelly EM 120A — power monitoring via CT clamps (auto-discovered via mDNS) |

### HACS Custom Cards

| Card | Repository | Purpose |
|------|------------|---------|
| `energy-flow-card-v2` | `custom:energy-flow-card-v2` | Animated energy flow visualisation |
| `button-card` | `custom:button-card` | Conditional formatting for diversion status |

## Step 2 — Shelly EM 120A Setup

1. Wire the Shelly EM 120A to the house main feed
2. Connect CT1 clamp around the live conductor (ensure it points toward the house, not the meter)
3. Power on the Shelly EM — it will appear on the network automatically via mDNS
4. In Home Assistant, go to **Settings > Devices & Services > Add Integration > Shelly**
5. The device should auto-discover. Confirm it appears in **Developer Tools > States** with:
   - `sensor.shelly_<hex_id>_power` — net grid flow (positive = importing, negative = exporting)
   - `sensor.shelly_<hex_id>_voltage` — mains voltage
   - `sensor.shelly_<hex_id>_current` — current draw
   - `sensor.shelly_<hex_id>_energy` — total energy

## Step 3 — Tapo Account Setup

1. Open the Tapo app
2. Go to **Settings > Privacy > App Password**
3. Create an app-specific password (do not use your main Tapo password)
4. Note your Tapo account email and the app-specific password

## Step 4 — Reserve Static IPs

- Reserve a **static IP** for the Tapo P110 in your router DHCP
- (Optional) Reserve a static IP for the Shelly EM if you access it by hostname
- Ensure the Tapo P110 and Home Assistant are on the same LAN (the Tapo integration uses LAN-based encrypted API)

## Step 3 — Tapo Account Setup

1. Open the Tapo app
2. Go to **Settings > Privacy > App Password**
3. Create an app-specific password (do not use your main Tapo password)
4. Note your Tapo account email and the app-specific password

## Step 4 — Configure Secrets

Copy the secrets template and fill in real values:

```bash
cp homeassistant/secrets.yaml ~/.homeassistant/secrets.yaml
```

Fill in the following real values:

```yaml
# Octopus Energy API
octopus_api_key: "PUT_YOUR_OCTOPUS_API_KEY_HERE"
octopus_account: "PUT_YOUR_OCTOPUS_ACCOUNT_HERE"
octopus_mpan: "1100021680150"
octopus_meter_serial: "PUT_YOUR_METER_SERIAL_HERE"

# Tapo P110
tapo_username: "PUT_YOUR_TAPO_EMAIL_HERE"
tapo_password: "PUT_YOUR_TAPO_APP_PASSWORD_HERE"
tapo_plug_ip: "PUT_YOUR_TAPO_PLUG_IP_HERE"
```

**Warning:** Do not commit `secrets.yaml` to git. It is already gitignored.

## Step 5 — Configure Main Home Assistant

Copy the main config and fragment files:

```bash
cp homeassistant/configuration.yaml ~/.homeassistant/configuration.yaml
cp homeassistant/sensors.yaml ~/.homeassistant/sensors.yaml
cp homeassistant/automations.yaml ~/.homeassistant/automations.yaml
cp -r homeassistant/dashboards ~/.homeassistant/dashboards
```

Update `configuration.yaml` if any YAML keys already exist (HA will complain about duplicates).
Only the integrations you actually need should be present — comment out unused ones.

## Step 6 — Start Home Assistant

Start or restart Home Assistant. Watch the logs for errors:

```bash
docker logs homeassistant    # if running in Docker
# or
journalctl -f -u home-assistant   # if running as a service
```

Look for:
- **Shelly EM** auto-discovered via mDNS with power sensors active
- **SBFspot addon** connecting to the SMA inverter via Bluetooth
- **EcoFlow cloud** successfully authenticated
- **Tapo P110** found on the network and responding
- **Octopus Energy** API responding with tariff data

## Step 7 — Verify Entity IDs

The entity IDs used in the YAML are based on common integration naming conventions.
After start, go to **Developer Tools > States** in the HA UI and verify:

| Expected entity | What to look for |
|-----------------|------------------|
| `sensor.shelly_<hex>_power` | Net grid flow (positive = importing, negative = exporting) |
| `sensor.shelly_<hex>_voltage` | Mains voltage (should be ~230 V) |
| `sensor.sbfspot_power` | Solar power in watts |
| `sensor.ecoflow_soc` | Battery state of charge (%) |
| `sensor.ecoflow_total_in_power` | Battery charge power (W) |
| `sensor.ecoflow_total_out_power` | Battery discharge power (W) |
| `switch.tapo_p110_power` | Tapo plug on/off |
| `sensor.octopus_energy_electricity_...` | Tariff rates, daily consumption |
| `sensor.net_grid_watts` | Net grid power (template sensor, should match Shelly) |
| `sensor.home_consumption_watts` | Home consumption (derived from Shelly + SBFspot) |
| `sensor.excess_solar_watts` | Excess solar (> 0 when exporting) |
| `sensor.is_cheap_rate` | Boolean true/false |
| `sensor.divert_status` | "idle" / "E7 charging" / "diverting" |
| `number.ecoflow_..._ac_charging_power` | AC charge rate slider (200–2400 W) |

If any entity names differ from the expected ones, update the entity IDs in `sensors.yaml`
and `automations.yaml` accordingly. Key places to check:
- Replace `sensor.shelly_<hex>_power` everywhere in `sensors.yaml` — it's referenced 4 times
- Replace the EcoFlow AC charge rate entity ID in `automations.yaml` — it's referenced 5 times

## Step 8 — Import the Dashboard

1. Go to **Configuration > Dashboards > Import Dashboard YAML**
2. Copy the contents of `dashboards/energy-flow.yaml`
3. Paste and save
4. Navigate to the new dashboard to verify all cards render correctly

## Step 9 — Test Automations

Manually trigger each automation to verify correct behaviour:

| Test | Expected Result |
|------|-----------------|
| Toggle `sensor.is_cheap_rate` to `true` | Tapo turns ON if battery < 90% |
| Toggle `sensor.is_cheap_rate` to `false` | Tapo turns OFF |
| Set battery SOC above 90% while Tapo ON | Tapo turns OFF |
| Set `sensor.excess_solar_watts` above 100 | Tapo turns ON (outside E7) |
| Set battery SOC below 25% with excess solar > 50W | Tapo turns ON |
| Set `sensor.excess_solar_watts` above 1500 (EcoFlow < 90%) | AC charge rate set to min(2000, excess_solar) — never exceeds excess |
| Set `sensor.excess_solar_watts` below 50 (EcoFlow < 90%) | AC charge rate drops to 200 W |

## Step 10 — One-Day Monitoring Pass

Run the system for one full day and verify:

- [ ] Shelly EM shows correct net grid values (compare with inverter app if possible)
- [ ] `net_grid_watts` template sensor matches Shelly EM reading
- [ ] `home_consumption_watts` shows reasonable values (baseload ~558 W at night)
- [ ] `excess_solar_watts` is > 0 during export periods
- [ ] Tapo turns ON at 00:30 (E7 start)
- [ ] Tapo turns OFF at 07:30 (E7 end)
- [ ] Battery charges during E7 window (check `sensor.ecoflow_total_in_power`)
- [ ] Excess solar during the day triggers Tapo ON
- [ ] AC charge rate adjusts automatically with excess solar levels
- [ ] Tapo turns OFF when cloud cover drops excess below 50W
- [ ] Dashboard displays all entities with correct values and colours
- [ ] No entities stuck in "unknown" state

## Step 11 — Tune Thresholds

After the monitoring pass, adjust these if needed:

| Parameter | Location | Default | Notes |
|-----------|----------|---------|-------|
| Max charge SOC | `input_number.max_charge_soc` | 90% | Lower to charge faster, higher to maximise capacity |
| Min discharge SOC | `input_number.min_discharge_soc` | 20% | EcoFlow firmware also enforces this |
| Solar diversion threshold | `input_number.solar_diversion_threshold` | 100 W | Increase if Tapo toggles too often |
| E7 start threshold | `sensors.yaml` line 21 | 30 min (00:30) | Adjust for BST/GMT if needed |
| AC charge tiers | `automations.yaml` | min(tier, excess_solar): 200/500/1000/1500/2000 W | Adjust tier thresholds or max as needed |

## Troubleshooting

### "unknown" state on template sensors
Check that all referenced source entities (Shelly, EcoFlow, Octopus, SBFspot, Tapo) show
real values in Developer Tools > States. Template sensors inherit "unknown" if any
source entity is unknown. Common culprits:
- Shelly EM entity name doesn't match `sensor.shelly_<hex>_power`
- SBFspot has lost connection to the SMA inverter
- EcoFlow cloud integration is offline

### Shelly EM readings seem wrong
- Check the CT clamp is oriented toward the house (arrow points to load, not source)
- Verify voltage reading matches mains (~230 V). If it's 110 V or 0, the Shelly may not be powered.
- If power reads ~180° out of phase, swap the CT clamp ends

### Tapo P110 not responding
- Verify the IP address in `secrets.yaml` matches the router reservation
- Check the Tapo integration logs — LAN-based API requires same-subnet connectivity
- Regenerate the app-specific password in the Tapo app if auth fails

### Octopus entity names too long
The Octopus entities include the MPAN and meter serial in their names.
Find the actual name in Developer Tools > States and use it consistently
across all YAML files.

### EcoFlow cloud integration offline
Check the EcoFlow cloud integration logs in HA. If the MQTT broker fails,
restart the integration. Ensure your EcoFlow account has cloud access enabled
in the EcoFlow app.

### AC charge rate not adjusting
- Confirm `number.ecoflow_..._ac_charging_power` exists in Developer Tools > States
- Check the `Dynamic AC Charge Rate` automation is enabled (blue toggle)
- Check the automation log: **Developer Tools > Automations** → look for errors
- The automation fires every time excess solar crosses the 30 W threshold — this is normal

### SBFspot not connecting via Bluetooth
- Verify a Bluetooth adapter is connected to the VM
- Check the SBFspot add-on logs for scanning/connecting messages
- The SMA inverter must be within range of the Bluetooth adapter
