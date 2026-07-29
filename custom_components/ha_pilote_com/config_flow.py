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
    CONF_CONSUMPTION_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


class HaPiloteComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Pilote Com."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_API_KEY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="HA Pilote Com",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PRODUCTION_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Required(CONF_CONSUMPTION_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=24,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="h",
                        ),
                    ),
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type="password"),
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=user_input,
            )

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRODUCTION_ENTITY,
                        default=entry.data.get(CONF_PRODUCTION_ENTITY),
                    ): EntitySelector(
                        EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Required(
                        CONF_CONSUMPTION_ENTITY,
                        default=entry.data.get(CONF_CONSUMPTION_ENTITY),
                    ): EntitySelector(
                        EntitySelectorConfig(domain="sensor"),
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=entry.data.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
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
                        default=entry.data.get(CONF_API_KEY),
                    ): TextSelector(
                        TextSelectorConfig(type="password"),
                    ),
                }
            ),
        )
