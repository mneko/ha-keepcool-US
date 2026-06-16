"""DataUpdateCoordinator for Keep Cool — unit-aware rebuild.

All internal computation (schedule, recommendations, thresholds) is done
in **°C** and **km/h**, regardless of the user's HA display-unit setting.
The coordinator converts incoming °F → °C and mph → km/h at the boundary
so schedule.py never needs to know about Imperial units.

Sensor entities report in the user's configured unit and let HA's native
unit-conversion handle dashboard display.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    DOMAIN,
    UPDATE_INTERVAL_MINUTES,
    CONF_WEATHER_ENTITY,
    CONF_COMFORT_TEMP,
    CONF_ROOMS,
    CONF_ROOM_NAME,
    CONF_ROOM_FACING,
    CONF_ROOM_BLIND_ENTITY,
    CONF_ROOM_AUTO_CONTROL,
    CONF_ROOM_NOTIFY_BLIND,
    NOTIFICATION_ID,
)
from .schedule import (
    Room,
    ScheduleEvent,
    compute_current_recommendation,
    compute_sun_exposure_per_room,
    compute_schedule_events,
    sun_hits_window,
)

_LOGGER = logging.getLogger(__name__)

# Conversion constants
_MPH_TO_KMH = 1.60934


class KeepCoolData:
    """Holds the current computed state."""

    recommendation: str = "comfortable"
    recommendation_reason: str = ""
    peak_temp_c: Optional[float] = None          # always °C (for schedule logic)
    outdoor_temp_c: Optional[float] = None        # always °C (for schedule logic)
    peak_temp_display: Optional[float] = None     # user's unit (for sensor state)
    outdoor_temp_display: Optional[float] = None  # user's unit (for sensor state)
    sun_exposure: dict[str, bool] = {}
    events_today: list[ScheduleEvent] = []
    events_tomorrow: list[ScheduleEvent] = []
    next_event: Optional[ScheduleEvent] = None
    is_celsius: bool = True


class KeepCoolCoordinator(DataUpdateCoordinator[KeepCoolData]):
    """Fetches weather data, computes the schedule, controls blinds."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.config_entry = config_entry
        self._weather_entity: str = config_entry.data[CONF_WEATHER_ENTITY]

        # Detect the user's unit system
        self._is_celsius: bool = self._detect_celsius()
        self._comfort_temp_c: float = self._to_celsius(
            config_entry.data[CONF_COMFORT_TEMP]
        )

        self._rooms: list[Room] = [
            Room(
                name=r[CONF_ROOM_NAME],
                facing=r[CONF_ROOM_FACING],
                blind_entity=r.get(CONF_ROOM_BLIND_ENTITY),
                auto_control_blinds=r.get(CONF_ROOM_AUTO_CONTROL, False),
                notify_blind=r.get(CONF_ROOM_NOTIFY_BLIND, False),
            )
            for r in config_entry.data.get(CONF_ROOMS, [])
        ]

        # Track previous sun exposure to detect changes
        self._prev_sun_exposure: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Unit helpers
    # ------------------------------------------------------------------

    def _detect_celsius(self) -> bool:
        """Return True if HA is configured for Celsius."""
        unit = self.hass.config.units.temperature_unit
        return str(unit) != "°F"

    def _to_celsius(self, temp: float) -> float:
        """Convert a temperature from the user's unit to °C."""
        if self._is_celsius:
            return float(temp)
        return TemperatureConverter.convert(float(temp), "°F", "°C")

    def _from_celsius(self, temp_c: float) -> float:
        """Convert °C to the user's display unit."""
        if self._is_celsius:
            return temp_c
        return TemperatureConverter.convert(temp_c, "°C", "°F")

    def _is_mph(self) -> bool:
        """Return True if wind speed from the weather entity is in mph."""
        weather_state = self.hass.states.get(self._weather_entity)
        if weather_state:
            wind_unit = weather_state.attributes.get("wind_speed_unit", "")
            return "mph" in str(wind_unit).lower()
        # Fallback: check HA's length unit
        return str(self.hass.config.units.length_unit) == "mi"

    def _wind_to_kmh(self, speed: float) -> float:
        """Convert wind speed to km/h if HA uses mph."""
        if self._is_mph():
            return float(speed) * _MPH_TO_KMH
        return float(speed)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sun_azimuth(self, _at: datetime) -> Optional[float]:
        """Current sun azimuth from sun.sun entity."""
        sun = self.hass.states.get("sun.sun")
        if not sun:
            return None
        return sun.attributes.get("azimuth")

    def _sun_elevation(self, _at: datetime) -> Optional[float]:
        sun = self.hass.states.get("sun.sun")
        if not sun:
            return None
        return sun.attributes.get("elevation")

    def _sun_next_rising(self) -> Optional[datetime]:
        sun = self.hass.states.get("sun.sun")
        if not sun:
            return None
        raw = sun.attributes.get("next_rising")
        return dt_util.parse_datetime(raw) if raw else None

    def _sun_next_setting(self) -> Optional[datetime]:
        sun = self.hass.states.get("sun.sun")
        if not sun:
            return None
        raw = sun.attributes.get("next_setting")
        return dt_util.parse_datetime(raw) if raw else None

    async def _fetch_forecast(self) -> list[dict[str, Any]]:
        """Call weather.get_forecasts and return hourly list."""
        try:
            response = await self.hass.services.async_call(
                WEATHER_DOMAIN,
                "get_forecasts",
                {"entity_id": self._weather_entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            return response.get(self._weather_entity, {}).get("forecast", [])
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not fetch weather forecast: %s", err)
            return []

    async def _control_blinds(self, sun_exposure: dict[str, bool]) -> None:
        """Control blinds: auto-close for rooms with auto_control, send
        notification for rooms with notify_blind only."""
        for room in self._rooms:
            if not room.blind_entity:
                continue
            exposed = sun_exposure.get(room.name, False)
            was_exposed = self._prev_sun_exposure.get(room.name, False)

            if room.auto_control_blinds:
                # Automatic control — close when sun hits, open when it leaves
                service = "close_cover" if exposed else "open_cover"
                await self.hass.services.async_call(
                    "cover",
                    service,
                    {"entity_id": room.blind_entity},
                    blocking=False,
                )
            elif room.notify_blind:
                # Manual blind — notify on state transitions only
                if exposed and not was_exposed:
                    # Sun just started hitting this window
                    await self._send_blind_notification(room, "close")
                elif not exposed and was_exposed:
                    # Sun just left this window
                    await self._send_blind_notification(room, "open")

    async def _send_blind_notification(self, room: Room, action: str) -> None:
        """Send a persistent notification for a manual blind action."""
        if action == "close":
            title = f"☀️ Close {room.name} blind"
            message = (
                f"The sun is now hitting your {room.facing}-facing window "
                f"in {room.name}. Close the blind to keep the room cool."
            )
        else:
            title = f"🌤️ Open {room.name} blind"
            message = (
                f"The sun has moved away from your {room.facing}-facing window "
                f"in {room.name}. You can open the blind again."
            )

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{NOTIFICATION_ID}_{room.name.lower().replace(' ', '_')}_{action}",
            },
            blocking=False,
        )

    async def _clear_blind_notifications(self) -> None:
        """Dismiss all Keep Cool blind notifications on startup/reload."""
        for room in self._rooms:
            if room.notify_blind and room.blind_entity:
                for action in ("close", "open"):
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "dismiss",
                        {
                            "notification_id": f"{NOTIFICATION_ID}_{room.name.lower().replace(' ', '_')}_{action}",
                        },
                        blocking=False,
                    )

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> KeepCoolData:
        data = KeepCoolData()

        # Re-detect unit system in case user changed HA settings
        self._is_celsius = self._detect_celsius()
        data.is_celsius = self._is_celsius
        self._comfort_temp_c = self._to_celsius(
            self.config_entry.data[CONF_COMFORT_TEMP]
        )

        # --- Current outdoor temperature ---
        weather_state = self.hass.states.get(self._weather_entity)
        if not weather_state:
            raise UpdateFailed(f"Weather entity {self._weather_entity} not found")

        raw_outdoor_temp = weather_state.attributes.get("temperature")
        if raw_outdoor_temp is not None:
            # Convert to °C for internal logic
            data.outdoor_temp_c = self._to_celsius(float(raw_outdoor_temp))
            # Keep display value in user's unit for sensor state
            data.outdoor_temp_display = float(raw_outdoor_temp)
        else:
            data.outdoor_temp_c = None
            data.outdoor_temp_display = None

        # --- Hourly forecast ---
        forecast = await self._fetch_forecast()

        now = dt_util.now()
        today = now.date()

        hourly_times: list[datetime] = []
        hourly_temps_c: list[float] = []          # always °C
        hourly_wind_speed_kmh: list[float] = []   # always km/h
        hourly_wind_dir: list[float] = []

        for entry in forecast:
            raw_time = entry.get("datetime")
            temp = entry.get("temperature")
            if raw_time is None or temp is None:
                continue
            t = dt_util.parse_datetime(raw_time)
            if t is None:
                continue
            hourly_times.append(t)
            hourly_temps_c.append(self._to_celsius(float(temp)))

            # Guard against None in wind fields (NWS returns null)
            wind_speed = entry.get("wind_speed")
            wind_bearing = entry.get("wind_bearing")
            hourly_wind_speed_kmh.append(
                self._wind_to_kmh(float(wind_speed) if wind_speed is not None else 0)
            )
            hourly_wind_dir.append(
                float(wind_bearing) if wind_bearing is not None else 0
            )

        # Today's peak temp (in °C for logic, in display unit for sensor)
        today_temps_c = [
            hourly_temps_c[i]
            for i, t in enumerate(hourly_times)
            if t.date() == today
        ]
        if today_temps_c:
            peak_c = max(today_temps_c)
            data.peak_temp_c = peak_c
            data.peak_temp_display = self._from_celsius(peak_c)
        else:
            data.peak_temp_c = None
            data.peak_temp_display = None

        # --- Current recommendation (all in °C) ---
        if data.outdoor_temp_c is not None:
            data.recommendation, data.recommendation_reason = (
                compute_current_recommendation(
                    data.outdoor_temp_c,
                    self._comfort_temp_c,
                    data.peak_temp_c,
                )
            )

        # --- Sun exposure per room ---
        az = self._sun_azimuth(now)
        el = self._sun_elevation(now)
        if az is not None and el is not None:
            data.sun_exposure = compute_sun_exposure_per_room(self._rooms, az, el)
        else:
            data.sun_exposure = {room.name: False for room in self._rooms}

        # --- Auto blind control + manual blind notifications ---
        await self._control_blinds(data.sun_exposure)
        # Save for next update's transition detection
        self._prev_sun_exposure = dict(data.sun_exposure)

        # --- Full schedule events (all temps in °C, wind in km/h) ---
        sunrise = self._sun_next_rising()
        sunset = self._sun_next_setting()

        data.events_today = compute_schedule_events(
            hourly_times=hourly_times,
            hourly_temps=hourly_temps_c,
            hourly_wind_speed=hourly_wind_speed_kmh,
            hourly_wind_dir=hourly_wind_dir,
            rooms=self._rooms,
            comfort_temp=self._comfort_temp_c,
            sun_azimuth_fn=self._sun_azimuth,
            sun_elevation_fn=self._sun_elevation,
            sunrise=sunrise,
            sunset=sunset,
        )

        # Also look for tomorrow's events so we never have
        # "unknown" for next-event late in the day
        tomorrow = (now + timedelta(days=1)).date()
        tomorrow_times = [t for t in hourly_times if t.date() == tomorrow]
        if tomorrow_times:
            data.events_tomorrow = compute_schedule_events(
                hourly_times=hourly_times,
                hourly_temps=hourly_temps_c,
                hourly_wind_speed=hourly_wind_speed_kmh,
                hourly_wind_dir=hourly_wind_dir,
                rooms=self._rooms,
                comfort_temp=self._comfort_temp_c,
                sun_azimuth_fn=self._sun_azimuth,
                sun_elevation_fn=self._sun_elevation,
                sunrise=sunrise,
                sunset=sunset,
            )
        else:
            data.events_tomorrow = []

        # Next upcoming event — today first, then tomorrow
        upcoming_today = [e for e in data.events_today if e.time > now]
        if upcoming_today:
            data.next_event = upcoming_today[0]
        elif data.events_tomorrow:
            data.next_event = data.events_tomorrow[0]
        else:
            data.next_event = None

        return data
