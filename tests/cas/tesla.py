# -*- coding: utf-8 -*-
"""Borne Tesla : la borne ouvre le robinet, la voiture décide du débit.

Deux pièges propres à cette marque, et les deux se paient cher :

1. **Couper ne peut pas passer par l'ampérage.** Le minimum d'une Tesla est de
   5 A ; sur trois phases cela fait encore 3.4 kW. Un pilote qui « arrête » en
   baissant la consigne laisserait la voiture charger au tarif de pointe en
   croyant l'avoir stoppée.
2. **L'interrupteur de charge se trouve parmi des homonymes.** Un véhicule
   Tesla expose « charge_port_door » et « charge_limit », qui contiennent tous
   deux le mot « charge » sans commander quoi que ce soit. Se tromper ouvre la
   trappe de recharge au lieu de lancer la charge.
"""

import asyncio

from faux import BancTesla, Inscription, T_AMPS, T_SW, T_STATUT


def executer(t):
    T = BancTesla().tesla

    # ------------------------------------------- résolution de l'interrupteur
    b = BancTesla()
    t.egal(b.pret, True, "les deux entités suffisent à démarrer le pilote")
    t.egal(b.d.sw, T_SW,
           "l'interrupteur de charge est retrouvé sur l'appareil du véhicule")
    t.vrai(b.d.sw != "switch.model3_charge_port_door",
           "la trappe de recharge n'est pas prise pour l'interrupteur de charge")
    t.egal(b.d.pw, "sensor.model3_charger_power",
           "le capteur de puissance de charge est reconnu")

    # Sans interrupteur, on REFUSE de démarrer. Un pilote qui ne sait pas
    # arrêter est plus dangereux que pas de pilote du tout.
    sans_sw = [
        Inscription("sensor.wall_connector_status", "WC42_status", None, "b"),
        Inscription("number.model3_charging_amps", "VIN9_charging_amps", None, "v"),
        Inscription("switch.model3_charge_port_door", "VIN9_charge_port_door",
                    None, "v"),
    ]
    b2 = BancTesla(entites=sans_sw)
    t.egal(b2.pret, False,
           "aucun interrupteur de charge : le pilote refuse de démarrer "
           "plutôt que de faire croire qu'il sait s'arrêter")

    # ------------------------------------------------ la consigne de courant
    b = BancTesla(statut="charging", puissance=7000, bas=5, haut=16, sw="off")
    b.applique(10)
    t.egal(b.amperages(), [10], "la consigne s'écrit sur la voiture")
    t.egal([a.data.get("entity_id") for a in b.services.appels
            if a.service == "set_value"], [T_AMPS],
           "et bien sur l'entité d'ampérage du véhicule")
    noms = [a.service for a in b.services.appels]
    t.vrai(noms.index("set_value") < noms.index("turn_on"),
           "l'ampérage est posé AVANT d'ouvrir le robinet — sinon la voiture "
           "démarre sur son ancienne consigne")

    b.interrupteur("on")
    b.services.vider()
    b.horloge.avance(90)
    b.applique(10)
    t.egal(b.services.appels, [],
           "consigne inchangée et charge en cours : aucune commande — une "
           "Tesla endormie se réveille à chaque ordre")

    b.services.vider()
    b.applique(13)
    t.egal(b.amperages(), [13], "une consigne qui change est écrite une fois")

    # ------------------------------------ ce que la voiture accepte fait loi
    b = BancTesla(bas=5, haut=16, sw="on")
    b.applique(32)
    t.egal(b.amperages(), [16],
           "32 A demandés, 16 A écrits : c'est le maximum du véhicule")
    t.egal(b.d.max_amps(), 16, "le plafond est celui que la voiture publie")

    # ------------------------------------------------ l'arrêt coupe vraiment
    b = BancTesla(statut="charging", puissance=7000, sw="on")
    b.applique(10)
    b.horloge.avance(90)
    b.services.vider()
    b.applique(0)
    t.vrai(("turn_off", T_SW) in b.commutations(),
           "la consigne nulle coupe l'interrupteur de charge")
    t.egal(b.amperages(), [],
           "et NE passe pas par l'ampérage — 5 A sur trois phases font encore "
           "3.4 kW, ce n'est pas un arrêt")
    t.egal(b.d.amps, 0, "la mémoire de consigne est remise à zéro")

    # ------------------------------- on ne bascule pas l'interrupteur sans fin
    b = BancTesla(statut="charging", puissance=7000, sw="on")
    b.services.vider()
    b.cycles(30, 0, pas=10)          # 300 s d'arrêt demandé
    coupures = [c for c in b.commutations() if c[0] == "turn_off"]
    t.vrai(len(coupures) <= 5,
           "l'interrupteur n'est pas commandé à chaque cycle (%d fois en "
           "300 s) — chaque ordre réveille la voiture" % len(coupures))

    b = BancTesla(statut="charging", puissance=7000, sw="on")
    b.interrupteur("off")
    b.services.vider()
    b.cycles(20, 0, pas=10)
    t.egal(b.commutations(), [],
           "déjà coupée : aucune commande répétée dans le vide")

    # ------------------------------------------ les phases ne se pilotent pas
    # Une Wall Connector est câblée une fois pour toutes. On l'ignore, mais on
    # le dit — le nombre de phases déclaré côté site doit être le bon.
    b = BancTesla(statut="charging", puissance=7000, sw="on")
    b.applique(10, 3)
    b.horloge.avance(60)
    b.services.vider()
    b.applique(10, 1)
    t.egal([a for a in b.services.appels if "phase" in a.service], [],
           "aucune tentative de bascule de phases")
    t.egal(b.services.appels, [],
           "et une demande de phases différente ne provoque aucune écriture")

    # -------------------------------------------------------- les lectures
    b = BancTesla(statut="charging", puissance=7000)
    t.egal(b.d.charge_en_cours(), True, "7 kW mesurés : la charge est en cours")
    t.egal(b.d.plugged(), True, "« charging » : le câble est branché")
    b.statut("disconnected")
    t.egal(b.d.plugged(), False, "« disconnected » : aucun véhicule présenté")
    b.statut("unknown")
    t.egal(b.d.plugged(), None, "état illisible : ni branché ni débranché")

    # La raison remonte en CODE BRUT, comme chez Easee : la mise en forme
    # appartient au cockpit, qui seul dispose des textes et des icônes.
    # La dupliquer ici la placerait à deux endroits, dont un sans traduction.
    b = BancTesla(statut="complete", puissance=0)
    t.egal(b.d.charge_en_cours(), False, "batterie pleine : rien ne circule")
    t.egal(b.d.raison(), "complete",
           "la raison remonte en code brut, pas en phrase toute faite")
    b = BancTesla(statut="nopower", puissance=0)
    t.egal(b.d.raison(), "nopower", "« nopower » remonte tel quel")
    b = BancTesla(statut="charging", puissance=7000)
    t.egal(b.d.raison(), "",
           "une charge qui se déroule bien n'a aucune raison à donner")

    # Sans capteur de puissance, l'état tranche — le piège déjà payé sur Easee.
    b = BancTesla(statut="charging", puissance=None)
    t.egal(b.d.power_w(), None, "sans capteur, la mesure est inconnue")
    t.egal(b.d.charge_en_cours(), True,
           "sans capteur, « charging » suffit à dire que ça circule")
    t.vrai("puissance" in b.d.entites_manquantes(),
           "et l'absence du capteur est signalée")

    # ------------------------------------------- l'état réel prime sur la mémoire
    # Leçon d'Easee : une mémoire interne dit ce que NOUS avons demandé, pas ce
    # que la voiture fait. L'application Tesla peut relancer la charge.
    b = BancTesla(statut="charging", puissance=7000, sw="on")
    b.applique(0)
    b.horloge.avance(120)
    b.interrupteur("on")             # quelqu'un d'autre a relancé
    b.services.vider()
    b.applique(0)
    t.vrai(("turn_off", T_SW) in b.commutations(),
           "la charge relancée ailleurs est de nouveau coupée : c'est l'état "
           "lu qui tranche, pas notre souvenir")

    # ------------------------------------------------------ rendre la voiture
    b = BancTesla(bas=5, haut=16, sw="off")
    b.services.vider()
    asyncio.run(b.d.release())
    t.egal(b.amperages(), [16], "en se retirant, le pilote rend le plein débit")
    t.vrai(("turn_on", T_SW) in b.commutations(),
           "et réautorise la charge")
