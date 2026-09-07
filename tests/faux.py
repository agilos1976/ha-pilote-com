# -*- coding: utf-8 -*-
"""Un Home Assistant en carton, juste assez pour faire tourner le vrai pilote.

Le pilote Easee n'importe qu'UNE chose de Home Assistant : le registre des
entités. On le remplace ici, et tout le reste du fichier — la résolution des
entités, l'échelle de réveil, la discipline d'écriture — s'exécute tel qu'il
tourne chez l'utilisateur. Ce n'est pas un port, il n'y a rien qui puisse
diverger d'une version à l'autre.

Le temps est faux lui aussi, et c'est indispensable : les temporisations du
pilote se comptent en minutes. Un `await asyncio.sleep(6)` avance l'horloge de
six secondes sans que personne n'attende, et une heure de charge se déroule en
quelques millisecondes.
"""

import asyncio
import importlib
import json
import os
import sys
import types

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------- horloge
class Horloge:
    """Remplace `time` et `asyncio` dans le module testé.

    Les deux sont branchés sur le même compteur : un sleep du pilote fait
    réellement avancer ce que time.monotonic() lui répondra ensuite.
    """

    def __init__(self):
        self.t = 1000.0
        self.dormi = []
        # Faire échouer une attente précise, pour vérifier qu'une séquence
        # interrompue en son milieu ne laisse pas la borne dans un état bâtard.
        self.exploser_a = None

    def monotonic(self):
        return self.t

    def time(self):
        return self.t

    async def sleep(self, s):
        self.dormi.append(s)
        self.t += s
        if self.exploser_a is not None and s == self.exploser_a:
            raise RuntimeError("Home Assistant s'arrête pendant l'attente")

    def avance(self, s):
        self.t += s


# ----------------------------------------------------------------- états
class Etat:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class Etats:
    def __init__(self, d=None):
        self.d = dict(d or {})

    def get(self, eid):
        return self.d.get(eid)

    def pose(self, eid, state, **attrs):
        self.d[eid] = Etat(state, attrs)

    def retire(self, eid):
        self.d.pop(eid, None)


# -------------------------------------------------------------- services
class Appel:
    def __init__(self, domaine, service, data):
        self.domaine, self.service, self.data = domaine, service, data

    def __repr__(self):
        util = dict((k, v) for k, v in self.data.items() if k != "device_id")
        return "%s.%s %s" % (self.domaine, self.service, util)


class Services:
    def __init__(self):
        self.appels = []
        self.exploser = None      # (domaine, service) : lève une exception

    async def async_call(self, domaine, service, data, blocking=False):
        self.appels.append(Appel(domaine, service, dict(data)))
        if self.exploser == (domaine, service):
            raise RuntimeError("liaison Easee interrompue")

    # --- lectures pratiques -------------------------------------------
    def limites(self):
        """Les écritures de courant, dans l'ordre."""
        return [a for a in self.appels
                if a.service == "set_charger_dynamic_limit"]

    def courants(self):
        return [a.data.get("current") for a in self.limites()]

    def commandes(self):
        return [a.data.get("action_command") for a in self.appels
                if a.service == "action_command"]

    def noms(self):
        return ["%s.%s" % (a.domaine, a.service) for a in self.appels]

    def vider(self):
        self.appels = []


class Hass:
    def __init__(self, etats, services):
        self.states = etats
        self.services = services


# --------------------------------------------------- registre des entités
class Inscription:
    def __init__(self, entity_id, unique_id=None, device_class=None,
                 device_id="borne-1"):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.device_class = device_class
        self.original_device_class = None
        self.device_id = device_id


def _faux_homeassistant(inscriptions):
    """Injecte homeassistant.helpers.entity_registry avant l'import du pilote."""
    par_id = dict((i.entity_id, i) for i in inscriptions)

    class Registre:
        def async_get(self, eid):
            return par_id.get(eid)

    reg = Registre()
    mod = types.ModuleType("homeassistant.helpers.entity_registry")
    mod.async_get = lambda hass: reg
    mod.async_entries_for_device = (
        lambda r, device_id, include_disabled_entities=False:
        [i for i in inscriptions if i.device_id == device_id])

    ha = sys.modules.setdefault("homeassistant",
                                types.ModuleType("homeassistant"))
    helpers = sys.modules.setdefault("homeassistant.helpers",
                                     types.ModuleType("homeassistant.helpers"))
    ha.helpers = helpers
    helpers.entity_registry = mod
    sys.modules["homeassistant.helpers.entity_registry"] = mod


