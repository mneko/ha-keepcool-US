"""Sensor platform for Keep Cool."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KeepCoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KeepCoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KeepCoolRecommendationSensor(coordinator, entry),
            KeepCoolOutdoorTempSensor(coordinator, entry),
            KeepCoolPeakTempSensor(coordinator, entry),
            KeepCoolNextEventSensor(coordinator, entry),
        ]
    )


class _KeepCoolSensorBase(CoordinatorEntity[KeepCoolCoordinator], SensorEntity):
    """Base class shared by all Keep Cool sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Keep Cool",
            "manufacturer": "Keep Cool",
            "model": "Window & Blind Scheduler",
            "entry_type": "service",
        }


class KeepCoolRecommendationSensor(_KeepCoolSensorBase):
    """Current recommendation: open / close / comfortable."""

    _attr_translation_key = "recommendation"
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "recommendation")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.recommendation

    @property
    def extra_state_attributes(self) -> dict:
        return {"reason": self.coordinator.data.recommendation_reason}


class KeepCoolOutdoorTempSensor(_KeepCoolSensorBase):
    """Current outdoor temperature from the weather entity."""

    _attr_translation_key = "outdoor_temp"
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "outdoor_temp")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.outdoor_temp


class KeepCoolPeakTempSensor(_KeepCoolSensorBase):
    """Today's forecast peak temperature."""

    _attr_translation_key = "peak_temp"
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer-high"

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "peak_temp")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.peak_temp


class KeepCoolNextEventSensor(_KeepCoolSensorBase):
    """Time of the next scheduled event (open / close / blind)."""

    _attr_translation_key = "next_event"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_event")

    @property
    def native_value(self) -> str | None:
        evt = self.coordinator.data.next_event
        if evt is None:
            return None
        return evt.time.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        evt = self.coordinator.data.next_event
        if evt is None:
            return {}
        return {
            "type": evt.type,
            "title": evt.title,
            "reason": evt.reason,
            "rooms": evt.rooms,
        }
