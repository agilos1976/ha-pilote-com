from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.selector import (
    BooleanSelector,
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
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CONSUMERS,
    CONF_GRID_ENTITY,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_METER_BATTERY_CHARGE,
    CONF_METER_BATTERY_DISCHARGE,
    CONF_METER_EXPORT,
    CONF_METER_IMPORT,
    CONF_METER_PRODUCTION,
    CONF_PRODUCTION_ENTITY,
    CONF_SUBTRACT_ENTITIES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    schema = {}

    prod = d.get(CONF_PRODUCTION_ENTITY)
    if prod:
        schema[vol.Optional(CONF_PRODUCTION_ENTITY, default=prod)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="power")
        )
    else:
        schema[vol.Optional(CONF_PRODUCTION_ENTITY)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="power")
        )

    schema[vol.Required(CONF_GRID_ENTITY, default=d.get(CONF_GRID_ENTITY))] = EntitySelector(
        EntitySelectorConfig(domain="sensor", device_class="power")
    )

    schema[vol.Required(CONF_GRID_IMPORT_POSITIVE, default=d.get(CONF_GRID_IMPORT_POSITIVE, True))] = BooleanSelector()

    bat = d.get(CONF_BATTERY_ENTITY)
    if bat:
        schema[vol.Optional(CONF_BATTERY_ENTITY, default=bat)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="power")
        )
    else:
        schema[vol.Optional(CONF_BATTERY_ENTITY)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="power")
        )

    soc = d.get(CONF_BATTERY_SOC_ENTITY)
    if soc:
        schema[vol.Optional(CONF_BATTERY_SOC_ENTITY, default=soc)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="battery")
        )
    else:
        schema[vol.Optional(CONF_BATTERY_SOC_ENTITY)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="battery")
        )

    meter_prod = d.get(CONF_METER_PRODUCTION)
    if meter_prod:
        schema[vol.Optional(CONF_METER_PRODUCTION, default=meter_prod)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )
    else:
        schema[vol.Optional(CONF_METER_PRODUCTION)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )

    meter_imp = d.get(CONF_METER_IMPORT)
    if meter_imp:
        schema[vol.Optional(CONF_METER_IMPORT, default=meter_imp)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )
    else:
        schema[vol.Optional(CONF_METER_IMPORT)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )

    meter_exp = d.get(CONF_METER_EXPORT)
    if meter_exp:
        schema[vol.Optional(CONF_METER_EXPORT, default=meter_exp)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )
    else:
        schema[vol.Optional(CONF_METER_EXPORT)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )

    meter_bat_ch = d.get(CONF_METER_BATTERY_CHARGE)
    if meter_bat_ch:
        schema[vol.Optional(CONF_METER_BATTERY_CHARGE, default=meter_bat_ch)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )
    else:
        schema[vol.Optional(CONF_METER_BATTERY_CHARGE)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )

    meter_bat_dis = d.get(CONF_METER_BATTERY_DISCHARGE)
    if meter_bat_dis:
        schema[vol.Optional(CONF_METER_BATTERY_DISCHARGE, default=meter_bat_dis)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )
    else:
        schema[vol.Optional(CONF_METER_BATTERY_DISCHARGE)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="energy")
        )

    schema[vol.Required(CONF_BATTERY_CHARGE_POSITIVE, default=d.get(CONF_BATTERY_CHARGE_POSITIVE, True))] = BooleanSelector()

    schema[vol.Required(CONF_UPDATE_INTERVAL, default=d.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))] = NumberSelector(
        NumberSelectorConfig(min=5, max=1440, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="min")
    )
    schema[vol.Required(CONF_API_KEY, default=d.get(CONF_API_KEY))] = TextSelector(
        TextSelectorConfig(type="password")
    )
    schema[vol.Optional(CONF_HA_URL, default=d.get(CONF_HA_URL, ""))] = TextSelector(
        TextSelectorConfig(type="url")
    )
    schema[vol.Optional(CONF_HA_TOKEN, default=d.get(CONF_HA_TOKEN, ""))] = TextSelector(
        TextSelectorConfig(type="password")
    )

    return vol.Schema(schema)


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
            def _fmt(c):
                base = f"• {c['name']} [{cat_labels.get(c.get('category', 'other'), 'Autres')}] ({c['entity']})"
                subs = c.get(CONF_SUBTRACT_ENTITIES, [])
                if subs:
                    base += f" − {len(subs)} entité(s)"
                return base
            lines = [_fmt(c) for c in consumers]
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
            entry = {
                "entity": user_input["consumer_entity"],
                "name": user_input["consumer_name"],
                "category": user_input.get("consumer_category", "other"),
            }
            subtract = user_input.get(CONF_SUBTRACT_ENTITIES)
            if subtract:
                entry[CONF_SUBTRACT_ENTITIES] = subtract if isinstance(subtract, list) else [subtract]
            consumers.append(entry)
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
                    vol.Optional(CONF_SUBTRACT_ENTITIES): EntitySelector(
                        EntitySelectorConfig(domain="sensor", multiple=True)
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
            for key in (CONF_PRODUCTION_ENTITY, CONF_BATTERY_ENTITY, CONF_BATTERY_SOC_ENTITY, CONF_METER_PRODUCTION, CONF_METER_IMPORT, CONF_METER_EXPORT, CONF_METER_BATTERY_CHARGE, CONF_METER_BATTERY_DISCHARGE):
                user_input.setdefault(key, "")
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
            for key in (CONF_PRODUCTION_ENTITY, CONF_BATTERY_ENTITY, CONF_BATTERY_SOC_ENTITY, CONF_METER_PRODUCTION, CONF_METER_IMPORT, CONF_METER_EXPORT, CONF_METER_BATTERY_CHARGE, CONF_METER_BATTERY_DISCHARGE):
                user_input.setdefault(key, "")
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(self._get_reconfigure_entry().data)),
        )
