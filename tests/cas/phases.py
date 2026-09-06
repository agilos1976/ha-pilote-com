# -*- coding: utf-8 -*-
"""La bascule mono / triphasé.

Le nombre de phases alimentées ne se change pas en cours de session : le signal
pilote ne le transporte pas, et la voiture continue sur la configuration
négociée au démarrage. Le fichier a longtemps affirmé qu'Easee encaissait la
bascule à chaud — c'était une affirmation, pas une vérification, et la voiture
restait sur l'ancienne configuration.
"""

from faux import Banc


def executer(t):
    # ------------------------------------------- première consigne
    b = Banc(statut="charging", puissance=7000)
    b.applique(10, 3)
    t.vrai(any(a.service == "set_charger_phase_mode" for a in b.services.appels),
           "la première consigne fixe explicitement le mode de phases")
    mode = [a for a in b.services.appels
            if a.service == "set_charger_phase_mode"][0]
    t.egal(mode.data.get("phase_mode"), "3_phase",
           "trois phases demandées, trois phases écrites")

    # ------------------------------------- consigne stable : rien à écrire
    b.services.vider()
    b.horloge.avance(30)
    b.applique(10, 3)
    t.vrai(not any(a.service == "set_charger_phase_mode"
                   for a in b.services.appels),
           "le même nombre de phases ne se réécrit pas")

    # --------------------------------------- bascule triphasé → monophasé
    b.services.vider()
    b.horloge.avance(30)
    b.applique(8, 1)
    noms = [a.service for a in b.services.appels]
    cmds = b.services.commandes()

    t.vrai("set_charger_phase_mode" in noms, "le mode de phases est réécrit")
    i_mode = noms.index("set_charger_phase_mode")
    t.egal([a for a in b.services.appels
            if a.service == "set_charger_phase_mode"][0].data.get("phase_mode"),
           "1_phase", "une phase demandée, une phase écrite")

    t.vrai("pause" in cmds, "le pilote est coupé avant de changer le mode")
    i_pause = noms.index("action_command")
    t.vrai(i_pause < i_mode,
           "la coupure précède le changement de mode, jamais l'inverse")
    t.vrai("resume" in cmds and "start" in cmds,
           "la session est rouverte après le changement")

    # La réouverture de session remet parfois la limite au calibre du circuit.
    # Reprendre notre mémoire pour argent comptant laissait la borne à 25 A
    # alors que Pilote croyait avoir demandé 8.
    t.vrai(any(a.data.get("current") == 8 for a in b.services.limites()),
           "la consigne de courant est réécrite après la bascule, au lieu "
           "d'être supposée intacte")

    # ------------------------------------ pas de coupure si rien ne charge
    b = Banc(statut="ready_to_charge", puissance=0)
    b.applique(10, 3)
    b.services.vider()
    b.horloge.avance(30)
    b.applique(8, 1)
    avant_mode = []
    for a in b.services.appels:
        if a.service == "set_charger_phase_mode":
            break
        if a.service == "action_command":
            avant_mode.append(a.data.get("action_command"))
    t.vrai("pause" not in avant_mode,
           "borne à l'arrêt : rien à couper avant de changer le mode")
