from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_API_KEY,
    CONF_BATTERY_ENTITY,
    CONF_GRID_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_PRODUCTION_ENTITY,
                default=d.get(CONF_PRODUCTION_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(
                CONF_GRID_ENTITY,
                default=d.get(CONF_GRID_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(
                CONF_BATTERY_ENTITY,
                default=d.get(CONF_BATTERY_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=d.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=24,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                ),
            ),
            vol.Required(
                CONF_API_KEY,
                default=d.get(CONF_API_KEY),
            ): TextSelector(TextSelectorConfig(type="password")),
        }
    )


class HaPiloteComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Pilote Com."""

    VERSION = 1
    _user_input: dict | None = None
    _is_reconfigure: bool = False

    def _format_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return "N/A"
        unit = state.attributes.get("unit_of_measurement", "")
        return f"{state.state} {unit}".strip()

    def _verify_placeholders(self) -> dict[str, str]:
        return {
            "production_entity": self._user_input[CONF_PRODUCTION_ENTITY],
            "production_value": self._format_state(self._user_input[CONF_PRODUCTION_ENTITY]),
            "grid_entity": self._user_input[CONF_GRID_ENTITY],
            "grid_value": self._format_state(self._user_input[CONF_GRID_ENTITY]),
            "battery_entity": self._user_input[CONF_BATTERY_ENTITY],
            "battery_value": self._format_state(self._user_input[CONF_BATTERY_ENTITY]),
        }

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._user_input = user_input
            self._is_reconfigure = False
            return self.async_show_menu(
                step_id="verify",
                menu_options=["save", "modify"],
                description_placeholders=self._verify_placeholders(),
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._user_input),
        )

    async def async_step_save(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if self._is_reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=self._user_input,
            )
        await self.async_set_unique_id(self._user_input[CONF_API_KEY])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="HA Pilote Com",
            data=self._user_input,
        )

    async def async_step_modify(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if self._is_reconfigure:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_user_schema(self._user_input),
            )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._user_input),
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._user_input = user_input
            self._is_reconfigure = True
            return self.async_show_menu(
                step_id="verify",
                menu_options=["save", "modify"],
                description_placeholders=self._verify_placeholders(),
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(self._get_reconfigure_entry().data)),
        )
