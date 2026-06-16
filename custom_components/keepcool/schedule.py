"""
Schedule logic — Python port of the Keep Cool web app's schedule.ts.

All temperatures are in **°C** and wind speeds in **km/h**.
The coordinator is responsible for converting from the user's display
units before calling any function in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .const import (
    FACING_AZIMUTH,
    SUN_FACING_TOLERANCE,
    SUN_ELEVATION_MIN,
    CROSS_VENT_WIND_MIN_KMH,
    CROSS_VENT_ROOM_TOLERANCE,
)


@dataclass
class Room:
    name: str
    facing: str
    blind_entity: Optional[str] = None
    auto_control_blinds: bool = False


@dataclass
class ScheduleEvent:
    time: datetime
    type: str          # "open" | "close" | "blind" | "info"
    title: str
    reason: str
    rooms: list[str] = field(default_factory=list)


@dataclass
class DaySchedule:
    events: list[ScheduleEvent]
    peak_temp: Optional[float]
    current_recommendation: str   # "open" | "close" | "comfortable"
    recommendation_reason: str


def _facing_diff(azimuth: float, facing: str) -> float:
    """Angular difference between sun azimuth and a facing direction."""
    target = FACING_AZIMUTH[facing]
    diff = abs(azimuth - target) % 360
    return diff if diff <= 180 else 360 - diff


def sun_hits_window(sun_azimuth: float, sun_elevation: float, facing: str) -> bool:
    """True if the sun is currently shining through a window of the given facing."""
    if sun_elevation < SUN_ELEVATION_MIN:
        return False
    return _facing_diff(sun_azimuth, facing) <= SUN_FACING_TOLERANCE


def compute_current_recommendation(
    outdoor_temp: float,
    comfort_temp: float,
    forecast_peak: Optional[float],
) -> tuple[str, str]:
    """
    Returns (recommendation, reason) where recommendation is:
      "open"        — outdoor air is cooler, open up
      "close"       — outdoor is too warm, keep closed
      "comfortable" — outdoor matches comfort target, hold

    All values in °C. Reason strings use °C with the degree symbol.
    """
    if outdoor_temp < comfort_temp - 1:
        gap = round(comfort_temp - outdoor_temp, 1)
        return (
            "open",
            f"Outside is {gap}°C cooler than your {round(comfort_temp)}°C target — let the cool air in",
        )
    if outdoor_temp > comfort_temp + 1:
        gap = round(outdoor_temp - comfort_temp, 1)
        reason = f"Outside is {gap}°C above your {round(comfort_temp)}°C target — keep windows closed"
        if forecast_peak and forecast_peak > comfort_temp:
            reason += f" (peaks at {round(forecast_peak)}°C)"
        return "close", reason
    return (
        "comfortable",
        f"Outside temperature is near your {round(comfort_temp)}°C target",
    )


def compute_sun_exposure_per_room(
    rooms: list[Room],
    sun_azimuth: float,
    sun_elevation: float,
) -> dict[str, bool]:
    """Returns {room_name: is_sun_hitting} for every configured room."""
    return {
        room.name: sun_hits_window(sun_azimuth, sun_elevation, room.facing)
        for room in rooms
    }


def compute_schedule_events(
    hourly_times: list[datetime],
    hourly_temps: list[float],
    hourly_wind_speed: list[float],
    hourly_wind_dir: list[float],
    rooms: list[Room],
    comfort_temp: float,
    sun_azimuth_fn,          # callable(datetime) -> float | None
    sun_elevation_fn,         # callable(datetime) -> float | None
    sunrise: Optional[datetime],
    sunset: Optional[datetime],
) -> list[ScheduleEvent]:
    """
    Compute today's full event schedule, mirroring the web app's logic.
    All temperatures must be in °C, wind speeds in km/h.
    """
    events: list[ScheduleEvent] = []
    now = datetime.now().astimezone()
    today = now.date()

    # Filter to today's hours
    day_indices = [i for i, t in enumerate(hourly_times) if t.date() == today]
    if not day_indices:
        return events

    day_temps = [hourly_temps[i] for i in day_indices]
    peak_temp = max(day_temps)
    peak_idx = day_temps.index(peak_temp)

    if peak_temp <= comfort_temp:
        # Comfortable day — no events needed
        return events

    # --- Close event: shortly before peak ---
    close_candidates = [
        i for i in range(peak_idx)
        if day_temps[i] >= comfort_temp - 1
    ]
    close_hour_idx = close_candidates[0] if close_candidates else peak_idx
    close_time = hourly_times[day_indices[close_hour_idx]]
    events.append(ScheduleEvent(
        time=close_time,
        type="close",
        title="Close windows & doors",
        reason=f"Temperature reaching {round(comfort_temp)}°C — shut out the heat before it builds up",
    ))

    # --- Open events: morning (after sunrise) and evening (after peak) ---
    if sunrise:
        open_morning_time = sunrise
        events.append(ScheduleEvent(
            time=open_morning_time,
            type="open",
            title="Open windows",
            reason="Cool morning air — ventilate before the heat arrives",
        ))

    eve_candidates = [
        i for i in range(peak_idx + 1, len(day_temps))
        if day_temps[i] <= comfort_temp
    ]
    if eve_candidates:
        eve_time = hourly_times[day_indices[eve_candidates[0]]]
        events.append(ScheduleEvent(
            time=eve_time,
            type="open",
            title="Re-open windows",
            reason=f"Outside has cooled to {round(day_temps[eve_candidates[0]])}°C — safe to ventilate again",
        ))

    # --- Blind events: per room, when sun hits during the hot period ---
    hot_hours = {
        hourly_times[day_indices[i]]
        for i in range(close_hour_idx, len(day_temps))
        if day_temps[i] >= comfort_temp
    }

    for room in rooms:
        blind_times = []
        for t in sorted(hot_hours):
            az = sun_azimuth_fn(t)
            el = sun_elevation_fn(t)
            if az is not None and el is not None and sun_hits_window(az, el, room.facing):
                blind_times.append(t)

        if blind_times:
            events.append(ScheduleEvent(
                time=blind_times[0],
                type="blind",
                title=f"Close {room.name} blind",
                reason=f"Sun will be hitting your {room.facing}-facing window",
                rooms=[room.name],
            ))

    # --- Cross-ventilation info (wind speed in km/h) ---
    morning_wind_speeds = [
        hourly_wind_speed[day_indices[i]]
        for i in range(min(len(day_temps), 6))  # first 6 hours
    ]
    morning_wind = morning_wind_speeds[0] if morning_wind_speeds else 0
    morning_wind_dir = hourly_wind_dir[day_indices[0]] if day_indices else None

    if morning_wind >= CROSS_VENT_WIND_MIN_KMH and morning_wind_dir is not None:
        windward = [
            r.name for r in rooms
            if _facing_diff(morning_wind_dir, r.facing) <= CROSS_VENT_ROOM_TOLERANCE
        ]
        leeward = [
            r.name for r in rooms
            if _facing_diff((morning_wind_dir + 180) % 360, r.facing) <= CROSS_VENT_ROOM_TOLERANCE
        ]
        if windward and leeward:
            reason = f"Wind from {_wind_cardinal(morning_wind_dir)} at {round(morning_wind)} km/h — open {', '.join(windward)} to draw air through to {', '.join(leeward)}"
        elif rooms:
            reason = f"Wind at {round(morning_wind)} km/h — open opposite windows to create a cross-breeze"
        else:
            reason = None

        if reason and sunrise:
            events.append(ScheduleEvent(
                time=sunrise,
                type="info",
                title="Cross-ventilation opportunity",
                reason=reason,
            ))

    events.sort(key=lambda e: e.time)
    return events


def _wind_cardinal(degrees: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(degrees / 45) % 8]
