"""Config flow for Keep Cool."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_COMFORT_TEMP,
    CONF_ROOM_AUTO_CONTROL,
    CONF_ROOM_BLIND_ENTITY,
    CONF_ROOM_FACING,
    CONF_ROOM_NAME,
    CONF_ROOMS,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_TEMP,
    DOMAIN,
    FACING_OPTIONS,
)


class KeepCoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Step 1 — Weather entity + comfort temperature
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Verify the weather entity actually exists
            if not self.hass.states.get(user_input[CONF_WEATHER_ENTITY]):
                errors[CONF_WEATHER_ENTITY] = "weather_entity_not_found"
            else:
                self._data[CONF_WEATHER_ENTITY] = user_input[CONF_WEATHER_ENTITY]
                self._data[CONF_COMFORT_TEMP] = user_input[CONF_COMFORT_TEMP]
                return await self.async_step_rooms_menu()

        schema = vol.Schema(
            {
                vol.Required(CONF_WEATHER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=WEATHER_DOMAIN)
                ),
                vol.Required(
                    CONF_COMFORT_TEMP, default=DEFAULT_COMFORT_TEMP
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=35,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Step 2 — Rooms menu (loop: add rooms, then finish)
    # ------------------------------------------------------------------

    async def async_step_rooms_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu_options = ["add_room"]
        if self._rooms:
            menu_options.append("finish")

        return self.async_show_menu(
            step_id="rooms_menu",
            menu_options=menu_options,
        )

    # ------------------------------------------------------------------
    # Step 3 — Add a single room
    # ------------------------------------------------------------------

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            room: dict[str, Any] = {
                CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                CONF_ROOM_FACING: user_input[CONF_ROOM_FACING],
            }
            blind = user_input.get(CONF_ROOM_BLIND_ENTITY)
            if blind:
                room[CONF_ROOM_BLIND_ENTITY] = blind
                room[CONF_ROOM_AUTO_CONTROL] = user_input.get(
                    CONF_ROOM_AUTO_CONTROL, False
                )
            self._rooms.append(room)
            return await self.async_step_rooms_menu()

        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
                vol.Required(CONF_ROOM_FACING): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=FACING_OPTIONS,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_ROOM_BLIND_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=COVER_DOMAIN)
                ),
                vol.Optional(CONF_ROOM_AUTO_CONTROL, default=False): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="add_room", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------------
    # Step 4 — Finish: create the config entry
    # ------------------------------------------------------------------

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._data[CONF_ROOMS] = self._rooms
        return self.async_create_entry(
            title=f"Keep Cool ({self._data[CONF_WEATHER_ENTITY]})",
            data=self._data,
        )

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KeepCoolOptionsFlow(config_entry)


class KeepCoolOptionsFlow(OptionsFlow):
    """Handle options (comfort temp + room management)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._comfort_temp: float = config_entry.data.get(
            CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP
        )
        self._rooms: list[dict[str, Any]] = list(
            config_entry.data.get(CONF_ROOMS, [])
        )

    # ------------------------------------------------------------------
    # Step 1 — Comfort temperature
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._comfort_temp = user_input[CONF_COMFORT_TEMP]
            return await self.async_step_rooms_menu()

        schema = vol.Schema(
            {
                vol.Required(CONF_COMFORT_TEMP, default=self._comfort_temp): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=35,
                        step=0.5,
                        unit_of_measurement="°C",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)

    # ------------------------------------------------------------------
    # Step 2 — Rooms menu
    # ------------------------------------------------------------------

    async def async_step_rooms_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        menu_options = ["add_room", "finish"]
        if self._rooms:
            menu_options.insert(1, "remove_room")

        return self.async_show_menu(
            step_id="rooms_menu",
            menu_options=menu_options,
        )

    # ------------------------------------------------------------------
    # Step 3a — Add a room
    # ------------------------------------------------------------------

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            room: dict[str, Any] = {
                CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                CONF_ROOM_FACING: user_input[CONF_ROOM_FACING],
            }
            blind = user_input.get(CONF_ROOM_BLIND_ENTITY)
            if blind:
                room[CONF_ROOM_BLIND_ENTITY] = blind
                room[CONF_ROOM_AUTO_CONTROL] = user_input.get(
                    CONF_ROOM_AUTO_CONTROL, False
                )
            self._rooms.append(room)
            return await self.async_step_rooms_menu()

        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME): selector.TextSelector(),
                vol.Required(CONF_ROOM_FACING): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=FACING_OPTIONS,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_ROOM_BLIND_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=COVER_DOMAIN)
                ),
                vol.Optional(CONF_ROOM_AUTO_CONTROL, default=False): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="add_room", data_schema=schema)

    # ------------------------------------------------------------------
    # Step 3b — Remove a room
    # ------------------------------------------------------------------

    async def async_step_remove_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            name_to_remove = user_input["room"]
            self._rooms = [r for r in self._rooms if r[CONF_ROOM_NAME] != name_to_remove]
            return await self.async_step_rooms_menu()

        schema = vol.Schema(
            {
                vol.Required("room"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[r[CONF_ROOM_NAME] for r in self._rooms],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="remove_room", data_schema=schema)

    # ------------------------------------------------------------------
    # Step 4 — Save options
    # ------------------------------------------------------------------

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Merge updated values back into config entry data
        new_data = dict(self._config_entry.data)
        new_data[CONF_COMFORT_TEMP] = self._comfort_temp
        new_data[CONF_ROOMS] = self._rooms
        self.hass.config_entries.async_update_entry(
            self._config_entry, data=new_data
        )
        return self.async_create_entry(title="", data={})
