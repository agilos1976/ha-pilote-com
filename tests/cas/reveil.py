# -*- coding: utf-8 -*-
"""Le véhicule en veille profonde.

Une voiture laissée branchée sans charger finit par endormir son calculateur de
charge. Elle ne surveille alors plus le signal pilote, et rouvrir la session ne
sert à rien : répéter « start » ne produit aucune transition, et c'est la
transition qui réveille.

Trois barreaux, du plus doux au plus brutal. Chacun coûte plus cher que le
précédent à la voiture, donc on ne monte qu'en cas d'échec — et le dernier
coupe la borne, ce qui doit rester rare et réversible.
"""

from faux import Banc, Inscription


def executer(t):
    E = Banc().easee

    # -------------------------------------- l'échelle ne s'arme pas trop tôt
    b = Banc(statut="ready_to_charge", puissance=0)
    b.cycles(int(E.REVEIL_APRES / 10) - 3, 12)      # 120 s < 150 s
    t.egal(b.d.reveils, 0,
           "aucune tentative avant %d s de courant offert sans effet"
           % E.REVEIL_APRES)

    b.cycles(6, 12)                                  # on franchit le seuil
    t.egal(b.d.reveils, 1, "le seuil franchi, une tentative est engagée")

    # ------------------------------------------------ barreau 1 : la session
    # On s'arrête AU cycle du barreau, pas après : le cycle suivant repose la
    # consigne et effacerait justement ce qu'on veut observer.
    b = Banc(statut="ready_to_charge", puissance=0)
    b.jusqu_a(lambda: b.d.reveils == 1, 12)
    cmds = b.services.commandes()
    t.vrai("pause" in cmds and "resume" in cmds and "start" in cmds,
           "barreau 1 : la session est refermée puis rouverte")
    t.egal(b.d.amps, None,
           "barreau 1 : la consigne n'est pas supposée intacte après une "
           "réouverture de session — elle sera réécrite au cycle suivant")

    b.services.vider()
    b.horloge.avance(10)
    b.applique(12)
    t.vrai(any(a.data.get("current") == 12 for a in b.services.limites()),
           "barreau 1 : le cycle suivant repose bien la consigne")

    # -------------------------------- barreau 2 : la modulation recréée
    b = Banc(statut="ready_to_charge", puissance=0)
    b.jusqu_a(lambda: b.d.reveils == 2, 12)
    t.egal(b.d.reveils, 2, "barreau 2 atteint après un second intervalle")
    courants = b.services.courants()
    t.vrai(0 in courants,
           "barreau 2 : la limite passe par zéro, ce qui fait disparaître la "
           "modulation elle-même")
    apres_zero = courants[courants.index(0) + 1:]
    t.vrai(apres_zero and all(c >= 6 for c in apres_zero),
           "barreau 2 : la limite est immédiatement relevée, jamais laissée "
           "à zéro")

    # --- et si tout s'arrête au pire moment ---------------------------
    # Entre la mise à zéro et sa restauration, une exception ou un
    # redémarrage laisserait la borne à 0 A. Elle afficherait alors
    # « ready_to_charge » en délivrant 0 kW — indiscernable d'une voiture qui
    # refuse — et rien ne l'en sortirait, puisque apply() ne réécrit la limite
    # que si elle diffère de sa mémoire.
    b = Banc(statut="ready_to_charge", puissance=0)
    b.jusqu_a(lambda: b.d.reveils == 1, 12)          # barreau 1 franchi
    b.horloge.exploser_a = 6                         # l'attente du barreau 2
    b.services.vider()
    leve = False
    try:
        b.jusqu_a(lambda: b.d.reveils == 2, 12)
    except RuntimeError:
        leve = True
    t.vrai(leve, "l'interruption a bien eu lieu au milieu du barreau 2")
    courants = b.services.courants()
    t.vrai(courants and courants[-1] >= 6,
           "interrompu en plein barreau 2, la borne n'est PAS laissée à 0 A "
           "(dernière écriture : %s A)" % (courants[-1] if courants else "aucune"))
    t.egal(b.d.amps, None,
           "et la mémoire est effacée, pour que le cycle suivant réécrive")

    # ------------------------------------ barreau 3 : couper puis remettre
    b = Banc(statut="ready_to_charge", puissance=0)
    b.jusqu_a(lambda: b.d.reveils == E.REVEIL_MAX, 12)
    t.egal(b.d.reveils, E.REVEIL_MAX,
           "l'échelle s'arrête à %d tentatives" % E.REVEIL_MAX)
    inter = [(a.service, a.data.get("entity_id")) for a in b.services.appels
             if a.domaine == "switch"]
    coupures = [s for s, e in inter if e == "switch.borne_chargeur_active"]
    t.vrai("turn_off" in coupures and "turn_on" in coupures,
           "barreau 3 : la borne est désactivée puis RÉACTIVÉE")
    t.vrai(coupures.index("turn_off") < coupures.index("turn_on"),
           "barreau 3 : jamais laissée désactivée")

    b.services.vider()
    b.cycles(60, 12)
    t.egal(b.d.reveils, E.REVEIL_MAX,
           "au-delà du maximum, plus aucune tentative — on n'insiste pas")

    # -------------------------- une charge saine ne déclenche jamais rien
    # Le piège de la v1.24 : le capteur de puissance est FACULTATIF, et absent
    # il rendait None — donc « rien ne circule » en permanence. L'échelle
    # montait alors jusqu'à couper la borne sur une voiture qui chargeait.
    sans_capteur = [
        Inscription("sensor.borne_statut", "AB123_status"),
        Inscription("switch.borne_chargeur_active", "AB123_isEnabled"),
    ]
    b = Banc(statut="charging", puissance=None, entites=sans_capteur)
    b.cycles(200, 12)                                # 2000 s de charge
    t.egal(b.d.reveils, 0,
           "sans capteur de puissance, une charge en cours ne déclenche "
           "aucune tentative de réveil")
    t.vrai(not [a for a in b.services.appels
                if a.domaine == "switch" and a.service == "turn_off"],
           "et la borne n'est jamais coupée sur une charge saine")

    # ------------------------------- un état illisible n'est pas un refus
    b = Banc(statut="unknown", puissance=None)
    b.cycles(200, 12)
    t.egal(b.d.reveils, 0,
           "état illisible : on ne réveille pas sur une ignorance")

    # ------------------------------------ un débranchement solde l'échelle
    b = Banc(statut="ready_to_charge", puissance=0)
    b.cycles(60, 12)
    t.vrai(b.d.reveils >= 1, "une tentative a eu lieu avant le débranchement")
    b.statut("disconnected")
    b.applique(12)
    t.egal(b.d.reveils, 0,
           "le véhicule suivant ne paie pas les tentatives du précédent")
