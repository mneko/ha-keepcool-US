"""Binary sensor platform for Keep Cool — unit-aware rebuild."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOMS, CONF_ROOM_NAME, DOMAIN
from .coordinator import KeepCoolCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KeepCoolCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [
        KeepCoolWindowsOpenSensor(coordinator, entry),
    ]

    for room in entry.data.get(CONF_ROOMS, []):
        entities.append(
            KeepCoolRoomSunExposureSensor(coordinator, entry, room[CONF_ROOM_NAME])
        )

    async_add_entities(entities)


class _KeepCoolBinarySensorBase(
    CoordinatorEntity[KeepCoolCoordinator], BinarySensorEntity
):
    """Base class shared by all Keep Cool binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KeepCoolCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
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


class KeepCoolWindowsOpenSensor(_KeepCoolBinarySensorBase):
    """True when the recommendation is to have windows open."""

    _attr_translation_key = "windows_open"
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_icon = "mdi:window-open"

    def __init__(self, coordinator: KeepCoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "windows_open")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.recommendation == "open"


class KeepCoolRoomSunExposureSensor(_KeepCoolBinarySensorBase):
    """True when the sun is currently hitting a specific room's window."""

    _attr_device_class = BinarySensorDeviceClass.LIGHT
    _attr_icon = "mdi:sun-angle"

    def __init__(
        self,
        coordinator: KeepCoolCoordinator,
        entry: ConfigEntry,
        room_name: str,
    ) -> None:
        # Slug the room name for use in the unique ID
        slug = room_name.lower().replace(" ", "_")
        super().__init__(coordinator, entry, f"sun_exposure_{slug}")
        self._room_name = room_name
        self._attr_name = f"{room_name} sun exposure"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.sun_exposure.get(self._room_name, False)
