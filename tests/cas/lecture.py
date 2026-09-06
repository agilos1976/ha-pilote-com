# -*- coding: utf-8 -*-
"""Ce que le pilote lit sur la borne.

Tout le reste en dépend : une puissance mal convertie fait croire que rien ne
circule et déclenche l'échelle de réveil sur une voiture qui charge très bien.
Une entité mal reconnue fait perdre silencieusement une fonction entière.
"""

from faux import Banc, Inscription, ENTITES


def executer(t):
    # ----------------------------------------- résolution des entités
    b = Banc()
    t.egal(b.d.e.get("power"), "sensor.borne_puissance_totale_borne",
           "le capteur de puissance est reconnu par son unique_id")
    t.egal(b.d.e.get("override"), "button.borne_ignorer_la_programmation",
           "le bouton « ignorer la programmation » est reconnu")
    t.egal(b.d.entites_manquantes(), [],
           "avec toutes les entités présentes, rien n'est signalé manquant")

    # L'unique_id l'emporte sur le nom. Un utilisateur qui renomme ses entités,
    # ou qui utilise Home Assistant en anglais, doit être piloté pareil.
    renommees = [
        Inscription("sensor.wallbox_state", "AB123_status"),
        Inscription("sensor.truc_bidule", "AB123_power", "power"),
        Inscription("switch.autre_chose", "AB123_smartCharging"),
    ]
    b2 = Banc(entites=renommees, statut_eid="sensor.wallbox_state")
    t.egal(b2.d.e.get("power"), "sensor.truc_bidule",
           "des entités renommées restent reconnues par leur unique_id")
    t.vrai("override" in b2.d.entites_manquantes(),
           "une entité absente est nommée dans les manquantes")

    # Deux capteurs de puissance sans unique_id reconnaissable : on ne devine
    # pas. Choisir au hasard donnerait une mesure fausse sans le dire.
    ambigues = [
        Inscription("sensor.borne_statut", "AB123_status"),
        Inscription("sensor.borne_p1", "xx_aaa", "power"),
        Inscription("sensor.borne_p2", "xx_bbb", "power"),
    ]
    b3 = Banc(entites=ambigues)
    t.egal(b3.d.e.get("power"), None,
           "deux capteurs de puissance ambigus : aucun n'est choisi au hasard")

    # ------------------------------------------------- la puissance
    b = Banc(puissance=7000, unite="W")
    t.egal(b.d.power_w(), 7000.0, "une mesure en W est lue telle quelle")
    b.puissance(7.2, unite="kW")
    t.egal(b.d.power_w(), 7200.0, "une mesure en kW est convertie en W")
    b.puissance("unknown")
    t.egal(b.d.power_w(), None, "une mesure indisponible ne vaut pas zéro")
    b.puissance(None)
    t.egal(b.d.power_w(), None, "un capteur absent ne vaut pas zéro")

    # ---------------------------------------------- charge en cours
    # Le piège corrigé en v1.25 : sans capteur de puissance, se fier à la seule
    # mesure rendait « rien ne circule » en permanence, et l'échelle de réveil
    # montait jusqu'à couper la borne sur une charge parfaite.
    b = Banc(statut="charging", puissance=None)
    t.egal(b.d.power_w(), None, "sans capteur, la mesure est inconnue")
    t.egal(b.d.charge_en_cours(), True,
           "sans capteur, l'état « charging » suffit à dire que ça circule")
    b.statut("ready_to_charge")
    t.egal(b.d.charge_en_cours(), False,
           "sans capteur, « ready_to_charge » dit que rien ne circule")
    b.statut("unknown")
    t.egal(b.d.charge_en_cours(), None,
           "ni mesure ni état : le pilote répond « je ne sais pas », pas « non »")

    b = Banc(statut="ready_to_charge", puissance=7000)
    t.egal(b.d.charge_en_cours(), True,
           "la mesure l'emporte sur l'état : 7 kW pendant « ready_to_charge »")
    b.puissance(50)
    t.egal(b.d.charge_en_cours(), False,
           "50 W ne sont pas une charge — c'est la veille de la borne")

    # ------------------------------------------------- calibre du circuit
    b = Banc(calibre=25)
    t.egal(b.d.max_amps(), 25, "le calibre du circuit est lu sur le statut")
    b.etats.pose("sensor.borne_statut", "charging")   # sans l'attribut
    t.egal(b.d.max_amps(), None,
           "sans l'attribut, le calibre est inconnu et non supposé")

    # ------------------------------------------------- branchement, lien
    b = Banc(statut="disconnected")
    t.egal(b.d.plugged(), False, "« disconnected » : aucun véhicule présenté")
    b.statut("charging")
    t.egal(b.d.plugged(), True, "« charging » : un véhicule est branché")
    b.statut("unknown")
    t.egal(b.d.plugged(), None, "état inconnu : ni branché ni débranché")

    b = Banc()
    b.etats.pose("binary_sensor.borne_en_ligne", "off")
    t.egal(b.d.available(), False, "borne hors ligne : indisponible")

    # ------------------------------------------------------ la raison
    b = Banc()
    b.etats.pose("sensor.borne_raison", "car_not_charging")
    t.egal(b.d.raison(), "car_not_charging",
           "la raison publiée par la borne est relayée telle quelle")
    b.etats.pose("sensor.borne_raison", "unknown")
    t.egal(b.d.raison(), "",
           "une raison indisponible ne remonte pas comme un motif")
