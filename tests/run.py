# -*- coding: utf-8 -*-
"""Vérifications avant publication d'une version du plugin.

    python tests/run.py

Code de sortie 0 si tout passe, 1 sinon. Aucune dépendance : Python seul, ni
Home Assistant ni pytest. À lancer avant chaque étiquette et chaque publication
GitHub — une version publiée part chez tous les utilisateurs par HACS, et rien
ne la rattrape.
"""

import io
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Sortie en UTF-8 : la console Windows est en cp1252 et avale les accents.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)


class Journal:
    def __init__(self):
        self.reussis = 0
        self.echoues = 0
        self.sautes = 0

    def ok(self, quoi):
        self.reussis += 1
        print("  OK   %s" % quoi)

    def echec(self, quoi):
        self.echoues += 1
        print("  ECHEC %s" % quoi)

    def saute(self, quoi):
        self.sautes += 1
        print("  SAUTE %s" % quoi)

    def vrai(self, cond, quoi):
        self.ok(quoi) if cond else self.echec(quoi)

    def egal(self, obtenu, attendu, quoi):
        if obtenu == attendu:
            self.ok(quoi)
        else:
            self.echec("%s\n         attendu : %r\n         obtenu  : %r"
                       % (quoi, attendu, obtenu))

    def note(self, texte):
        print("    %s" % texte)


SERIES = [
    ("syntaxe",   "Syntaxe et cohérence du paquet"),
    ("version",   "Version — ce qui part chez les utilisateurs"),
    ("lecture",   "Ce que le pilote lit sur la borne"),
    ("limite",    "Discipline d'écriture de la consigne de courant"),
    ("phases",    "Bascule mono / triphasé"),
    ("programme", "Borne en attente de sa programmation"),
    ("reveil",    "Véhicule en veille profonde"),
    ("arret",     "Arrêt de la charge"),
]


MINIMUM = (3, 12)


def main():
    print("\nPilote — plugin Home Assistant : vérifications avant publication\n")

    # Home Assistant tourne sur Python 3.13, et le plugin emploie la syntaxe
    # `type X = ...` apparue en 3.12. Vérifier sous un interpréteur plus ancien
    # ferait échouer des fichiers parfaitement valides, et surtout : ce ne
    # serait pas l'interpréteur qui les exécutera chez l'utilisateur.
    if sys.version_info < MINIMUM:
        print("  Cet interpréteur est en Python %d.%d, il en faut au moins "
              "%d.%d.\n" % (sys.version_info[0], sys.version_info[1], *MINIMUM))
        print("  Le plugin tourne sur le Python de Home Assistant (3.13).")
        print("  Ici, « python3 » convient :\n")
        print("      python3 tests/run.py\n")
        return 1

    t = Journal()
    for nom, titre in SERIES:
        print(titre)
        try:
            mod = __import__("cas.%s" % nom, fromlist=["executer"])
            mod.executer(t)
        except Exception:
            t.echec("la série « %s » s'est interrompue" % nom)
            for l in traceback.format_exc().strip().splitlines():
                print("         %s" % l)
        print("")

    print("-" * 64)
    print("  %d réussis, %d échoués, %d sautés"
          % (t.reussis, t.echoues, t.sautes))
    if t.sautes:
        print("\n  Un test sauté ne vérifie rien. Voir ci-dessus la raison.")
    print("")
    return 1 if t.echoues else 0


if __name__ == "__main__":
    sys.exit(main())