def _paquets_synthetiques():
    """Ouvre le chemin vers drivers/ sans exécuter le __init__.py du paquet.

    Le __init__.py de l'intégration importe la moitié de Home Assistant :
    config_entries, recorder, dt_util… L'imiter en entier pour atteindre un
    fichier qui n'en dépend pas serait absurde. On fabrique donc les paquets
    parents à la main, avec leur seul __path__ — les imports relatifs du
    pilote (`from . import`, `from ..const import`) s'y résolvent, et le
    __init__.py n'est jamais exécuté.

    Sa syntaxe, elle, reste vérifiée par la série « syntaxe ».
    """
    for nom, chemin in (
        ("custom_components", os.path.join(RACINE, "custom_components")),
        ("custom_components.ha_pilote_com",
         os.path.join(RACINE, "custom_components", "ha_pilote_com")),
    ):
        mod = types.ModuleType(nom)
        mod.__path__ = [chemin]
        sys.modules[nom] = mod


def charger_pilote(nom, inscriptions=()):
    """Importe le VRAI module d'un pilote, avec ses dépendances en carton."""
    _faux_homeassistant(list(inscriptions))
    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    for m in list(sys.modules):
        if m.startswith("custom_components"):
            del sys.modules[m]
    _paquets_synthetiques()
    return importlib.import_module(
        "custom_components.ha_pilote_com.drivers." + nom)


def charger_easee(inscriptions=()):
    return charger_pilote("easee", inscriptions)


# --------------------------------------------------------------- montage
ENTITES = [
    Inscription("sensor.borne_statut", "AB123_status"),
    Inscription("sensor.borne_puissance_totale_borne", "AB123_power", "power"),
    Inscription("binary_sensor.borne_en_ligne", "AB123_online", "connectivity"),
    Inscription("switch.borne_chargeur_active", "AB123_isEnabled"),
    Inscription("switch.borne_recharge_intelligente", "AB123_smartCharging"),
    Inscription("sensor.borne_raison", "AB123_reasonForNoCurrent"),
    Inscription("button.borne_ignorer_la_programmation",
                "AB123_override_schedule"),
]

STATUT = "sensor.borne_statut"
PUISSANCE = "sensor.borne_puissance_totale_borne"


class Banc:
    """Une borne montée, prête à recevoir des consignes."""

    def __init__(self, statut="charging", puissance=7000, entites=None,
                 calibre=25, unite="W", statut_eid=STATUT):
        self.horloge = Horloge()
        self.easee = charger_easee(ENTITES if entites is None else entites)
        # Le module testé lit l'heure et dort PAR CES DEUX OBJETS.
        self.easee.time = self.horloge
        self.easee.asyncio = self.horloge
        self.etats = Etats()
        self.services = Services()
        self.hass = Hass(self.etats, self.services)
        self.calibre = calibre
        self.eid_statut = statut_eid

        self.etats.pose(statut_eid, statut, circuit_ratedCurrent=calibre)
        if puissance is not None:
            self.etats.pose(PUISSANCE, str(puissance),
                            unit_of_measurement=unite)
        self.etats.pose("binary_sensor.borne_en_ligne", "on")
        self.etats.pose("switch.borne_chargeur_active", "on")
        self.etats.pose("switch.borne_recharge_intelligente", "off")
        self.etats.pose("sensor.borne_raison", "ok")
        self.etats.pose("button.borne_ignorer_la_programmation", "unknown")

        self.d = self.easee.EaseeDriver(
            self.hass, None, {"ev_easee_status": statut_eid})
        asyncio.run(self.d.async_prepare())
        self.services.vider()

    # --- conduite ------------------------------------------------------
    def statut(self, s):
        self.etats.pose(self.eid_statut, s, circuit_ratedCurrent=self.calibre)

    def puissance(self, w, unite="W"):
        if w is None:
            self.etats.retire(PUISSANCE)
        else:
            self.etats.pose(PUISSANCE, str(w), unit_of_measurement=unite)

    def applique(self, amperes, phases=3):
        asyncio.run(self.d.apply(amperes, phases))

    def cycles(self, n, amperes, phases=3, pas=10):
        """n cycles de pilotage espacés de `pas` secondes, comme le serveur."""
        for _ in range(n):
            self.applique(amperes, phases)
            self.horloge.avance(pas)

    def jusqu_a(self, condition, amperes, phases=3, pas=10, plafond=400):
        """Pilote jusqu'à ce que `condition()` soit vraie, et s'arrête LÀ.

        Compter les cycles à la main est un piège : le cycle qui suit celui
        qu'on visait défait ce qu'on venait d'observer — une consigne remise,
        un compteur réarmé — et le test constate alors le contraire de ce
        qu'il voulait voir. Quatre de mes tests s'y sont pris exactement.
        """
        for _ in range(plafond):
            self.applique(amperes, phases)
            if condition():
                return True
            self.horloge.avance(pas)
        return False


