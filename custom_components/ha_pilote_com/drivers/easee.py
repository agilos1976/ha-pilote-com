"""Borne Easee.

L'utilisateur ne designe qu'une entite — le capteur de statut. Tout le reste
(identifiant materiel, puissance, etat du lien, interrupteurs) est retrouve
sur le meme appareil dans le registre : demander six entites pour un appareil
que Home Assistant connait deja serait reporter sur l'utilisateur un travail
que le plugin sait faire.

Quatre particularites Easee que ce pilote encapsule, et qu'aucune abstraction
generique ne devine :

1. Reecrire la meme limite est sans effet : la borne ne re-emet pas son signal
   et la voiture ne voit rien passer. On ecrit donc une valeur voisine, puis
   la vraie deux secondes apres.
2. time_to_live doit valoir 0. Sinon la limite expire et la borne remonte
   d'elle-meme au calibre du circuit, en plein milieu d'un suivi solaire.
3. La recharge intelligente Easee doit rester a l'arret : active, elle decide
   du courant a notre place et entre en conflit avec le planning du cockpit.
4. Ouvrir une session demande une commande explicite (start) ; regler le
   courant ne suffit pas.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.helpers import entity_registry as er

from . import WallboxDriver
from ..const import CONF_EV_EASEE_STATUS

_LOGGER = logging.getLogger(__name__)

# Statuts pour lesquels aucun vehicule n'est presente a la borne.
HORS_SESSION = ("disconnected", "unavailable", "unknown", "none", "")

# Suffixes d'entity_id cherches sur l'appareil. L'integration Easee est
# traduite : on accepte les deux langues plutot que d'imposer une locale.
SUFFIXES = {
    "power":  ("_puissance", "_power"),
    "online": ("_en_ligne", "_online"),
    "enable": ("_chargeur_active", "_enabled", "_is_enabled"),
    "smart":  ("_recharge_intelligente", "_smart_charging"),
}


class EaseeDriver(WallboxDriver):

    marque = "easee"
    libelle = "Easee"

    def __init__(self, hass, entry, options):
        super().__init__(hass, entry, options)
        self.status = options.get(CONF_EV_EASEE_STATUS, "")
        self.device_id = None
        self.e = {}
        self.paused = None

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def async_prepare(self) -> bool:
        if not self.status:
            _LOGGER.info("Easee : capteur de statut non configure")
            return False
        reg = er.async_get(self.hass)
        ent = reg.async_get(self.status)
        if ent is None or not ent.device_id:
            _LOGGER.warning(
                "Easee : %s est introuvable dans le registre ou n'est rattache "
                "a aucun appareil — or les services Easee s'adressent a un "
                "appareil, pas a une entite", self.status)
            return False
        self.device_id = ent.device_id

        for role, suffixes in SUFFIXES.items():
            for e in er.async_entries_for_device(
                    reg, self.device_id, include_disabled_entities=False):
                if any(e.entity_id.endswith(s) for s in suffixes):
                    self.e[role] = e.entity_id
                    break

        _LOGGER.info(
            "Easee : statut=%s puissance=%s lien=%s actif=%s intelligente=%s",
            self.status, self.e.get("power", "-"), self.e.get("online", "-"),
            self.e.get("enable", "-"), self.e.get("smart", "-"),
        )
        return True

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def _st(self, eid):
        return self.hass.states.get(eid) if eid else None

    def _statut(self):
        st = self._st(self.status)
        return "" if st is None else st.state

    def available(self) -> bool:
        st = self._st(self.e.get("online"))
        if st is not None:
            return st.state == "on"
        return self._statut() not in ("unavailable", "unknown", "")

    def plugged(self):
        s = self._statut()
        if s in ("unavailable", "unknown", ""):
            return None
        return s not in HORS_SESSION

    def power_w(self):
        st = self._st(self.e.get("power"))
        if st is None or st.state in ("unknown", "unavailable", "", None):
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        # Le capteur Easee publie des kW ; on ne le suppose pas, on le lit.
        unite = (st.attributes.get("unit_of_measurement") or "").strip()
        return v * 1000.0 if unite.lower() in ("kw", "kilowatt") else v

    def max_amps(self):
        """Calibre du circuit, tel que la borne le declare.

        C'est le plafond pose par l'electricien. Il prime sur toute consigne :
        le maximum generique Easee (32 A) depasserait le circuit.
        """
        st = self._st(self.status)
        if st is None:
            return None
        try:
            return int(float(st.attributes.get("circuit_ratedCurrent")))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------

    async def _svc(self, service, data):
        await self.hass.services.async_call(
            "easee", service, dict(data, device_id=self.device_id), blocking=True)

    async def _limite(self, amperes: int):
        """Ecrit la limite dynamique en forcant la borne a la re-emettre.

        La valeur voisine est prise au-dessus, sauf au plafond ou il n'y a
        plus de place : on passe alors juste en dessous.
        """
        plafond = self.max_amps() or 32
        voisin = amperes - 1 if amperes >= plafond else amperes + 1
        if voisin < 6:
            voisin = amperes + 1
        await self._svc("set_charger_dynamic_limit",
                        {"current": voisin, "time_to_live": 0})
        await asyncio.sleep(2)
        await self._svc("set_charger_dynamic_limit",
                        {"current": amperes, "time_to_live": 0})

    async def _intelligente_off(self):
        eid = self.e.get("smart")
        st = self._st(eid)
        if st is not None and st.state == "on":
            _LOGGER.info(
                "Easee : recharge intelligente desactivee — elle deciderait "
                "du courant a la place du planning Pilote")
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": eid}, blocking=True)

    async def apply(self, amperes: int, phases: int) -> None:
        plafond = self.max_amps()
        if plafond and amperes:
            amperes = min(amperes, plafond)

        if amperes and amperes > 0:
            await self._intelligente_off()

            eid = self.e.get("enable")
            st = self._st(eid)
            if st is not None and st.state != "on":
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": eid}, blocking=True)

            if phases and phases != self.phases:
                # Easee encaisse la bascule sans arret prealable, contrairement
                # a une borne pilotee par un simple interrupteur.
                await self._svc(
                    "set_charger_phase_mode",
                    {"phase_mode": "3_phase" if phases >= 3 else "1_phase"})
                await asyncio.sleep(5)
                self.phases = phases

            if amperes != self.amps:
                await self._limite(amperes)
                self.amps = amperes

            if self.paused:
                await self._svc("action_command", {"action_command": "resume"})
                self.paused = False
            if self._statut() != "charging":
                await self._svc("action_command", {"action_command": "start"})
            return

        # Arret : on met la session en pause plutot que de la clore. Une
        # session close oblige la voiture a tout renegocier, et certaines
        # refusent de repartir sans debranchement physique.
        if self.paused is not True:
            await self._svc("action_command", {"action_command": "pause"})
            self.paused = True
        self.amps = 0

    async def release(self) -> None:
        """Rend la borne dans son comportement d'origine."""
        plafond = self.max_amps() or 16
        await self._svc("set_charger_dynamic_limit",
                        {"current": plafond, "time_to_live": 0})
        if self.plugged() is not True:
            # Le mode automatique ne se change pas sereinement avec un
            # vehicule presente : on attend qu'il soit debranche.
            await self._svc("set_charger_phase_mode", {"phase_mode": "auto_phase"})
        eid = self.e.get("enable")
        if eid:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": eid}, blocking=True)
        await self._svc("action_command", {"action_command": "resume"})
        _LOGGER.info("Easee : borne rendue a l'utilisateur (%s A)", plafond)
        self.amps = None
        self.phases = None
        self.paused = None
