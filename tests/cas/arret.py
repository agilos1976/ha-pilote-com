# -*- coding: utf-8 -*-
"""L'arrêt de la charge.

On met la session en pause plutôt que de la clore : une session close oblige la
voiture à tout renégocier, et certaines refusent de repartir sans débranchement
physique — impossible à demander quand la borne est chez un client.

La mémoire `paused` ne suffit pas : elle dit ce que NOUS avons demandé, pas ce
que la borne fait. Si autre chose relance la charge — une automatisation,
l'application Easee, la recharge intelligente — nous la croyions arrêtée et ne
renvoyions plus rien.
"""

from faux import Banc


def executer(t):
    E = Banc().easee

    # ------------------------------------------------- l'arrêt met en pause
    b = Banc(statut="charging", puissance=7000)
    b.applique(10)
    b.services.vider()
    b.applique(0)
    t.vrai("pause" in b.services.commandes(),
           "la consigne nulle met la session en pause")
    t.vrai("stop" not in b.services.commandes(),
           "la session n'est jamais close — certaines voitures ne repartiraient "
           "pas sans débrancher le câble")
    t.egal(b.d.amps, 0, "la mémoire de consigne est remise à zéro")

    # ---------------------------------------- on ne répète pas dans le vide
    b.puissance(0)
    b.services.vider()
    b.cycles(30, 0)                                  # 300 s à l'arrêt
    t.egal(b.services.commandes(), [],
           "borne effectivement arrêtée : aucune commande répétée pendant 300 s")

    # ------------------------- mais si elle débite quand même, on insiste
    b = Banc(statut="charging", puissance=7000)
    b.applique(0)
    b.services.vider()
    b.horloge.avance(E.PAUSE_MIN_INTERVAL + 10)
    b.applique(0)
    t.vrai("pause" in b.services.commandes(),
           "la borne délivre encore 7 kW : la pause est renvoyée, parce que "
           "c'est la mesure qui tranche et non notre souvenir")

    b.services.vider()
    b.horloge.avance(10)
    b.applique(0)
    t.egal(b.services.commandes(), [],
           "mais pas plus d'une fois par %d s" % E.PAUSE_MIN_INTERVAL)

    # ------------------------------- le chronomètre du réveil est désarmé
    # Le laisser courir aurait déclenché une tentative dès la reprise, sur une
    # attente accumulée alors que la borne était à l'arrêt.
    b = Banc(statut="ready_to_charge", puissance=0)
    b.cycles(12, 12)                                 # le chronomètre s'arme
    t.vrai(b.d.offre_depuis > 0, "le chronomètre du réveil est armé")
    b.applique(0)
    t.egal(b.d.offre_depuis, 0.0,
           "l'arrêt le désarme : plus de courant offert, plus d'attente à "
           "compter")

    b.services.vider()
    b.horloge.avance(600)                            # une longue pause
    b.applique(12)
    t.egal(b.d.reveils, 0,
           "à la reprise, aucune tentative de réveil sur une attente accumulée "
           "pendant l'arrêt")

    # ------------------------------------------ la reprise rouvre la session
    b = Banc(statut="charging", puissance=7000)
    b.applique(10)
    b.applique(0)
    b.horloge.avance(60)
    b.services.vider()
    b.puissance(0)
    b.statut("ready_to_charge")
    b.applique(10)
    t.vrai("resume" in b.services.commandes(),
           "la reprise lève explicitement la pause")
    t.vrai(any(a.data.get("current") == 10 for a in b.services.limites()),
           "et repose la consigne de courant")

    # -------------------------------------------------- rendre la borne
    b = Banc(statut="disconnected", puissance=0, calibre=25)
    b.services.vider()
    import asyncio
    asyncio.run(b.d.release())
    t.egal(b.services.courants(), [25],
           "en se retirant, le pilote rend le calibre plein du circuit")
    t.vrai(any(a.service == "set_charger_phase_mode"
               and a.data.get("phase_mode") == "auto_phase"
               for a in b.services.appels),
           "et rend le mode automatique, véhicule débranché")
    t.vrai("resume" in b.services.commandes(),
           "et lève la pause qu'il avait posée")

    b = Banc(statut="charging", puissance=7000)
    b.services.vider()
    asyncio.run(b.d.release())
    t.vrai(not any(a.service == "set_charger_phase_mode"
                   for a in b.services.appels),
           "véhicule branché : le mode de phases n'est pas touché, il "
           "interromprait la charge en cours")
