from __future__ import annotations

import logging

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
    BRAND_KEYWORDS,
    BAT_IN_HINTS,
    BAT_OUT_HINTS,
    CONF_ADD_BATTERY_ENTITY,
    CONF_API_KEY,
    CONF_BRANDS,
    CONF_CONSUMERS,
    CONF_CONSUMPTION_ENTITY,
    CONF_GRID_ENTITY,
    CONF_OUT_BATTERY_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_PROFILE,
    CONF_SOC_ENTITY,
    CONF_UPDATE_INTERVAL,
    CONSO_HINTS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    GRID_HINTS,
    PROD_HINTS,
    PROFILE_CONSUMPTION,
    PROFILE_SOLAR,
    PROFILE_SOLAR_BATTERY,
    SOC_HINTS,
)

_LOGGER = logging.getLogger(__name__)

_ENERGY_DEVICE_CLASSES = ["power", "energy"]


def _match_hints(entity_id: str, hints: list[str]) -> bool:
    eid = entity_id.lower()
    return any(h in eid for h in hints)


def _detect_entities(hass, brands: list[str], profile: str) -> dict[str, str]:
    """Scan toutes les entités HA et trouve les meilleures correspondances."""
    all_states = hass.states.async_all("sensor")

    brand_kws = []
    for brand in brands:
        brand_kws.extend(BRAND_KEYWORDS.get(brand, [brand]))

    candidates: dict[str, list[str]] = {}

    for state in all_states:
        eid = state.entity_id.lower()
        attrs = state.attributes
        dc = attrs.get("device_class", "") or ""
        unit = (attrs.get("unit_of_measurement") or "").lower()

        if not any(kw in eid for kw in brand_kws):
            continue

        is_power = dc in ("power", "energy") or unit in ("w", "kw", "wh", "kwh")

        if is_power and _match_hints(eid, GRID_HINTS):
            candidates.setdefault("grid", []).append(state.entity_id)

        if is_power and _match_hints(eid, PROD_HINTS):
            candidates.setdefault("production", []).append(state.entity_id)

        if is_power and _match_hints(eid, CONSO_HINTS):
            candidates.setdefault("consumption", []).append(state.entity_id)

        if is_power and _match_hints(eid, BAT_IN_HINTS):
            candidates.setdefault("battery_in", []).append(state.entity_id)

        if is_power and _match_hints(eid, BAT_OUT_HINTS):
            candidates.setdefault("battery_out", []).append(state.entity_id)

        if dc == "battery" or _match_hints(eid, SOC_HINTS):
            candidates.setdefault("soc", []).append(state.entity_id)

    detected = {}
    for role, eids in candidates.items():
        if eids:
            detected[role] = eids[0]

    return detected


def _entity_selector(device_classes=None):
    if device_classes is None:
        device_classes = _ENERGY_DEVICE_CLASSES
    return EntitySelector(EntitySelectorConfig(
        domain="sensor",
        device_class=device_classes,
    ))


def _entity_schema(profile: str, defaults: dict | None = None) -> vol.Schema:
    """Schéma d'entités adapté au profil d'installation."""
    d = defaults or {}
    schema: dict = {}

    schema[vol.Required(
        CONF_GRID_ENTITY,
        default=d.get(CONF_GRID_ENTITY, d.get("grid")),
    )] = _entity_selector()

    if profile in (PROFILE_SOLAR_BATTERY, PROFILE_SOLAR):
        schema[vol.Required(
            CONF_PRODUCTION_ENTITY,
            default=d.get(CONF_PRODUCTION_ENTITY, d.get("production")),
        )] = _entity_selector()

        schema[vol.Optional(
            CONF_CONSUMPTION_ENTITY,
            description={"suggested_value": d.get(CONF_CONSUMPTION_ENTITY, d.get("consumption", ""))},
        )] = _entity_selector()

    if profile == PROFILE_SOLAR_BATTERY:
        schema[vol.Optional(
            CONF_ADD_BATTERY_ENTITY,
            description={"suggested_value": d.get(CONF_ADD_BATTERY_ENTITY, d.get("battery_in", ""))},
        )] = _entity_selector()

        schema[vol.Optional(
            CONF_OUT_BATTERY_ENTITY,
            description={"suggested_value": d.get(CONF_OUT_BATTERY_ENTITY, d.get("battery_out", ""))},
        )] = _entity_selector()

        schema[vol.Optional(
            CONF_SOC_ENTITY,
            description={"suggested_value": d.get(CONF_SOC_ENTITY, d.get("soc", ""))},
        )] = EntitySelector(EntitySelectorConfig(domain="sensor"))

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

        desc = "Aucun consommateur configuré."
        if consumers:
            lines = [f"• {c['name']} ({c['entity']})" for c in consumers]
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
                }
            ),
        )


class HaPiloteComConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for HA Pilote Com."""

    VERSION = 1

    def __init__(self):
        self._data: dict = {}

    @staticmethod
    def async_get_options_flow(config_entry):
        return HaPiloteComOptionsFlow()

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Étape 1 : Type d'installation."""
        if user_input is not None:
            self._data[CONF_PROFILE] = user_input[CONF_PROFILE]
            return await self.async_step_equipment()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROFILE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=PROFILE_SOLAR_BATTERY,
                                    label="Solaire + Batterie",
                                ),
                                SelectOptionDict(
                                    value=PROFILE_SOLAR,
                                    label="Solaire uniquement",
                                ),
                                SelectOptionDict(
                                    value=PROFILE_CONSUMPTION,
                                    label="Consommation uniquement (pas de panneaux)",
                                ),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_equipment(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Étape 2 : Quel matériel ?"""
        if user_input is not None:
            self._data[CONF_BRANDS] = user_input[CONF_BRANDS]
            return await self.async_step_entities()

        profile = self._data[CONF_PROFILE]

        options = [
            SelectOptionDict(value="whatwatt", label="WhatWatt Go (compteur GRD)"),
            SelectOptionDict(value="shelly", label="Shelly EM / Pro"),
        ]

        if profile in (PROFILE_SOLAR_BATTERY, PROFILE_SOLAR):
            options.extend([
                SelectOptionDict(value="fronius", label="Fronius"),
                SelectOptionDict(value="solaredge", label="SolarEdge"),
                SelectOptionDict(value="huawei", label="Huawei FusionSolar"),
                SelectOptionDict(value="enphase", label="Enphase"),
                SelectOptionDict(value="sma", label="SMA"),
                SelectOptionDict(value="kostal", label="Kostal"),
                SelectOptionDict(value="senec", label="SENEC"),
            ])

        if profile == PROFILE_SOLAR_BATTERY:
            options.append(
                SelectOptionDict(value="mystrom", label="myStrom (prises)")
            )

        options.append(
            SelectOptionDict(value="other", label="Autre matériel")
        )

        return self.async_show_form(
            step_id="equipment",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BRANDS): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                            multiple=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_entities(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Étape 3 : Sélection des entités (auto-détectées)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_api()

        profile = self._data[CONF_PROFILE]
        brands = self._data.get(CONF_BRANDS, [])

        detected = _detect_entities(self.hass, brands, profile)

        if detected:
            _LOGGER.info("Auto-détection: %s", detected)

        return self.async_show_form(
            step_id="entities",
            data_schema=_entity_schema(profile, detected),
        )

    async def async_step_api(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Étape 4 : Clé API et intervalle."""
        if user_input is not None:
            self._data.update(user_input)

            for key in (CONF_PRODUCTION_ENTITY, CONF_CONSUMPTION_ENTITY,
                        CONF_ADD_BATTERY_ENTITY, CONF_OUT_BATTERY_ENTITY,
                        CONF_SOC_ENTITY):
                self._data.setdefault(key, "")

            await self.async_set_unique_id(self._data[CONF_API_KEY])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Pilote Solaire",
                data=self._data,
            )

        return self.async_show_form(
            step_id="api",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type="password")
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=DEFAULT_UPDATE_INTERVAL,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=5,
                            max=1440,
                            step=5,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        existing = dict(entry.data)
        profile = existing.get(CONF_PROFILE, PROFILE_SOLAR_BATTERY)
        is_legacy = CONF_PROFILE not in entry.data

        if user_input is not None:
            for key in (CONF_PRODUCTION_ENTITY, CONF_CONSUMPTION_ENTITY,
                        CONF_ADD_BATTERY_ENTITY, CONF_OUT_BATTERY_ENTITY,
                        CONF_SOC_ENTITY):
                user_input.setdefault(key, "")
            if not is_legacy:
                user_input[CONF_PROFILE] = profile
            existing.update(user_input)
            return self.async_update_reload_and_abort(entry, data=existing)

        interval_display = existing.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        if is_legacy and interval_display <= 24:
            interval_display = int(interval_display) * 60

        schema_dict: dict = {}

        schema_dict[vol.Required(
            CONF_GRID_ENTITY,
            default=existing.get(CONF_GRID_ENTITY),
        )] = _entity_selector()

        if profile in (PROFILE_SOLAR_BATTERY, PROFILE_SOLAR):
            schema_dict[vol.Optional(
                CONF_PRODUCTION_ENTITY,
                description={"suggested_value": existing.get(CONF_PRODUCTION_ENTITY, "")},
            )] = _entity_selector()
            schema_dict[vol.Optional(
                CONF_CONSUMPTION_ENTITY,
                description={"suggested_value": existing.get(CONF_CONSUMPTION_ENTITY, "")},
            )] = _entity_selector()

        if profile == PROFILE_SOLAR_BATTERY:
            schema_dict[vol.Optional(
                CONF_ADD_BATTERY_ENTITY,
                description={"suggested_value": existing.get(CONF_ADD_BATTERY_ENTITY, "")},
            )] = _entity_selector()
            schema_dict[vol.Optional(
                CONF_OUT_BATTERY_ENTITY,
                description={"suggested_value": existing.get(CONF_OUT_BATTERY_ENTITY, "")},
            )] = _entity_selector()
            schema_dict[vol.Optional(
                CONF_SOC_ENTITY,
                description={"suggested_value": existing.get(CONF_SOC_ENTITY, "")},
            )] = EntitySelector(EntitySelectorConfig(domain="sensor"))

        schema_dict[vol.Required(
            CONF_UPDATE_INTERVAL,
            default=interval_display,
        )] = NumberSelector(
            NumberSelectorConfig(
                min=5, max=1440, step=5,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        )
        schema_dict[vol.Required(
            CONF_API_KEY,
            default=existing.get(CONF_API_KEY),
        )] = TextSelector(TextSelectorConfig(type="password"))

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(schema_dict),
        )
