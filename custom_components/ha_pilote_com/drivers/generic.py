"""Borne generique : un interrupteur et un reglage d'amperage.

Couvre toute borne exposee dans Home Assistant par ces deux entites. C'est le
plus petit denominateur commun ; il ne sait ni basculer les phases, ni ouvrir
une session de charge explicitement.
"""

from __future__ import annotations

import asyncio
import logging

from . import WallboxDriver
from ..const import (
    CONF_EV_AMPS,
    CONF_EV_PLUGGED,
    CONF_EV_POWER,
    CONF_EV_SWITCH,
    EV_PHASE_SWITCH_WAIT,
)

_LOGGER = logging.getLogger(__name__)


class GenericDriver(WallboxDriver):

    marque = "generic"
    libelle = "Borne generique (interrupteur + amperage)"

    def __init__(self, hass, entry, options):
        super().__init__(hass, entry, options)
        self.sw = options.get(CONF_EV_SWITCH, "")
        self.amp = options.get(CONF_EV_AMPS, "")
        self.plug = options.get(CONF_EV_PLUGGED, "")
        self.pw = options.get(CONF_EV_POWER, "")
        self.on = None

    async def async_prepare(self) -> bool:
        if not self.sw and not self.amp:
            _LOGGER.info("Borne generique : aucune entite configuree")
            return False
        _LOGGER.info(
            "Borne generique : interrupteur=%s amperage=%s branche=%s puissance=%s",
            self.sw or "-", self.amp or "-", self.plug or "-", self.pw or "-",
        )
        return True

    def _etat(self, eid):
        return self.hass.states.get(eid) if eid else None

    def _num(self, eid):
        st = self._etat(eid)
        if st is None or st.state in ("unknown", "unavailable", "", None):
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None

    def plugged(self):
        st = self._etat(self.plug)
        return None if st is None else st.state == "on"

    def power_w(self):
        return self._num(self.pw)

    def max_amps(self):
        st = self._etat(self.amp)
        if st is None:
            return None
        try:
            return int(float(st.attributes.get("max")))
        except (TypeError, ValueError):
            return None

    async def apply(self, amperes: int, phases: int) -> None:
        if amperes and amperes > 0:
            # Bascule de phases : la plupart des bornes exigent un arret, une
            # pause, puis un redemarrage — pas une simple ecriture.
            if self.phases is not None and phases != self.phases and self.sw:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": self.sw}, blocking=True)
                await asyncio.sleep(EV_PHASE_SWITCH_WAIT)
                self.on = False
            if self.amp and amperes != self.amps:
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.amp, "value": amperes}, blocking=True)
            if self.sw and self.on is not True:
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": self.sw}, blocking=True)
                self.on = True
            self.amps = amperes
            self.phases = phases
            return

        # Redescendre l'amperage AVANT de couper, et le faire meme sans
        # interrupteur : beaucoup de bornes s'arretent sur une consigne nulle,
        # et une installation declaree avec le seul amperage n'aurait sinon
        # aucun moyen de stopper.
        if self.amp and self.amps != 0:
            vmin = 0.0
            st = self._etat(self.amp)
            if st is not None:
                try:
                    vmin = float(st.attributes.get("min", 0) or 0)
                except (TypeError, ValueError):
                    vmin = 0.0
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": self.amp, "value": vmin}, blocking=True)
        if self.sw and self.on is not False:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": self.sw}, blocking=True)
            self.on = False
        self.amps = 0

    async def release(self) -> None:
        if self.amp:
            vmax = self.max_amps()
            if vmax:
                await self.hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self.amp, "value": vmax}, blocking=True)
        if self.sw:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": self.sw}, blocking=True)
        self.amps = None
        self.phases = None
        self.on = None
