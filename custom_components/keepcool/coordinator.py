"""DataUpdateCoordinator for Keep Cool."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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


class KeepCoolData:
    """Holds the current computed state."""

    recommendation: str = "comfortable"
    recommendation_reason: str = ""
    peak_temp: Optional[float] = None
    outdoor_temp: Optional[float] = None
    sun_exposure: dict[str, bool] = {}
    events_today: list[ScheduleEvent] = []
    next_event: Optional[ScheduleEvent] = None


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
        self._comfort_temp: float = config_entry.data[CONF_COMFORT_TEMP]
        self._rooms: list[Room] = [
            Room(
                name=r[CONF_ROOM_NAME],
                facing=r[CONF_ROOM_FACING],
                blind_entity=r.get(CONF_ROOM_BLIND_ENTITY),
                auto_control_blinds=r.get(CONF_ROOM_AUTO_CONTROL, False),
            )
            for r in config_entry.data.get(CONF_ROOMS, [])
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sun_azimuth(self, _at: datetime) -> Optional[float]:
        """Current sun azimuth from sun.sun entity (ignores the time arg for now)."""
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
        """Call weather.get_forecasts (HA 2024.3+) and return hourly list."""
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
        """Open or close blind covers based on sun exposure, if auto-control is on."""
        for room in self._rooms:
            if not room.blind_entity or not room.auto_control_blinds:
                continue
            exposed = sun_exposure.get(room.name, False)
            service = "close_cover" if exposed else "open_cover"
            await self.hass.services.async_call(
                "cover",
                service,
                {"entity_id": room.blind_entity},
                blocking=False,
            )

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> KeepCoolData:
        data = KeepCoolData()

        # --- Current outdoor temperature ---
        weather_state = self.hass.states.get(self._weather_entity)
        if not weather_state:
            raise UpdateFailed(f"Weather entity {self._weather_entity} not found")

        outdoor_temp = weather_state.attributes.get("temperature")
        data.outdoor_temp = outdoor_temp

        # --- Hourly forecast ---
        forecast = await self._fetch_forecast()

        now = dt_util.now()
        today = now.date()

        hourly_times: list[datetime] = []
        hourly_temps: list[float] = []
        hourly_wind_speed: list[float] = []
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
            hourly_temps.append(float(temp))
            hourly_wind_speed.append(float(entry.get("wind_speed", 0)))
            hourly_wind_dir.append(float(entry.get("wind_bearing", 0)))

        # Today's peak temp
        today_temps = [
            hourly_temps[i]
            for i, t in enumerate(hourly_times)
            if t.date() == today
        ]
        data.peak_temp = max(today_temps) if today_temps else None

        # --- Current recommendation ---
        if outdoor_temp is not None:
            data.recommendation, data.recommendation_reason = (
                compute_current_recommendation(
                    float(outdoor_temp),
                    self._comfort_temp,
                    data.peak_temp,
                )
            )

        # --- Sun exposure per room ---
        az = self._sun_azimuth(now)
        el = self._sun_elevation(now)
        if az is not None and el is not None:
            data.sun_exposure = compute_sun_exposure_per_room(self._rooms, az, el)
        else:
            data.sun_exposure = {room.name: False for room in self._rooms}

        # --- Auto blind control ---
        await self._control_blinds(data.sun_exposure)

        # --- Full schedule events ---
        sunrise = self._sun_next_rising()
        sunset = self._sun_next_setting()

        data.events_today = compute_schedule_events(
            hourly_times=hourly_times,
            hourly_temps=hourly_temps,
            hourly_wind_speed=hourly_wind_speed,
            hourly_wind_dir=hourly_wind_dir,
            rooms=self._rooms,
            comfort_temp=self._comfort_temp,
            sun_azimuth_fn=self._sun_azimuth,
            sun_elevation_fn=self._sun_elevation,
            sunrise=sunrise,
            sunset=sunset,
        )

        # Next upcoming event
        upcoming = [e for e in data.events_today if e.time > now]
        data.next_event = upcoming[0] if upcoming else None

        return data
