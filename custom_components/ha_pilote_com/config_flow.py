from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .const import (
    CONF_API_KEY,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CONSUMERS,
    CONF_GRID_ENTITY,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_PRODUCTION_ENTITY,
                default=d.get(CONF_PRODUCTION_ENTITY, ""),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(
                CONF_GRID_ENTITY,
                default=d.get(CONF_GRID_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Optional(
                CONF_BATTERY_ENTITY,
                default=d.get(CONF_BATTERY_ENTITY, ""),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Optional(
                CONF_BATTERY_SOC_ENTITY,
                default=d.get(CONF_BATTERY_SOC_ENTITY, ""),
            ): EntitySelector(EntitySelectorConfig(domain="sensor", device_class="battery")),
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
            vol.Optional(
                CONF_HA_URL,
                default=d.get(CONF_HA_URL, ""),
            ): TextSelector(TextSelectorConfig(type="url")),
            vol.Optional(
                CONF_HA_TOKEN,
                default=d.get(CONF_HA_TOKEN, ""),
            ): TextSelector(TextSelectorConfig(type="password")),
        }
    )


class HaPiloteComOptionsFlow(OptionsFlow):
    """Options flow pour gérer les consommateurs."""

    async def async_step_init(self, user_input=None):
        consumers = list(self.config_entry.options.get(CONF_CONSUMERS, []))
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_add_consumer()
            if action and action.startswith("remove:"):
                idx = int(action.split(":")[1])
                if 0 <= idx < len(consumers):
                    consumers.pop(idx)
                    return self.async_create_entry(data={CONF_CONSUMERS: consumers})
            return self.async_create_entry(data={CONF_CONSUMERS: consumers})

        options = [
            SelectOptionDict(value="add", label="Ajouter un consommateur"),
        ]
        for i, c in enumerate(consumers):
            options.append(
                SelectOptionDict(
                    value=f"remove:{i}",
                    label=f"Supprimer : {c['name']}",
                )
            )
        options.append(SelectOptionDict(value="done", label="Terminé"))

        cat_labels = {"ev_charger": "Borne de recharge", "heat_pump": "PAC", "pool": "Piscine", "hot_water": "Chauffe-eau", "appliance": "Électroménager", "other": "Autres"}
        desc = "Aucun consommateur configuré."
        if consumers:
            lines = [f"• {c['name']} [{cat_labels.get(c.get('category', 'other'), 'Autres')}] ({c['entity']})" for c in consumers]
            desc = "Consommateurs actuels :\n" + "\n".join(lines)

        return self.async_show_form(
            step_id="init",
            description_placeholders={"consumers_list": desc},
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="done"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_add_consumer(self, user_input=None):
        if user_input is not None:
            consumers = list(self.config_entry.options.get(CONF_CONSUMERS, []))
            consumers.append({
                "entity": user_input["consumer_entity"],
                "name": user_input["consumer_name"],
                "category": user_input.get("consumer_category", "other"),
            })
            return self.async_create_entry(data={CONF_CONSUMERS: consumers})

        return self.async_show_form(
            step_id="add_consumer",
            data_schema=vol.Schema(
                {
                    vol.Required("consumer_entity"): EntitySelector(
                        EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required("consumer_name"): TextSelector(
                        TextSelectorConfig(type="text")
                    ),
                    vol.Required("consumer_category", default="other"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="ev_charger", label="Borne de recharge"),
                                SelectOptionDict(value="heat_pump", label="Pompe à chaleur (PAC)"),
                                SelectOptionDict(value="pool", label="Piscine"),
                                SelectOptionDict(value="hot_water", label="Chauffe-eau"),
                                SelectOptionDict(value="appliance", label="Électroménager"),
                                SelectOptionDict(value="other", label="Autres"),
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )


class HaPiloteComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Pilote Com."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return HaPiloteComOptionsFlow()

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
            data_schema=_user_schema(),
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(self._get_reconfigure_entry().data)),
        )
