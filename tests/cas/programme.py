# -*- coding: utf-8 -*-
"""La borne attend l'heure que son programme lui a fixée.

Ce n'est pas un refus de charge : c'est la borne qui dit non, pas la voiture.
Lui envoyer « start » ne sert à rien — le programme reprend la main aussitôt —
et l'échelle de réveil n'y peut rien non plus, puisque le véhicule va très
bien. Le seul geste qui passe outre est le bouton « Ignorer la programmation ».

C'est la panne qui a immobilisé une borne chez un client, pendant que le
journal répétait « start » toutes les minutes sans que rien ne bouge.
"""

from faux import Banc


def executer(t):
    E = Banc().easee

    for statut in E.EN_ATTENTE_PROGRAMME:
        b = Banc(statut=statut, puissance=0)
        b.applique(12)
        boutons = [a for a in b.services.appels
                   if a.domaine == "button" and a.service == "press"]
        t.egal(len(boutons), 1,
               "« %s » : le bouton « ignorer la programmation » est pressé"
               % statut)
        if boutons:
            t.egal(boutons[0].data.get("entity_id"),
                   "button.borne_ignorer_la_programmation",
                   "« %s » : c'est bien le bouton de la borne" % statut)
        t.vrai("start" in b.services.commandes(),
               "« %s » : la session est ouverte juste après" % statut)

    # ------------------------------------- on ne martèle pas un bouton
    b = Banc(statut="awaiting_start", puissance=0)
    b.cycles(int(E.OVERRIDE_MIN_INTERVAL / 10) - 2, 12)   # juste sous l'intervalle
    presses = [a for a in b.services.appels if a.service == "press"]
    t.egal(len(presses), 1,
           "une seule pression en %d s (l'intervalle est de %d s)"
           % (E.OVERRIDE_MIN_INTERVAL - 20, E.OVERRIDE_MIN_INTERVAL))

    b.cycles(6, 12)                                        # on franchit l'intervalle
    presses = [a for a in b.services.appels if a.service == "press"]
    t.egal(len(presses), 2,
           "l'intervalle franchi, le bouton est pressé une seconde fois")

    # ------------------ l'échelle de réveil n'a rien à faire ici
    # « ni 'start' ni l'échelle de réveil n'y peuvent quoi que ce soit, et
    #   attendre 150 s pour tenter des gestes inopérants ne ferait que
    #   retarder le seul qui marche. » — le pilote, sur ce cas précis.
    b = Banc(statut="awaiting_start", puissance=0)
    b.cycles(60, 12)                                       # 600 s d'attente
    t.egal(b.d.reveils, 0,
           "aucune tentative de réveil sur une borne qui attend son "
           "programme — la voiture n'y est pour rien")
    interrupteurs = [a for a in b.services.appels
                     if a.domaine == "switch"
                     and a.data.get("entity_id") == "switch.borne_chargeur_active"
                     and a.service == "turn_off"]
    t.vrai(not interrupteurs,
           "la borne n'est jamais désactivée à cause de sa propre programmation")

    # ------------------------------------ sans le bouton, on le dit
    from faux import Inscription
    sans_bouton = [
        Inscription("sensor.borne_statut", "AB123_status"),
        Inscription("sensor.borne_puissance_totale_borne", "AB123_power", "power"),
    ]
    b = Banc(statut="awaiting_start", puissance=0, entites=sans_bouton)
    b.applique(12)
    t.vrai("override" in b.d.entites_manquantes(),
           "le bouton absent est signalé comme entité manquante")
    t.ok("sans le bouton, le pilote continue sans lever d'erreur")
