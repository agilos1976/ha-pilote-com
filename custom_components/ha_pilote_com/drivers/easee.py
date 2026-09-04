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
2. time_to_live se compte en MINUTES et doit etre NON NUL. J avais ecrit ici
   l inverse — « doit valoir 0, sinon la limite expire » — et c etait faux :
   l automatisation de l utilisateur, qui fait charger la voiture depuis des
   mois, pose 15 minutes et reecrit toutes les 5. Avec 0 la consigne ne prend
   pas, l appel Home Assistant reussit quand meme, et la borne garde la limite
   precedente. Pilote croyait piloter le courant sans jamais y toucher.
   Corollaire : la limite porte une echeance, il faut donc la RENOUVELER
   regulierement, pas seulement quand la valeur change.
3. La recharge intelligente Easee doit rester a l'arret : active, elle decide
   du courant a notre place et entre en conflit avec le planning du cockpit.
4. Ouvrir une session demande une commande explicite (start) ; regler le
   courant ne suffit pas.
"""

from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.helpers import entity_registry as er

from . import WallboxDriver
from ..const import CONF_EV_EASEE_STATUS

_LOGGER = logging.getLogger(__name__)

# Duree de vie de la consigne de courant, en minutes, et cadence de
# renouvellement. Trois fois plus court que l echeance : une ecriture perdue
# ne laisse pas la limite retomber.
TTL_LIMITE = 15
RENOUVELLEMENT = 300

# Intervalle minimal entre deux commandes d'ouverture de session.
START_MIN_INTERVAL = 60
# Idem pour la mise en pause, quand la borne refuse de s'arreter.
PAUSE_MIN_INTERVAL = 60

# --- Reveil d'un vehicule en veille profonde -------------------------------
# Une voiture laissee branchee sans charger finit par endormir son calculateur
# de charge, pour ne pas vider sa batterie 12 V. Elle ne surveille alors plus
# le signal pilote, et rouvrir la session ne sert a rien : repeter 'start' ne
# produit aucune transition, et c'est la transition qui reveille.
#
# D'ou une echelle de trois barreaux, du plus doux au plus brutal. Chacun
# provoque une rupture du signal plus franche que le precedent ; on ne monte
# d'un cran que si le precedent n'a rien donne.
REVEIL_APRES    = 150   # s de courant offert sans qu'un ampere circule
REVEIL_INTERVAL = 180   # s entre deux tentatives
REVEIL_MAX      = 3     # tentatives par branchement

# Statuts pour lesquels aucun vehicule n'est presente a la borne.
HORS_SESSION = ("disconnected", "unavailable", "unknown", "none", "")

# La borne tient la session fermee parce qu'une PROGRAMMATION lui dit d'attendre
# son heure. Aucune commande d'ouverture n'en vient a bout : 'start' demande a
# la borne de charger, le programme lui dit de ne pas le faire, et le programme
# gagne. Le seul geste qui passe outre est 'override_schedule' — d'ou le bouton
# « Ignorer la programmation » qu'Easee expose sur l'appareil.
EN_ATTENTE_PROGRAMME = ("awaiting_start", "awaiting_authorization", "awaiting_schedule")
# Une fois toutes les cinq minutes suffit ; on ne martele pas un bouton.
OVERRIDE_MIN_INTERVAL = 300

# Intervalle de reecriture de la consigne de courant quand rien ne circule.
RELANCE_LIMITE = 120

# Comment reconnaitre les entites voisines sur l'appareil. Trois couches, de
# la plus fiable a la plus faible :
#
#   1. unique_id — pose par l'integration, invisible et non modifiable par
#      l'utilisateur, identique quelle que soit la langue de l'interface.
#   2. device_class — semantique standard de Home Assistant, elle aussi
#      independante de la langue et du nom donne a l'entite.
#   3. entity_id — dernier recours seulement : il derive du nom au moment de
#      la creation, donc de la locale, et se renomme librement.
#
# La premiere couche qui repond l'emporte. Se fier au seul entity_id, comme
# je l'avais d'abord fait, revient a parier sur la langue de l'utilisateur et
# sur le fait qu'il n'a jamais renomme ses entites.
RESOLUTION = {
    "power": {
        "domaine": "sensor",
        "unique":  ("_power", "_totalpower", "_total_power"),
        "classe":  ("power",),
        "suffixe": ("_puissance_totale_borne", "_puissance", "_power"),
    },
    "online": {
        "domaine": "binary_sensor",
        "unique":  ("_online", "_isonline"),
        "classe":  ("connectivity",),
        "suffixe": ("_en_ligne", "_online"),
    },
    "enable": {
        "domaine": "switch",
        "unique":  ("_isenabled", "_is_enabled", "_enabled"),
        "classe":  (),
        "suffixe": ("_chargeur_active", "_enabled", "_is_enabled"),
    },
    "smart":  {
        "domaine": "switch",
        "unique":  ("_smartcharging", "_smart_charging"),
        "classe":  (),
        "suffixe": ("_recharge_intelligente", "_smart_charging"),
    },
    # Easee publie lui-meme la raison pour laquelle il ne delivre rien :
    # file d attente, aucune demande du vehicule, limite trop basse, charge
    # programmee en attente... C est la reponse a la question qu on se pose
    # justement quand la borne est prete et que rien ne circule. Elle est
    # desactivee par defaut chez Home Assistant, donc absente de voisines
    # tant que l utilisateur ne l active pas — et signalee comme manquante.
    "raison": {
        "domaine": "sensor",
        "unique":  ("_reasonfornocurrent", "_reason_for_no_current"),
        "classe":  (),
        "suffixe": ("_raison_de_l_absence_de_courant", "_reason_for_no_current",
                    "_raison_absence_courant"),
    },
    "override": {
        "domaine": "button",
        "unique":  ("_override_schedule", "_overrideschedule"),
        "classe":  (),
        "suffixe": ("_ignorer_la_programmation", "_override_schedule",
                    "_ignorer_la_programmation_de_charge"),
    },
}


# Repli quand l'entite de statut designee n'a plus d'etat. Tenue a l'ecart de
# RESOLUTION : ce n'est pas une entite facultative de plus, c'est un secours
# pour celle que l'utilisateur a lui-meme choisie.
RESOLUTION_STATUT = {
    "domaine": "sensor",
    "unique":  ("_status", "_chargerstatus", "_charger_status"),
    "classe":  (),
    "suffixe": ("_statut", "_status"),
}


# Ce que l'on perd si une entite n'est pas reconnue.
DEGRADATION = {
    "power":  "la mesure de puissance envoyee au serveur",
    "online":  "la detection de borne hors ligne",
    "enable":  "le reveil de la borne si elle a ete desactivee",
    "smart":   "la garantie que la recharge intelligente Easee ne reprend pas la main",
    "raison":  "l explication que la borne donne quand elle ne delivre rien",
    "override": "la possibilite de passer outre une programmation de la borne",
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
        self.dernier_start = 0.0
        self.dernier_pause = 0.0
        # Depuis quand du courant est offert sans qu'un ampere circule, et ou
        # en est l'echelle de reveil pour ce branchement.
        self.offre_depuis = 0.0
        self.reveils = 0
        self.dernier_reveil = 0.0
        self.reveil_dit = False
        self.dernier_override = 0.0
        self.derniere_limite = 0.0

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

        voisines = [
            e for e in er.async_entries_for_device(
                reg, self.device_id, include_disabled_entities=False)
            if e.entity_id != self.status
        ]
        for role, r in RESOLUTION.items():
            trouve = self._resoudre(voisines, r)
            if trouve:
                self.e[role] = trouve

        # Une entite peut figurer au registre sans avoir d etat : elle a ete
        # desactivee, ou renommee puis recreee. async_prepare se contentait de
        # la trouver au registre — il passait donc — et tout le reste echouait
        # ensuite en silence : _statut() rendait "", plugged() rendait None,
        # l etat de la borne n arrivait jamais au serveur, et le cockpit
        # n avait plus que la puissance AUTORISEE a afficher.
        #
        # En AVERTISSEMENT, pas en INFO : le panneau des journaux de Home
        # Assistant n affiche pas les INFO, et ce diagnostic-la doit se voir.
        if self.hass.states.get(self.status) is None:
            repli = self._resoudre(voisines, RESOLUTION_STATUT)
            if repli is not None and self.hass.states.get(repli) is not None:
                _LOGGER.warning(
                    "Easee : %s figure au registre mais n a aucun etat "
                    "(entite desactivee ?). Le pilote se rabat sur %s, trouve "
                    "sur le meme appareil.", self.status, repli)
                self.status = repli
            else:
                _LOGGER.warning(
                    "Easee : %s figure au registre mais n a aucun etat — "
                    "entite desactivee ? Sans statut, le pilote ignore si la "
                    "voiture est branchee et si elle charge. Reactive cette "
                    "entite, ou reconfigure l integration en designant le "
                    "capteur de statut de la borne.", self.status)

        manquant = [r for r in RESOLUTION if r not in self.e]
        _LOGGER.info(
            "Easee : statut=%s puissance=%s lien=%s actif=%s intelligente=%s "
            "ignorer-programme=%s",
            self.status, self.e.get("power", "-"), self.e.get("online", "-"),
            self.e.get("enable", "-"), self.e.get("smart", "-"),
            self.e.get("override", "-"),
        )
        if manquant:
            # Aucune de ces entites n'est indispensable — le pilotage marche
            # sans, en degradant. Le dire evite de chercher longtemps pourquoi
            # la puissance reste a zero ou la recharge intelligente reprend.
            _LOGGER.warning(
                "Easee : entites non reconnues sur l'appareil (%s). Le pilotage "
                "fonctionne mais perd %s.",
                ", ".join(manquant),
                " et ".join(DEGRADATION[m] for m in manquant),
            )
        return True

    @staticmethod
    def _resoudre(voisines, regle):
        """Cherche une entite selon les trois couches, dans l'ordre."""
        cands = [e for e in voisines if e.entity_id.startswith(regle["domaine"] + ".")]
        for e in cands:
            uid = (e.unique_id or "").lower()
            if any(uid.endswith(u) for u in regle["unique"]):
                return e.entity_id
        if regle["classe"]:
            classes = [
                e for e in cands
                if (e.device_class or e.original_device_class) in regle["classe"]
            ]
            # Une seule candidate : aucune ambiguite. Plusieurs capteurs de
            # puissance sur la meme borne, on ne devine pas et on passe a la
            # couche suivante plutot que de choisir au hasard.
            if len(classes) == 1:
                return classes[0].entity_id
        for e in cands:
            if any(e.entity_id.endswith(s) for s in regle["suffixe"]):
                return e.entity_id
        return None

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

    def entites_manquantes(self):
        manque = [r for r in RESOLUTION if r not in self.e]
        if self._st(self.status) is None:
            manque.append("statut")
        return manque

    def etat(self):
        return self._statut()

    def raison(self):
        st = self._st(self.e.get("raison"))
        if st is None or st.state in ("unknown", "unavailable", "", None):
            return ""
        return st.state

    def charge_en_cours(self):
        """La mesure d'abord, l'etat en repli.

        Le capteur de puissance est facultatif : s'il n'a pas ete reconnu sur
        l'appareil, il ne reste que l'etat publie par la borne. Il est plus
        grossier — Easee passe par 'ready_to_charge' a chaque renegociation,
        y compris quand la voiture charge tres bien — mais il vaut infiniment
        mieux que rien, qui se lisait jusqu'ici comme « rien ne circule ».
        """
        pw = self.power_w()
        if pw is not None:
            return pw > 200
        s = self._statut()
        if s in ("unavailable", "unknown", ""):
            return None
        return s == "charging"

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
        # Chaque ecriture est tracee. Par conception elles sont rares : une
        # consigne stable ne doit rien produire ici. Si le journal en montre
        # toutes les dix secondes, c'est que quelqu'un d'autre bouscule la
        # borne — et le savoir vaut mieux que de le deduire.
        _LOGGER.info("Easee <- %s %s", service,
                     " ".join("%s=%s" % (k, v) for k, v in data.items()))
        await self.hass.services.async_call(
            "easee", service, dict(data, device_id=self.device_id), blocking=True)

    async def _limite(self, amperes: int, reemettre: bool = True):
        """Ecrit la limite dynamique de courant.

        reemettre : passer d abord par une valeur voisine, pour forcer la borne
        a re-emettre son signal — reecrire la meme valeur ne produit rien de
        visible pour la voiture. Inutile lors d un simple renouvellement
        d echeance, ou la valeur ne change pas et la charge est en cours.
        """
        self.derniere_limite = time.monotonic()
        if reemettre:
            plafond = self.max_amps() or 32
            voisin = amperes - 1 if amperes >= plafond else amperes + 1
            if voisin < 6:
                voisin = amperes + 1
            await self._svc("set_charger_dynamic_limit",
                            {"current": voisin, "time_to_live": TTL_LIMITE})
            await asyncio.sleep(2)
        await self._svc("set_charger_dynamic_limit",
                        {"current": amperes, "time_to_live": TTL_LIMITE})

    async def _intelligente_off(self):
        eid = self.e.get("smart")
        st = self._st(eid)
        if st is not None and st.state == "on":
            _LOGGER.info(
                "Easee : recharge intelligente desactivee — elle deciderait "
                "du courant a la place du planning Pilote")
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": eid}, blocking=True)

    async def _ignorer_programme(self) -> bool:
        """Passe outre une programmation de la borne.

        Une borne en 'awaiting_start' n a pas refuse la charge : elle attend
        l heure que son programme lui a fixee. Lui envoyer 'start' ne sert a
        rien, le programme reprend la main aussitot — et l echelle de reveil ne
        peut rien non plus, puisque la voiture, elle, va tres bien. C est la
        borne qui dit non.
        """
        eid = self.e.get("override")
        if not eid:
            return False
        maintenant = time.monotonic()
        if maintenant - self.dernier_override < OVERRIDE_MIN_INTERVAL:
            return False
        self.dernier_override = maintenant
        _LOGGER.info(
            "Easee : la borne est en '%s' — une programmation lui dit "
            "d attendre. Pilote passe outre (%s).", self._statut(), eid)
        await self.hass.services.async_call(
            "button", "press", {"entity_id": eid}, blocking=True)
        return True

    async def _reveil(self, amperes: int) -> None:
        """Provoque une transition du signal pilote pour reveiller le vehicule.

        Trois barreaux, du plus doux au plus franc. On ne monte d'un cran que
        si le precedent n'a rien donne, parce que chacun coute plus cher que
        le precedent en renegociation pour la voiture.
        """
        self.reveils += 1
        self.dernier_reveil = time.monotonic()
        attente = int(self.dernier_reveil - self.offre_depuis)
        _LOGGER.warning(
            "Easee : %d s de courant offert sans qu'un ampere circule — le "
            "vehicule est probablement en veille profonde. Tentative de "
            "reveil %d/%d.", attente, self.reveils, REVEIL_MAX)

        if self.reveils == 1:
            # Refermer puis rouvrir la session. La borne retire sa modulation
            # et la re-emet : cela suffit a un vehicule simplement assoupi.
            await self._svc("action_command", {"action_command": "pause"})
            await asyncio.sleep(4)
            await self._svc("action_command", {"action_command": "resume"})
            await asyncio.sleep(2)
            await self._svc("action_command", {"action_command": "start"})
            self.paused = False
            self.dernier_start = time.monotonic()
            # Rouvrir une session remet parfois la limite au calibre du
            # circuit : on oublie la notre pour la faire reecrire au cycle
            # suivant. Meme piege que dans la bascule de phases.
            self.amps = None
            return

        if self.reveils == 2:
            # Une limite nulle fait disparaitre la modulation elle-meme ; la
            # remonter la recree de zero. La rupture est plus nette qu'un
            # pause/resume, que la borne peut traiter sans couper le signal.
            #
            # try/finally imperatif : entre la mise a zero et sa restauration,
            # une exception, un redemarrage de Home Assistant ou une liaison
            # Easee defaillante laisserait la borne a 0 A. Elle afficherait
            # alors 'ready_to_charge' en delivrant 0 kW — indiscernable d'une
            # voiture qui refuse — et rien ne l'en sortirait, puisque apply()
            # ne reecrit la limite que si elle differe de sa memoire.
            #
            # self.amps = None, jamais la valeur voulue : on ne prend pas pour
            # acquis ce qu'on n'a pas verifie. Le cycle suivant reecrira.
            try:
                await self._svc("set_charger_dynamic_limit",
                                {"current": 0, "time_to_live": TTL_LIMITE})
                await asyncio.sleep(6)
            finally:
                self.amps = None
                await self._limite(amperes)
            await self._svc("action_command", {"action_command": "resume"})
            await asyncio.sleep(2)
            await self._svc("action_command", {"action_command": "start"})
            self.paused = False
            self.dernier_start = time.monotonic()
            return

        # Dernier recours : desactiver la borne. Le vehicule voit disparaitre
        # le signal pilote lui-meme, ce qui equivaut electriquement au
        # debranchement — le seul geste dont on sait qu'il reveille tout le
        # monde, et celui qu'on cherche justement a eviter a l'utilisateur.
        #
        # Rester coupee n'est pas un risque : la remise en marche est reecrite
        # plus haut a chaque consigne >= 6 A, y compris apres un redemarrage de
        # Home Assistant qui interromprait cette sequence.
        eid = self.e.get("enable")
        if not eid:
            _LOGGER.warning(
                "Easee : dernier recours indisponible — l'interrupteur "
                "d'activation de la borne n'a pas ete reconnu sur l'appareil.")
            return
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": eid}, blocking=True)
        await asyncio.sleep(8)
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": eid}, blocking=True)
        await asyncio.sleep(3)
        await self._limite(amperes)
        self.amps = amperes
        await self._svc("action_command", {"action_command": "start"})
        self.paused = False
        self.dernier_start = time.monotonic()

    async def apply(self, amperes: int, phases: int) -> None:
        plafond = self.max_amps()
        if plafond and amperes:
            amperes = min(amperes, plafond)

        # Un debranchement solde l'echelle : le vehicule suivant n'a pas a
        # payer les tentatives infructueuses du precedent.
        if self._statut() in HORS_SESSION:
            self.offre_depuis = 0.0
            self.reveils = 0
            self.dernier_reveil = 0.0
            self.reveil_dit = False

        if amperes and amperes > 0:
            await self._intelligente_off()

            eid = self.e.get("enable")
            st = self._st(eid)
            if st is not None and st.state != "on":
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": eid}, blocking=True)

            if phases and phases != self.phases:
                # Le nombre de phases alimentees ne se change pas en cours de
                # session : le signal pilote ne le transporte pas, la voiture
                # continue sur la configuration negociee au demarrage. J'avais
                # ecrit ici qu'Easee encaissait la bascule a chaud — c'etait une
                # affirmation, pas une verification, et la voiture restait sur
                # l'ancienne configuration.
                #
                # On coupe donc le pilote, on change, puis on rouvre. Les
                # automatisations d'origine de l'utilisateur font de meme : elles
                # reglent le mode AVANT le start, jamais pendant.
                en_charge = self._statut() == "charging"
                if en_charge:
                    await self._svc("action_command", {"action_command": "pause"})
                    await asyncio.sleep(3)
                await self._svc(
                    "set_charger_phase_mode",
                    {"phase_mode": "3_phase" if phases >= 3 else "1_phase"})
                await asyncio.sleep(5)
                self.phases = phases
                if en_charge:
                    await self._svc("action_command", {"action_command": "resume"})
                    await asyncio.sleep(2)
                    await self._svc("action_command", {"action_command": "start"})
                    self.dernier_start = time.monotonic()
                    self.paused = False
                    # La consigne de courant sera reecrite ci-dessous : la
                    # reouverture de session la remet parfois au calibre.
                    self.amps = None

            if amperes != self.amps:
                # Ecriture SIMPLE quand la valeur change. Le passage par une
                # valeur voisine n a de sens que pour forcer la borne a
                # re-emettre une consigne INCHANGEE ; ici le changement suffit,
                # et la valeur intermediaire ajoute une seconde transition du
                # signal pilote a deux secondes de la premiere.
                #
                # Une Tesla l encaisse, une DS3 non : elle charge sans faillir
                # en « Plein immediat », ou la consigne ne bouge jamais, et
                # abandonne au bout de deux minutes en « Solaire d abord », ou
                # elle est modulee toutes les 30 a 60 secondes. Deux sauts de
                # PWM rapproches a chaque ajustement, quelques ajustements, et
                # la voiture se met en defaut jusqu au debranchement.
                await self._limite(amperes, reemettre=False)
                self.amps = amperes
            elif time.monotonic() - self.derniere_limite >= RENOUVELLEMENT:
                # La consigne expire au bout de TTL_LIMITE minutes. Ne l ecrire
                # que lorsqu elle change la laissait retomber en pleine charge —
                # c est exactement ce que fait l automatisation de reference,
                # qui la repose toutes les cinq minutes sans jamais la changer.
                await self._limite(amperes, reemettre=False)
                self.amps = amperes

            if self.paused:
                await self._svc("action_command", {"action_command": "resume"})
                self.paused = False
            # Ouvrir la session, mais pas six fois par minute. Le statut reste
            # 'ready_to_charge' tant que la voiture n'a pas repris la main :
            # renvoyer 'start' a chaque cycle de 10 s inonde l'API Easee et
            # relance une negociation que le vehicule n'a pas fini de refuser.
            # Ouvrir la session seulement si rien ne circule. Le statut passe
            # par 'ready_to_charge' a chaque renegociation, y compris quand la
            # voiture charge tres bien : renvoyer 'start' a ce moment-la relance
            # une negociation dont personne n'avait besoin, et c'est precisement
            # ce que montrent les allers-retours du journal Easee.
            # La mesure tranche quand elle existe, l etat sinon. Ne s appuyer
            # que sur power_w() etait un piege : le capteur de puissance est
            # facultatif, et absent il rendait None — donc circule=False en
            # permanence, meme pendant une charge parfaite. L echelle de reveil
            # serait alors montee jusqu a couper la borne sur une voiture qui
            # chargeait tres bien.
            circule = self.charge_en_cours()
            if circule is None:
                # Ni mesure ni etat exploitable : on ne reveille pas sur une
                # ignorance. Repeter 'start' reste sans danger, pas le reste.
                self.offre_depuis = 0.0
            elif circule:
                if self.reveils:
                    _LOGGER.info(
                        "Easee : le vehicule a repris le courant apres %d "
                        "tentative(s) de reveil.", self.reveils)
                self.offre_depuis = 0.0
                self.reveils = 0
                self.reveil_dit = False
                self.derniere_limite = 0.0
            elif self.offre_depuis == 0.0:
                self.offre_depuis = time.monotonic()

            if self._statut() != "charging" and not circule:
                maintenant = time.monotonic()
                # Une programmation de borne se traite AVANT tout le reste : ni
                # 'start' ni l echelle de reveil n y peuvent quoi que ce soit, et
                # attendre 150 s pour tenter des gestes inoperants ne ferait que
                # retarder le seul qui marche.
                if self._statut() in EN_ATTENTE_PROGRAMME:
                    if await self._ignorer_programme():
                        await asyncio.sleep(2)
                        await self._svc("action_command", {"action_command": "start"})
                        self.dernier_start = maintenant
                        return
                # La memoire de la limite dit ce que NOUS avons demande, pas ce
                # que la borne applique. Le fichier tire deja cette lecon pour
                # la pause ; elle vaut tout autant ici. Une limite restee a zero
                # — sequence interrompue, ecriture perdue, automatisation tierce
                # — se voit exactement comme une voiture qui refuse, et notre
                # memoire nous interdisait de la corriger.
                if (amperes >= 6
                        and maintenant - self.derniere_limite >= RELANCE_LIMITE):
                    self.derniere_limite = maintenant
                    _LOGGER.info(
                        "Easee : rien ne circule sous %d A autorises — la "
                        "consigne de courant est reecrite plutot que supposee.",
                        amperes)
                    await self._limite(amperes)
                    self.amps = amperes
                if maintenant - self.dernier_start >= START_MIN_INTERVAL:
                    await self._svc("action_command", {"action_command": "start"})
                    self.dernier_start = maintenant
                # Repeter 'start' ne reveille personne : la commande ne produit
                # aucune transition du signal pilote, et c'est la transition
                # que le vehicule endormi attend. Au bout de REVEIL_APRES on
                # change donc de moyen plutot que de repeter le meme.
                if (self.reveils < REVEIL_MAX
                        and self.offre_depuis > 0.0
                        and maintenant - self.offre_depuis >= REVEIL_APRES
                        and maintenant - self.dernier_reveil >= REVEIL_INTERVAL):
                    await self._reveil(amperes)
                elif self.reveils >= REVEIL_MAX and not self.reveil_dit:
                    _LOGGER.warning(
                        "Easee : les %d tentatives de reveil ont echoue. Le "
                        "vehicule ne repond plus au signal pilote ; seul un "
                        "debranchement puis rebranchement du cable le "
                        "relancera.", REVEIL_MAX)
                    self.reveil_dit = True
            else:
                self.dernier_start = 0.0
            return

        # Arret : on met la session en pause plutot que de la clore. Une
        # session close oblige la voiture a tout renegocier, et certaines
        # refusent de repartir sans debranchement physique.
        #
        # La memoire `self.paused` ne suffit pas : elle dit ce que NOUS avons
        # demande, pas ce que la borne fait. Si quelque chose d'autre relance
        # la charge — une automatisation, l'application Easee, la borne
        # elle-meme — nous croyions l'avoir arretee et ne renvoyions plus rien.
        # C'est la mesure qui tranche, pas le souvenir.
        pw = self.power_w()
        debite = (pw is not None and pw > 200)
        maintenant = time.monotonic()
        if self.paused is not True or (
                debite and maintenant - self.dernier_pause >= PAUSE_MIN_INTERVAL):
            if debite and self.paused is True:
                _LOGGER.warning(
                    "Easee : la borne delivre %.2f kW alors que Pilote demande "
                    "l'arret. Quelque chose d'autre la commande — automatisation "
                    "Home Assistant, application Easee, ou recharge intelligente.",
                    pw / 1000.0)
            await self._svc("action_command", {"action_command": "pause"})
            self.paused = True
            self.dernier_pause = maintenant
        self.amps = 0
        # Plus de courant offert : le chronometre du reveil n a plus d objet.
        # Le laisser armer aurait declenche une tentative des la reprise, sur
        # une attente accumulee alors que la borne etait a l arret.
        self.offre_depuis = 0.0

    async def release(self) -> None:
        """Rend la borne dans son comportement d'origine."""
        plafond = self.max_amps() or 16
        await self._svc("set_charger_dynamic_limit",
                        {"current": plafond, "time_to_live": TTL_LIMITE})
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
