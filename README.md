# Keep Cool — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

> Know when to open and close your windows to keep your home cool — without air conditioning.

Keep Cool reads your existing weather integration, watches the sun position, and tells you exactly when to open windows, close them before the heat builds up, and lower blinds when the sun is shining through a specific window. It can also control smart blinds automatically.

---

## Features

- **Hourly temperature schedule** — computes open/close events from your weather forecast
- **Per-room sun tracking** — knows which direction each window faces and when the sun is on it
- **Automatic blind control** — optionally close a cover entity when direct sun hits the window
- **HA entities** — exposes sensors you can use in dashboards, automations, and voice assistants

## Entities created

| Entity | Type | Description |
|---|---|---|
| `sensor.keep_cool_recommendation` | Sensor | `open` / `close` / `comfortable` with a reason attribute |
| `sensor.keep_cool_outdoor_temperature` | Sensor | Current outdoor temperature from your weather entity |
| `sensor.keep_cool_todays_peak_temperature` | Sensor | Forecast peak for today |
| `sensor.keep_cool_next_event` | Sensor | ISO timestamp of the next open/close/blind event |
| `binary_sensor.keep_cool_windows_open` | Binary sensor | `on` when the recommendation is to have windows open |
| `binary_sensor.<room>_sun_exposure` | Binary sensor | `on` when the sun is shining through that room's window |

## Requirements

- Home Assistant 2024.3 or newer
- A weather integration that provides **hourly forecasts** (e.g. Met.no, OpenWeatherMap, Météo-France)
- The built-in `sun` integration enabled (Settings → Devices & Services → Sun)

## Installation via HACS

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/greghesp/ha-keepcool` with category **Integration**
3. Find **Keep Cool** in the list and click **Download**
4. Restart Home Assistant

## Manual installation

1. Copy `custom_components/keepcool/` into your `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add integration** and search for **Keep Cool**
2. Select your weather entity and set your comfort temperature (the indoor target you want to maintain)
3. Add one or more rooms:
   - **Room name** — e.g. "Living room"
   - **Window direction** — which compass direction the main window faces (N / NE / E … NW)
   - **Blind entity** *(optional)* — a `cover` entity for a smart blind on that window
   - **Auto-control blind** *(optional)* — if enabled, Keep Cool will close the blind when direct sun hits the window and re-open it when the sun moves away

You can add more rooms or change the comfort temperature at any time via **Configure** on the integration card.

## How it works

Keep Cool mirrors the logic of the [Keep Cool web app](https://keepcool.app):

1. **Comfort threshold** — when outdoor temp is more than 1 °C below your target, open windows; more than 1 °C above, close them.
2. **Daily schedule** — from the hourly forecast it derives: a morning *open* event (at sunrise), a *close* event (when the temperature approaches your target), and an evening *re-open* event (once the temperature drops back down).
3. **Sun exposure** — using the `sun.sun` entity (azimuth + elevation) it determines which windows have direct sunlight right now and generates *close blind* events accordingly.
4. **Auto blind control** — on every 15-minute update cycle, it calls `cover.close_cover` or `cover.open_cover` on any configured blind entities based on current sun exposure.

## Automation example

```yaml
alias: "Close living room blind when sun hits"
trigger:
  - platform: state
    entity_id: binary_sensor.keep_cool_living_room_sun_exposure
    to: "on"
action:
  - service: cover.close_cover
    target:
      entity_id: cover.living_room_blind
```

## Contributing

Issues and PRs welcome at [github.com/greghesp/ha-keepcool](https://github.com/greghesp/ha-keepcool).
