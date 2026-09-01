"""Pilotes de bornes de recharge.

Le serveur decide, un pilote traduit. La consigne qui arrive de Pilote est
toujours la meme — un ampérage et un nombre de phases — et chaque pilote sait
comment l'exprimer dans le vocabulaire d'une marque.

Ce qui n'appartient PAS a un pilote : les horaires, les objectifs d'energie,
les seuils de surplus, les prix. Ces decisions vivent dans le cockpit, ou
elles disposent des previsions et du planning batterie. Un pilote qui se
mettrait a decider serait un second cerveau en desaccord avec le premier.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


class WallboxDriver:
    """Contrat commun a toutes les bornes."""

    marque = "generique"
    libelle = "Borne generique"

    def __init__(self, hass, entry, options):
        self.hass = hass
        self.entry = entry
        self.o = options
        # Derniere consigne appliquee : on n'ecrit que sur changement, une
        # borne reecrite en boucle use sa memoire et sature son lien reseau.
        self.amps = None
        self.phases = None

    async def async_prepare(self) -> bool:
        """Resout ce dont le pilote a besoin.

        Retourne False si la borne est inexploitable en l'etat — le pilotage
        est alors desactive proprement au lieu d'echouer a chaque cycle.
        """
        return True

    def describe(self) -> str:
        return self.libelle

    def available(self) -> bool:
        """La borne repond-elle ?"""
        return True

    def plugged(self):
        """True/False si l'information existe, None sinon."""
        return None

    def power_w(self):
        """Puissance de charge en W, ou None."""
        return None

    def etat(self):
        """Etat brut de la borne tel qu'elle le publie, ou "".

        Distinct de power_w() : le capteur de puissance est facultatif et peut
        ne pas etre reconnu, alors que l'etat vient de l'entite que
        l'utilisateur a lui-meme designee. Sans lui, le cockpit ne peut
        qu'annoncer la puissance AUTORISEE et la fait passer pour la puissance
        delivree — 11 kW affiches pendant que la voiture ne prend rien.
        """
        return ""

    def charge_en_cours(self):
        """True/False si la borne sait le dire, None sinon.

        C'est la reponse a « du courant circule-t-il ? », que power_w() donne
        au watt pres quand le capteur existe et que l'etat donne grossierement
        sinon.
        """
        return None

    def max_amps(self):
        """Plafond materiel connu de la borne, ou None.

        C'est une contrainte electrique (calibre du circuit), pas un reglage
        de confort : elle prime sur toute consigne recue.
        """
        return None

    async def apply(self, amperes: int, phases: int) -> None:
        """Applique la consigne. amperes == 0 signifie arreter la charge."""
        raise NotImplementedError

    async def release(self) -> None:
        """Rend la borne a l'utilisateur, dans un etat pleinement utilisable.

        Appele quand l'interrupteur de pilotage passe a l'arret. Une borne
        laissee coupee priverait l'utilisateur de recharge sans motif visible.
        """
        raise NotImplementedError


def create_driver(hass, entry, options):
    """Instancie le pilote correspondant a la marque choisie."""
    from ..const import CONF_EV_BRAND, EV_BRAND_EASEE, EV_BRAND_GENERIC
    from .easee import EaseeDriver
    from .generic import GenericDriver

    marque = options.get(CONF_EV_BRAND) or EV_BRAND_GENERIC
    if marque == EV_BRAND_EASEE:
        return EaseeDriver(hass, entry, options)
    return GenericDriver(hass, entry, options)
