"""Interrupteur exposant le pilotage de la recharge VE par Pilote."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_EV_AMPS,
    CONF_EV_BRAND,
    CONF_EV_SWITCH,
    DOMAIN,
    EV_BRAND_GENERIC,
    EV_BRAND_NONE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cree l'interrupteur, uniquement si une borne est declaree.

    La condition porte sur la MARQUE, pas sur les entites d'une marque
    particuliere. Elle regardait auparavant les entites generiques, si bien
    qu'une borne Easee — qui n'en renseigne aucune — ne recevait pas
    d'interrupteur : le pilotage devenait impossible a activer, sans que rien
    ne l'explique.
    """
    marque = entry.options.get(CONF_EV_BRAND, entry.data.get(CONF_EV_BRAND, ""))
    if not marque:
        # Configuration anterieure au choix de marque : on se rabat sur les
        # entites generiques, seule declaration de borne qui existait alors.
        marque = (
            EV_BRAND_GENERIC
            if entry.options.get(CONF_EV_SWITCH, entry.data.get(CONF_EV_SWITCH, ""))
            or entry.options.get(CONF_EV_AMPS, entry.data.get(CONF_EV_AMPS, ""))
            else EV_BRAND_NONE
        )
    if marque == EV_BRAND_NONE:
        # Sans borne declaree l'interrupteur n'aurait rien a piloter : mieux
        # vaut pas d'entite du tout qu'une entite sans effet.
        return
    async_add_entities([PiloteEvSwitch(entry)])


class PiloteEvSwitch(SwitchEntity, RestoreEntity):
    """Autorise ou non Pilote a piloter la borne.

    L'etat vit dans hass.data : la boucle _ev_control le lit a chaque cycle.
    RestoreEntity le retablit apres un redemarrage de Home Assistant, sinon le
    pilotage repartirait a l'arret sans que personne ne s'en apercoive.
    """

    _attr_has_entity_name = True
    _attr_name = "Pilote optimise votre recharge VE"
    _attr_icon = "mdi:ev-station"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ev_enabled"
        self._attr_is_on = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Pilote",
            "manufacturer": "Romande Dynamics",
        }

    def _publish(self) -> None:
        store = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry.entry_id, {})
        store["ev_enabled"] = self._attr_is_on

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Par defaut a l'arret : activer un chargeur de voiture sans geste
        # explicite de l'utilisateur ne doit pas etre un effet de bord d'une
        # mise a jour.
        last = await self.async_get_last_state()
        self._attr_is_on = last is not None and last.state == "on"
        self._publish()

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._publish()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._publish()
        self.async_write_ha_state()
        # Rendre la borne dans un etat utilisable : coupee par Pilote puis
        # abandonnee, elle laisserait l'utilisateur sans recharge sans motif
        # visible. Le releve de la reprise est confie a la boucle principale.
        store = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry.entry_id, {})
        store["ev_release"] = True
