# -*- coding: utf-8 -*-
"""La consigne de courant : sa durée de vie, et la discipline d'écriture.

C'est ici qu'est passée la panne la plus coûteuse du projet. Le fichier
affirmait que `time_to_live` devait valoir 0 ; avec 0 la consigne ne prend pas,
l'appel Home Assistant réussit quand même, et la borne garde la limite
précédente. Pilote croyait piloter le courant sans jamais y toucher, pendant
des semaines, sans qu'aucun journal ne s'en plaigne.

Deux exigences opposées se rejoignent ici :
  — écrire ASSEZ pour que la consigne n'expire jamais en pleine charge ;
  — écrire le MOINS possible, parce que chaque écriture fait sauter le signal
    pilote et que certaines voitures (une DS3, en l'occurrence) se mettent en
    défaut au bout de quelques sauts rapprochés.
"""

from faux import Banc


def executer(t):
    b = Banc()
    E = b.easee

    # ------------------------------------------------ la durée de vie
    t.vrai(E.TTL_LIMITE > 0,
           "time_to_live est NON NUL (%s min) — avec 0 la consigne n'est "
           "jamais appliquée et la borne garde la précédente" % E.TTL_LIMITE)
    t.vrai(E.RENOUVELLEMENT < E.TTL_LIMITE * 60,
           "le renouvellement (%d s) tombe avant l'échéance (%d s)"
           % (E.RENOUVELLEMENT, E.TTL_LIMITE * 60))
    t.vrai(E.RENOUVELLEMENT * 3 <= E.TTL_LIMITE * 60,
           "la marge est d'au moins trois renouvellements : une écriture "
           "perdue ne laisse pas la limite retomber")

    # ------------------------------- une consigne qui change : UNE écriture
    # Le passage par une valeur voisine ne sert qu'à forcer la borne à
    # ré-émettre une consigne INCHANGÉE. Quand la valeur change, le changement
    # suffit — et la valeur intermédiaire ajoute une seconde rupture du signal
    # pilote deux secondes après la première.
    b = Banc(statut="charging", puissance=7000)
    b.applique(10)
    ecritures = b.services.limites()
    t.egal(len(ecritures), 1,
           "une consigne qui change produit UNE écriture, pas deux")
    t.egal(ecritures[0].data.get("current"), 10, "c'est la valeur demandée")
    t.egal(ecritures[0].data.get("time_to_live"), E.TTL_LIMITE,
           "l'écriture porte l'échéance")

    b.services.vider()
    b.horloge.avance(30)
    b.applique(11)
    t.egal([a.data.get("current") for a in b.services.limites()], [11],
           "une modulation 10 A → 11 A reste une écriture unique")

    # --------------------------- une consigne stable : le moins possible
    # « Par conception elles sont rares : une consigne stable ne doit rien
    #   produire ici. » — en-tête de _svc, dans le pilote.
    b = Banc(statut="charging", puissance=7000)
    b.applique(10)
    b.services.vider()
    b.cycles(29, 10)                       # 290 s, sous le renouvellement
    n = len(b.services.limites())
    t.egal(n, 0,
           "consigne stable, charge en cours : aucune écriture pendant "
           "290 s (le renouvellement est à %d s)" % E.RENOUVELLEMENT)
    if n:
        t.note("écritures observées : %d en 29 cycles — soit une toutes les "
               "%.0f s au lieu d'une toutes les %d s."
               % (n, 290.0 / n, E.RENOUVELLEMENT))

    # --------------------------------- mais la consigne ne doit pas expirer
    b = Banc(statut="charging", puissance=7000)
    b.applique(10)
    b.services.vider()
    duree = E.TTL_LIMITE * 60
    b.cycles(int(duree / 10) + 1, 10)      # une échéance complète
    ecrit = b.services.limites()
    t.vrai(len(ecrit) >= 1,
           "sur une échéance entière (%d s) la consigne est réécrite au moins "
           "une fois — sinon elle expire en pleine charge" % duree)
    t.vrai(all(a.data.get("current") == 10 for a in ecrit),
           "toutes les réécritures reposent la même valeur")

    # ----------------------------- toute écriture porte une échéance non nulle
    b = Banc(statut="ready_to_charge", puissance=0)
    b.cycles(60, 12)                       # 600 s sans que rien ne circule
    toutes = b.services.limites()
    t.vrai(toutes, "des écritures ont bien eu lieu (%d)" % len(toutes))
    sans = [a for a in toutes if not a.data.get("time_to_live")]
    t.vrai(not sans,
           "aucune écriture sans échéance sur %d — c'est la panne de v1.22"
           % len(toutes))

    # ------------------------------------- la relance quand rien ne circule
    # La mémoire de la limite dit ce que NOUS avons demandé, pas ce que la
    # borne applique. Une limite restée à zéro se voit exactement comme une
    # voiture qui refuse.
    b = Banc(statut="ready_to_charge", puissance=0)
    b.applique(12)
    b.services.vider()
    b.cycles(int(E.RELANCE_LIMITE / 10) + 2, 12)
    relances = b.services.limites()
    t.vrai(relances,
           "rien ne circule : la consigne est réécrite plutôt que supposée")
    t.vrai(any(a.data.get("current") != 12 for a in relances),
           "la relance passe par une valeur voisine, pour forcer la borne à "
           "ré-émettre une consigne qu'elle croit déjà posée")

    # ----------------------------------------- le calibre du circuit prime
    b = Banc(statut="charging", puissance=7000, calibre=16)
    b.applique(32)
    t.egal(b.services.courants(), [16],
           "une consigne de 32 A est ramenée au calibre du circuit (16 A)")

    b = Banc(statut="charging", puissance=7000, calibre=25)
    b.applique(16)
    t.egal(b.services.courants(), [16],
           "une consigne sous le calibre passe intacte")
