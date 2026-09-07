"""Borne Tesla — la borne ouvre le robinet, la voiture decide du debit.

La Wall Connector ne module pas le courant : elle autorise, et c'est le
vehicule qui choisit combien il prend. Toutes les autres marques font
l'inverse, d'ou un pilote a part plutot qu'une variante du generique.

Consequences, et elles ne sont pas cosmetiques :

1. La consigne d'amperage s'ecrit sur LA VOITURE, pas sur la borne. Les deux
   sont des appareils distincts dans Home Assistant.
2. Couper ne peut pas se faire en baissant l'amperage. Le minimum d'une Tesla
   est de 5 A ; sur trois phases cela fait encore 3.4 kW. Un arret exige donc
   l'interrupteur de charge du vehicule — sans lui, ce pilote refuse de
   demarrer plutot que de faire croire qu'il sait s'arreter.
3. Le nombre de phases n'est pas pilotable. La Wall Connector est cablee une
   fois pour toutes ; la consigne de phases venue du serveur est ignoree, et
   c'est la configuration du site qui doit dire la verite.
4. Une Tesla dort. Chaque commande la reveille et puise sur la batterie 12 V,
   et l'API Tesla limite les appels. On ecrit donc le moins possible : jamais
   la meme valeur deux fois, et l'etat de l'interrupteur se LIT plutot que de
   se deduire d'un souvenir.
"""

from __future__ import annotations

import logging
import time

from homeassistant.helpers import entity_registry as er

from . import WallboxDriver
from ..const import CONF_EV_TESLA_AMPS, CONF_EV_TESLA_STATUS

_LOGGER = logging.getLogger(__name__)

# Etats publies par Tesla dans charging_state.
HORS_SESSION = ("disconnected", "unavailable", "unknown", "none", "")
EN_CHARGE = ("charging", "starting")

# Les etats qui EXPLIQUENT qu'aucun courant ne circule. On renvoie le code
# brut, pas une phrase : c'est le cockpit qui met en forme, comme il le fait
# deja pour les codes Easee. Mettre la traduction ici la placerait a deux
# endroits, dont un sans acces aux fichiers de langue.
RAISONS = ("complete", "stopped", "nopower", "no_power")

# Intervalle minimal entre deux commandes d'interrupteur. Une Tesla endormie
# se reveille a chaque ordre ; enchainer marche/arret la vide et sature l'API.
COMMUTATION_MIN = 60

# Comment reconnaitre l'interrupteur de charge sur l'appareil du vehicule.
# Trois integrations Tesla coexistent (officielle, Teslemetry, Tesla Custom)
# et ne nomment pas leurs entites pareil : on cherche donc par mot-cle, sur
# l'identifiant unique d'abord — pose par l'integration, invisible et
# independant de la langue — puis sur l'entity_id.
CLES_INTERRUPTEUR = ("charge", "charging")
# A ecarter en premier : « charge_port », « charging_amps »… ne commandent pas
# la charge elle-meme.
CLES_ECARTEES = ("port", "door", "limit", "amps", "current", "schedul")


