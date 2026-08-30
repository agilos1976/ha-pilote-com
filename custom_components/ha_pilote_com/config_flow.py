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
    CONF_EV_AMPS,
    CONF_EV_BRAND,
    CONF_EV_EASEE_STATUS,
    CONF_EV_PLUGGED,
    CONF_EV_POWER,
    CONF_EV_SWITCH,
    EV_BRAND_EASEE,
    EV_BRAND_GENERIC,
    EV_BRAND_NONE,
    CONF_GRID_ENTITY,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_METER_BATTERY_CHARGE,
    CONF_METER_BATTERY_DISCHARGE,
    CONF_METER_EXPORT,
    CONF_METER_IMPORT,
    CONF_METER_PRODUCTION,
    CONF_CONSUMER_POWER_ENTITY,
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
            EntitySelectorConfig(domain="sensor")
        )
    else:
        schema[vol.Optional(CONF_METER_PRODUCTION)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )

    meter_imp = d.get(CONF_METER_IMPORT)
    if meter_imp:
        schema[vol.Optional(CONF_METER_IMPORT, default=meter_imp)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )
    else:
        schema[vol.Optional(CONF_METER_IMPORT)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )

    meter_exp = d.get(CONF_METER_EXPORT)
    if meter_exp:
        schema[vol.Optional(CONF_METER_EXPORT, default=meter_exp)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )
    else:
        schema[vol.Optional(CONF_METER_EXPORT)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )

    meter_bat_ch = d.get(CONF_METER_BATTERY_CHARGE)
    if meter_bat_ch:
        schema[vol.Optional(CONF_METER_BATTERY_CHARGE, default=meter_bat_ch)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )
    else:
        schema[vol.Optional(CONF_METER_BATTERY_CHARGE)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )

    meter_bat_dis = d.get(CONF_METER_BATTERY_DISCHARGE)
    if meter_bat_dis:
        schema[vol.Optional(CONF_METER_BATTERY_DISCHARGE, default=meter_bat_dis)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )
    else:
        schema[vol.Optional(CONF_METER_BATTERY_DISCHARGE)] = EntitySelector(
            EntitySelectorConfig(domain="sensor")
        )

    schema[vol.Required(CONF_BATTERY_CHARGE_POSITIVE, default=d.get(CONF_BATTERY_CHARGE_POSITIVE, True))] = BooleanSelector()

    # --- Borne de recharge (facultatif) ---
    # Sans ces entites, le pilotage reste inactif : le plugin continue
    # d'envoyer ses mesures, mais n'ecrit rien sur la borne.
    #
    # La marque choisit le pilote. Chaque marque a ses propres commandes —
    # une Easee ne s'ecrit pas comme un simple interrupteur — et seuls les
    # champs de la marque retenue sont a remplir ; les autres sont ignores.
    schema[vol.Required(CONF_EV_BRAND, default=d.get(CONF_EV_BRAND, EV_BRAND_NONE))] = SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=EV_BRAND_NONE, label="Aucune borne pilotee"),
                SelectOptionDict(value=EV_BRAND_GENERIC, label="Borne generique (interrupteur + amperage)"),
                SelectOptionDict(value=EV_BRAND_EASEE, label="Easee"),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )
    # Les entites de la borne sont demandees a l'etape suivante, et
    # seulement celles que la marque retenue reclame : afficher des champs
    # qui seront ignores laisse croire qu'il faut les remplir.

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

    def __init__(self):
        self._edit_index: int | None = None

    async def async_step_init(self, user_input=None):
        consumers = list(self.config_entry.options.get(CONF_CONSUMERS, []))
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_add_consumer()
            if action and action.startswith("edit:"):
                idx = int(action.split(":")[1])
                if 0 <= idx < len(consumers):
                    self._edit_index = idx
                    return await self.async_step_edit_consumer()
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
                    value=f"edit:{i}",
                    label=f"Modifier : {c['name']}",
                )
            )
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
                if c.get(CONF_CONSUMER_POWER_ENTITY):
                    base += f" ⚡ live"
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
            power_ent = user_input.get(CONF_CONSUMER_POWER_ENTITY)
            if power_ent:
                entry[CONF_CONSUMER_POWER_ENTITY] = power_ent
            subtract = user_input.get(CONF_SUBTRACT_ENTITIES)
            if subtract:
                entry[CONF_SUBTRACT_ENTITIES] = subtract if isinstance(subtract, list) else [subtract]
            consumers.append(entry)
            return self.async_create_entry(data={CONF_CONSUMERS: consumers})

        return self.async_show_form(
            step_id="add_consumer",
            data_schema=self._consumer_schema(),
        )

    async def async_step_edit_consumer(self, user_input=None):
        consumers = list(self.config_entry.options.get(CONF_CONSUMERS, []))
        idx = self._edit_index
        if idx is None or idx >= len(consumers):
            return await self.async_step_init()

        if user_input is not None:
            entry = {
                "entity": user_input["consumer_entity"],
                "name": user_input["consumer_name"],
                "category": user_input.get("consumer_category", "other"),
            }
            power_ent = user_input.get(CONF_CONSUMER_POWER_ENTITY)
            if power_ent:
                entry[CONF_CONSUMER_POWER_ENTITY] = power_ent
            subtract = user_input.get(CONF_SUBTRACT_ENTITIES)
            if subtract:
                entry[CONF_SUBTRACT_ENTITIES] = subtract if isinstance(subtract, list) else [subtract]
            consumers[idx] = entry
            self._edit_index = None
            return self.async_create_entry(data={CONF_CONSUMERS: consumers})

        existing = consumers[idx]
        return self.async_show_form(
            step_id="edit_consumer",
            data_schema=self._consumer_schema(existing),
        )

    @staticmethod
    def _consumer_schema(defaults=None):
        d = defaults or {}
        schema = {}

        ent = d.get("entity")
        if ent:
            schema[vol.Required("consumer_entity", default=ent)] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )
        else:
            schema[vol.Required("consumer_entity")] = EntitySelector(
                EntitySelectorConfig(domain="sensor")
            )

        schema[vol.Required("consumer_name", default=d.get("name", ""))] = TextSelector(
            TextSelectorConfig(type="text")
        )
        schema[vol.Required("consumer_category", default=d.get("category", "other"))] = SelectSelector(
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
        )

        power_ent = d.get(CONF_CONSUMER_POWER_ENTITY)
        if power_ent:
            schema[vol.Optional(CONF_CONSUMER_POWER_ENTITY, default=power_ent)] = EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            )
        else:
            schema[vol.Optional(CONF_CONSUMER_POWER_ENTITY)] = EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            )

        subs = d.get(CONF_SUBTRACT_ENTITIES)
        if subs:
            schema[vol.Optional(CONF_SUBTRACT_ENTITIES, default=subs)] = EntitySelector(
                EntitySelectorConfig(domain="sensor", multiple=True)
            )
        else:
            schema[vol.Optional(CONF_SUBTRACT_ENTITIES)] = EntitySelector(
                EntitySelectorConfig(domain="sensor", multiple=True)
            )

        return vol.Schema(schema)


