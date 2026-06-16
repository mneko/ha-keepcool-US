# Keep Cool — Home Assistant Integration

[![hacs_badge](https://p.kagi.com/proxy/HACS-Custom-orange.svg?c=EgGQfWtq44GRXgvj3b8hBf4CIYcYEO3VNPBYvFOygNkMTU1Y5BFY8RTPOcLukn7En1v1-wYcXJ4yI8E2IdMQdU-5WdOJ4kYMEVwHVG0b1W8%3D)](https://github.com/hacs/integration)

> Know when to open and close your windows to keep your home cool — without air conditioning.

Keep Cool reads your existing weather integration, watches the sun position, and tells you exactly when to open windows, close them before the heat builds up, and lower blinds when the sun is shining through a specific window. It can control smart blinds automatically **or** send you notifications so you can adjust manual blinds yourself.

---

## Features

- **Hourly temperature schedule** — computes open/close events from your weather forecast
- **Per-room sun tracking** — knows which direction each window faces and when the sun is on it
- **Automatic blind control** — optionally close a cover entity when direct sun hits the window
- **Manual blind notifications** — send a persistent notification when the sun hits or leaves a window, so you can adjust non-motorized blinds yourself
- **Unit-aware** — works correctly with both °C and °F Home Assistant configurations; comfort temperature slider adapts to your unit setting
- **HA entities** — exposes sensors you can use in dashboards, automations, and voice assistants

## Entities created

| Entity | Type | Description |
|---|---|---|
| `sensor.keep_cool_recommendation` | Sensor | `open` / `close` / `comfortable` with a reason attribute |
| `sensor.keep_cool_outdoor_temperature` | Sensor | Current outdoor temperature from your weather entity (in your HA unit) |
| `sensor.keep_cool_todays_peak_temperature` | Sensor | Forecast peak for today (in your HA unit) |
| `sensor.keep_cool_next_event` | Sensor | ISO timestamp of the next open/close/blind event, or `none_today` / `all_passed` |
| `binary_sensor.keep_cool_windows_open` | Binary sensor | `on` when the recommendation is to have windows open |
| `binary_sensor.<room>_sun_exposure` | Binary sensor | `on` when the sun is shining through that room's window |

## Requirements

- Home Assistant 2024.3 or newer
- A weather integration that provides **hourly forecasts** (e.g. Met.no, OpenWeatherMap, NWS, Tomorrow.io)
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
   - The slider automatically shows °C or °F to match your Home Assistant unit setting
3. Add one or more rooms:
   - **Room name** — e.g. "Bedroom"
   - **Window direction** — which compass direction the main window faces (N / NE / E … NW)
   - **Blind entity** *(optional)* — a `cover` entity for a smart blind on that window
   - **Auto-control blind** *(optional)* — if enabled, Keep Cool will close the blind automatically when direct sun hits the window and re-open it when the sun moves away
   - **Notify me to adjust the blind manually** *(optional)* — if enabled, Keep Cool will send a persistent notification when the sun starts hitting the window (close the blind) and when the sun leaves (open the blind). Choose this for non-motorized blinds.

You can add more rooms or change the comfort temperature at any time via **Configure** on the integration card.

## How it works

Keep Cool mirrors the logic of the [Keep Cool web app](https://keepcool.app):

1. **Comfort threshold** — when outdoor temp is more than 1 °C below your target, open windows; more than 1 °C above, close them. All internal computation uses °C; if your HA is configured for °F, values are converted automatically.
2. **Daily schedule** — from the hourly forecast it derives: a morning *open* event (at sunrise), a *close* event (when the temperature approaches your target), and an evening *re-open* event (once the temperature drops back down).
3. **Sun exposure** — using the `sun.sun` entity (azimuth + elevation) it determines which windows have direct sunlight right now and generates blind events accordingly.
4. **Auto blind control** — on every 15-minute update cycle, it calls `cover.close_cover` or `cover.open_cover` on any configured blind entities based on current sun exposure.
5. **Manual blind notifications** — for rooms where the blind is not motorized, Keep Cool sends a persistent notification:
   - ☀️ **Close \<room\> blind** — when the sun starts hitting the window
   - 🌤️ **Open \<room\> blind** — when the sun moves away from the window
   - Notifications use unique IDs per room so they don't stack up.

## Automation example

```yaml
alias: &quot;Close living room blind when sun hits&quot;
trigger:

- platform: state
    entity_id: binary_sensor.keep_cool_living_room_sun_exposure
    to: &quot;on&quot;
action:

- service: cover.close_cover
    target:
      entity_id: cover.living_room_blind
```

## Notification example (manual blinds)

If you've enabled "Notify me to adjust the blind manually" for a room, you don't need any automation — Keep Cool sends the notifications automatically. But if you want to forward them to your phone:

```yaml
alias: &quot;Forward Keep Cool blind notification to phone&quot;
trigger:

- platform: event
    event_type: call_service
    event_data:
      domain: persistent_notification
      service: create
action:

- service: notify.mobile_app_your_phone
    data:
      title: &quot;{{ trigger.event.data.service_data.title }}&quot;
      message: &quot;{{ trigger.event.data.service_data.message }}&quot;
```

## Bug fixes in this fork

The upstream Keep Cool integration has several issues for °F users and NWS weather data. This version includes the following fixes:

| Bug | Fix |
|---|---|
| `float() argument must be a string or a real number, not 'NoneType'` | Guard against `None` values in NWS wind_speed/wind_bearing forecast fields |
| Outdoor temperature displayed as °C when HA uses °F | Coordinator converts between °C (internal logic) and °F (display); sensors report in the user's unit |
| Recommendation logic treats °F values as °C | All internal computation runs in °C; coordinator converts incoming °F → °C and outgoing °C → °F |
| Wind speed assumed km/h when HA uses mph | Coordinator detects wind speed unit and converts mph → km/h before passing to schedule logic |
| Comfort temperature slider hardcoded to 10–35 °C | Slider range and unit label adapt to HA's temperature unit setting (50–95 °F or 10–35 °C) |
| "Comfort temperature (°C)" label shown to °F users | Label changed to "Comfort temperature" — the slider already shows the correct unit |
| Next event sensor shows `unknown` | Returns `none_today` or `all_passed` instead of `None`; coordinator looks ahead to tomorrow's events |
| No notification option for manual blinds | Added `notify_blind` per-room option that sends persistent notifications on sun transitions |

## Contributing

Issues and PRs welcome at [github.com/greghesp/ha-keepcool](https://github.com/greghesp/ha-keepcool).