class TeslaDriver(WallboxDriver):

    marque = "tesla"
    libelle = "Tesla (borne + voiture)"

    def __init__(self, hass, entry, options):
        super().__init__(hass, entry, options)
        self.status = options.get(CONF_EV_TESLA_STATUS, "")
        self.amp = options.get(CONF_EV_TESLA_AMPS, "")
        self.sw = None
        self.pw = None
        self.derniere_commutation = 0.0
        self.phases_dit = False

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def async_prepare(self) -> bool:
        if not self.status or not self.amp:
            _LOGGER.info(
                "Tesla : il faut les deux entites — le statut de charge et "
                "l'amperage de la voiture")
            return False

        reg = er.async_get(self.hass)
        ent = reg.async_get(self.amp)
        if ent is None or not ent.device_id:
            _LOGGER.warning(
                "Tesla : %s est introuvable dans le registre ou n'est "
                "rattache a aucun appareil — impossible d'y trouver "
                "l'interrupteur de charge", self.amp)
            return False

        voisines = er.async_entries_for_device(
            reg, ent.device_id, include_disabled_entities=False)
        self.sw = self._interrupteur(voisines)
        self.pw = self._puissance(voisines)

        _LOGGER.info(
            "Tesla : statut=%s amperage=%s interrupteur=%s puissance=%s",
            self.status, self.amp, self.sw or "-", self.pw or "-")

        if not self.sw:
            # Fatal, et volontairement : un pilote qui ne sait pas arreter
            # laisserait la voiture charger au tarif de pointe en croyant
            # l'avoir stoppee. Mieux vaut ne pas demarrer et le dire.
            _LOGGER.error(
                "Tesla : aucun interrupteur de charge trouve sur l'appareil "
                "de %s. Sans lui Pilote ne peut pas arreter la charge — "
                "baisser l'amperage ne suffit pas, le minimum Tesla laisse "
                "passer plusieurs kilowatts. Verifie que l'entite "
                "« Charge » du vehicule est activee dans Home Assistant.",
                self.amp)
            return False
        return True

    @staticmethod
    def _interrupteur(voisines):
        cands = [e for e in voisines if e.entity_id.startswith("switch.")]
        for source in (lambda e: (e.unique_id or "").lower(),
                       lambda e: e.entity_id.lower()):
            for e in cands:
                s = source(e)
                if any(k in s for k in CLES_INTERRUPTEUR) \
                        and not any(x in s for x in CLES_ECARTEES):
                    return e.entity_id
        return None

    @staticmethod
    def _puissance(voisines):
        cands = [e for e in voisines if e.entity_id.startswith("sensor.")]
        for e in cands:
            if (e.device_class or e.original_device_class) == "power":
                s = (e.unique_id or "").lower() + " " + e.entity_id.lower()
                if "charg" in s:
                    return e.entity_id
        return None

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def _st(self, eid):
        return self.hass.states.get(eid) if eid else None

    def _statut(self):
        st = self._st(self.status)
        return "" if st is None else str(st.state).lower()

    def _bornes(self):
        """Minimum et maximum que la voiture accepte, tels qu'elle les dit."""
        st = self._st(self.amp)
        bas, haut = 5, 32
        if st is not None:
            try:
                bas = int(float(st.attributes.get("min", bas)))
            except (TypeError, ValueError):
                pass
            try:
                haut = int(float(st.attributes.get("max", haut)))
            except (TypeError, ValueError):
                pass
        return bas, haut

    def available(self) -> bool:
        return self._statut() not in ("unavailable", "unknown", "")

    def plugged(self):
        s = self._statut()
        if s in ("unavailable", "unknown", ""):
            return None
        return s not in HORS_SESSION

    def entites_manquantes(self):
        # On teste l'ETAT, pas la resolution. Une entite peut figurer au
        # registre sans avoir d etat — desactivee, ou renommee puis recreee —
        # et tout echoue ensuite en silence. Le pilote Easee avait deja paye
        # exactement cette distinction.
        manque = []
        for role, eid in (("statut", self.status), ("amperage", self.amp),
                          ("interrupteur", self.sw), ("puissance", self.pw)):
            if not eid or self._st(eid) is None:
                manque.append(role)
        return manque

    def etat(self):
        return self._statut()

    def raison(self):
        s = self._statut()
        return s if s in RAISONS else ""

    def charge_en_cours(self):
        pw = self.power_w()
        if pw is not None:
            return pw > 200
        s = self._statut()
        if s in ("unavailable", "unknown", ""):
            return None
        return s in EN_CHARGE

    def power_w(self):
        st = self._st(self.pw)
        if st is None or st.state in ("unknown", "unavailable", "", None):
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        unite = (st.attributes.get("unit_of_measurement") or "").strip().lower()
        return v * 1000.0 if unite in ("kw", "kilowatt") else v

    def max_amps(self):
        """Ce que la VOITURE accepte, pas le calibre du circuit.

        C'est la meme contrainte de fond — une borne superieure qui prime sur
        la consigne — mais elle vient d'un autre bout de la chaine : une Model 3
        Propulsion plafonne a 16 A la ou la borne en offrirait 32.
        """
        st = self._st(self.amp)
        if st is None:
            return None
        return self._bornes()[1]

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------

    def _allume(self):
        """L'etat REEL de l'interrupteur, pas le souvenir de nos ordres.

        Le pilote Easee a paye cette lecon : une memoire interne dit ce que
        NOUS avons demande, pas ce que la voiture fait. L'application Tesla,
        une automatisation, ou la voiture elle-meme peuvent commander la
        charge sans nous.
        """
        st = self._st(self.sw)
        return None if st is None else st.state == "on"

    async def _ecrire_amperes(self, amperes: int):
        bas, haut = self._bornes()
        valeur = max(bas, min(haut, int(amperes)))
        if valeur != amperes:
            _LOGGER.info(
                "Tesla : consigne de %d A ramenee a %d A — la voiture accepte "
                "de %d a %d A", amperes, valeur, bas, haut)
        _LOGGER.info("Tesla <- amperage %d A (%s)", valeur, self.amp)
        await self.hass.services.async_call(
            "number", "set_value",
            {"entity_id": self.amp, "value": valeur}, blocking=True)
        self.amps = valeur

    async def _commuter(self, marche: bool):
        maintenant = time.monotonic()
        if maintenant - self.derniere_commutation < COMMUTATION_MIN:
            return False
        self.derniere_commutation = maintenant
        _LOGGER.info("Tesla <- charge %s (%s)",
                     "marche" if marche else "arret", self.sw)
        await self.hass.services.async_call(
            "switch", "turn_on" if marche else "turn_off",
            {"entity_id": self.sw}, blocking=True)
        return True

    async def apply(self, amperes: int, phases: int) -> None:
        # Le cablage de la borne ne se change pas depuis Home Assistant. On le
        # dit une fois, puis on se tait : le repeter a chaque cycle noierait
        # le journal sans rien apporter.
        if phases and self.phases is not None and phases != self.phases \
                and not self.phases_dit:
            _LOGGER.info(
                "Tesla : le serveur demande %d phase(s), mais une Wall "
                "Connector est cablee une fois pour toutes. La consigne de "
                "phases est ignoree — verifie que le site est declare avec le "
                "bon nombre de phases.", phases)
            self.phases_dit = True
        self.phases = phases

        if amperes and amperes > 0:
            # L'amperage d'abord, l'interrupteur ensuite : la voiture doit
            # connaitre le debit avant qu'on ouvre le robinet, sinon elle
            # demarre a son ancienne consigne.
            if amperes != self.amps:
                await self._ecrire_amperes(amperes)
            if self._allume() is not True:
                await self._commuter(True)
            return

        # Arret. On coupe l'interrupteur, jamais par l'amperage : le minimum
        # Tesla laisse passer plusieurs kilowatts.
        if self._allume() is not False:
            await self._commuter(False)
        self.amps = 0

    async def release(self) -> None:
        """Rend la voiture a son proprietaire : plein debit, charge autorisee."""
        _, haut = self._bornes()
        await self.hass.services.async_call(
            "number", "set_value",
            {"entity_id": self.amp, "value": haut}, blocking=True)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": self.sw}, blocking=True)
        _LOGGER.info("Tesla : vehicule rendu a l'utilisateur (%d A)", haut)
        self.amps = None
        self.phases = None