# ------------------------------------------------------- montage Tesla
# Deux appareils, et c'est tout l'intérêt du cas : le statut vient de la
# borne, la consigne de courant s'écrit sur la voiture. Les leurres sont
# délibérés — un vrai véhicule Tesla expose « charge_port_door » et
# « charge_limit », qui contiennent le mot « charge » sans commander la
# charge.
BORNE, VOITURE = "borne-tesla", "voiture-tesla"
ENTITES_TESLA = [
    Inscription("sensor.wall_connector_status", "WC42_status", None, BORNE),
    Inscription("sensor.wall_connector_power", "WC42_power", "power", BORNE),
    Inscription("number.model3_charging_amps", "VIN9_charging_amps", None, VOITURE),
    Inscription("switch.model3_charge", "VIN9_charge", None, VOITURE),
    Inscription("switch.model3_charge_port_door", "VIN9_charge_port_door",
                None, VOITURE),
    Inscription("number.model3_charge_limit", "VIN9_charge_limit", None, VOITURE),
    Inscription("sensor.model3_charger_power", "VIN9_charger_power",
                "power", VOITURE),
]

T_STATUT = "sensor.wall_connector_status"
T_AMPS = "number.model3_charging_amps"
T_SW = "switch.model3_charge"
T_PW = "sensor.model3_charger_power"


class BancTesla:
    """Une Wall Connector et une voiture, prêtes à recevoir des consignes."""

    def __init__(self, statut="charging", puissance=7000, entites=None,
                 bas=5, haut=16, amps=None, sw="off", prepare=True):
        self.horloge = Horloge()
        self.tesla = charger_pilote(
            "tesla", ENTITES_TESLA if entites is None else entites)
        self.tesla.time = self.horloge
        self.etats = Etats()
        self.services = Services()
        self.hass = Hass(self.etats, self.services)

        self.etats.pose(T_STATUT, statut)
        self.etats.pose(T_AMPS, str(bas if amps is None else amps),
                        min=bas, max=haut)
        self.etats.pose(T_SW, sw)
        self.etats.pose("switch.model3_charge_port_door", "off")
        self.etats.pose("number.model3_charge_limit", "80", min=50, max=100)
        if puissance is not None:
            self.etats.pose(T_PW, str(puissance), unit_of_measurement="W")

        self.d = self.tesla.TeslaDriver(self.hass, None, {
            "ev_tesla_status": T_STATUT, "ev_tesla_amps": T_AMPS})
        self.pret = asyncio.run(self.d.async_prepare()) if prepare else None
        self.services.vider()

    def statut(self, s):
        self.etats.pose(T_STATUT, s)

    def interrupteur(self, s):
        self.etats.pose(T_SW, s)

    def puissance(self, w):
        if w is None:
            self.etats.retire(T_PW)
        else:
            self.etats.pose(T_PW, str(w), unit_of_measurement="W")

    def applique(self, amperes, phases=3):
        asyncio.run(self.d.apply(amperes, phases))

    def cycles(self, n, amperes, phases=3, pas=10):
        for _ in range(n):
            self.applique(amperes, phases)
            self.horloge.avance(pas)

    # --- lectures pratiques -------------------------------------------
    def amperages(self):
        return [a.data.get("value") for a in self.services.appels
                if a.service == "set_value"]

    def commutations(self):
        return [(a.service, a.data.get("entity_id"))
                for a in self.services.appels if a.domaine == "switch"]


def manifeste():
    chemin = os.path.join(RACINE, "custom_components", "ha_pilote_com",
                          "manifest.json")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)