def _wallbox_schema(marque: str, defaults: dict | None = None) -> vol.Schema:
    """Champs propres a la marque retenue, et rien d'autre."""
    d = defaults or {}
    schema: dict = {}
    if marque == EV_BRAND_EASEE:
        # Un seul champ : les services Easee s'adressent a un appareil, que
        # le registre donne depuis l'entite, et les autres entites de la
        # borne sont sur ce meme appareil.
        schema[vol.Optional(CONF_EV_EASEE_STATUS, description={"suggested_value": d.get(CONF_EV_EASEE_STATUS, "")})] = EntitySelector(
            EntitySelectorConfig(domain="sensor", integration="easee")
        )
    elif marque == EV_BRAND_GENERIC:
        schema[vol.Optional(CONF_EV_SWITCH, description={"suggested_value": d.get(CONF_EV_SWITCH, "")})] = EntitySelector(
            EntitySelectorConfig(domain="switch")
        )
        schema[vol.Optional(CONF_EV_AMPS, description={"suggested_value": d.get(CONF_EV_AMPS, "")})] = EntitySelector(
            EntitySelectorConfig(domain="number")
        )
        schema[vol.Optional(CONF_EV_PLUGGED, description={"suggested_value": d.get(CONF_EV_PLUGGED, "")})] = EntitySelector(
            EntitySelectorConfig(domain="binary_sensor")
        )
        schema[vol.Optional(CONF_EV_POWER, description={"suggested_value": d.get(CONF_EV_POWER, "")})] = EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class="power")
        )
    return vol.Schema(schema)


class HaPiloteComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Pilote Com."""

    VERSION = 1

    def __init__(self) -> None:
        self._donnees: dict = {}
        self._reconfigure = False

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
            self._donnees = user_input
            return await self.async_step_wallbox()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
        )

    async def async_step_wallbox(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Entites de la borne, selon la marque retenue a l'etape precedente."""
        marque = self._donnees.get(CONF_EV_BRAND, EV_BRAND_NONE)
        schema = _wallbox_schema(marque, self._donnees)
        # Aucune borne : rien a demander, on ne montre pas un formulaire vide.
        if user_input is None and schema.schema:
            return self.async_show_form(step_id="wallbox", data_schema=schema)
        donnees = dict(self._donnees)
        donnees.update(user_input or {})
        if self._reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=donnees)
        return self.async_create_entry(title="HA Pilote Com", data=donnees)

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            for key in (CONF_PRODUCTION_ENTITY, CONF_BATTERY_ENTITY, CONF_BATTERY_SOC_ENTITY, CONF_METER_PRODUCTION, CONF_METER_IMPORT, CONF_METER_EXPORT, CONF_METER_BATTERY_CHARGE, CONF_METER_BATTERY_DISCHARGE):
                user_input.setdefault(key, "")
            # Les entites deja enregistrees servent de valeurs proposees a
            # l'etape suivante ; changer de marque n'efface pas les autres.
            self._donnees = dict(self._get_reconfigure_entry().data)
            self._donnees.update(user_input)
            self._reconfigure = True
            return await self.async_step_wallbox()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(dict(self._get_reconfigure_entry().data)),
        )
