# -*- coding: utf-8 -*-
"""Vérifie que la suite SAIT échouer.

On réintroduit un défaut connu, on lance les tests, on attend un échec, puis on
restaure et on compare octet à octet. Une suite qui passe quoi qu'on lui fasse
est une décoration — et rassure d'autant plus qu'elle ne vérifie rien.

Les six défauts ci-dessous sont réels : quatre ont été livrés en production,
deux ont été trouvés par cette suite elle-même en l'écrivant.

    python3 tests/mutation.py
"""

import io
import os
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOTES = {
    "easee": os.path.join(RACINE, "custom_components", "ha_pilote_com",
                          "drivers", "easee.py"),
    "tesla": os.path.join(RACINE, "custom_components", "ha_pilote_com",
                          "drivers", "tesla.py"),
}

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

MUTATIONS = [
    ("tesla", "l'arrêt passe par l'ampérage au lieu de couper la charge",
     "        if self._allume() is not False:\n            await self._commuter(False)",
     "        await self._ecrire_amperes(5)"),

    ("tesla", "la trappe de recharge est prise pour l'interrupteur de charge",
     "                if any(k in s for k in CLES_INTERRUPTEUR) \\\n"
     "                        and not any(x in s for x in CLES_ECARTEES):",
     "                if any(k in s for k in CLES_INTERRUPTEUR):"),

    ("easee", "time_to_live revient à zéro — la consigne n'est jamais appliquée",
     "TTL_LIMITE = 15", "TTL_LIMITE = 0"),

    ("easee", "la consigne n'est plus renouvelée avant son échéance",
     "RENOUVELLEMENT = 300", "RENOUVELLEMENT = 1200"),

    ("easee", "la modulation repasse par une valeur voisine — le défaut de la DS3",
     "await self._limite(amperes, reemettre=False)\n                self.amps = amperes\n            elif",
     "await self._limite(amperes, reemettre=True)\n                self.amps = amperes\n            elif"),

    ("easee", "le barreau 2 suppose la consigne intacte au lieu de la réécrire",
     "            finally:\n                self.amps = None",
     "            finally:\n                self.amps = amperes"),

    ("easee", "la charge en cours ne se lit plus que sur la mesure",
     '        return s == "charging"', "        return False"),

    # --- les deux défauts que cette suite a trouvés ---------------------
    ("easee", "la consigne est réécrite à chaque cycle pendant toute la charge",
     "                self.reveil_dit = False\n                # NE PAS remettre",
     "                self.reveil_dit = False\n                self.derniere_limite = 0.0\n                # NE PAS remettre"),

    ("easee", "l'échelle de réveil se déroule sur une borne qui attend son programme",
     "                    self.offre_depuis = 0.0\n                    if await self._ignorer_programme():",
     "                    if await self._ignorer_programme():"),
]


def lancer():
    # Le contrôle « rien de non validé » est une règle de PUBLICATION, pas de
    # code : pendant une mutation l'arbre est forcément sale, et le laisser
    # échouer rendrait toutes les mutations « détectées » sans rien prouver.
    env = dict(os.environ, PILOTE_MUTATION="1")
    r = subprocess.run([sys.executable, os.path.join("tests", "run.py")],
                       cwd=RACINE, capture_output=True, env=env)
    return r.returncode


def main():
    origines = {}
    for nom, chemin in PILOTES.items():
        with open(chemin, "rb") as f:
            origines[nom] = f.read()

    print("\n  état de départ : %s\n"
          % ("la suite passe" if lancer() == 0 else "LA SUITE ÉCHOUE DÉJÀ"))

    manques = 0
    for pilote, quoi, avant, apres in MUTATIONS:
        origine = origines[pilote]
        source = origine.decode("utf-8")
        # Les fichiers sont en CRLF. Les fragments ci-dessus sont écrits en LF,
        # comme tout le monde les lit : on les adapte plutôt que de truffer la
        # liste de \r invisibles, où une faute ne se verrait jamais.
        saut = "\r\n" if b"\r\n" in origine else "\n"
        a, b = avant.replace("\n", saut), apres.replace("\n", saut)
        etiquette = "%-6s %s" % (pilote, quoi)
        if source.count(a) != 1:
            print("  ?   %s — fragment introuvable ou ambigu (%d fois)"
                  % (etiquette, source.count(a)))
            manques += 1
            continue
        with open(PILOTES[pilote], "w", encoding="utf-8", newline="") as f:
            f.write(source.replace(a, b))
        code = lancer()
        with open(PILOTES[pilote], "wb") as f:
            f.write(origine)
        if code != 0:
            print("  ✓   détecté : %s" % etiquette)
        else:
            print("  ✗   NON DÉTECTÉ : %s" % etiquette)
            manques += 1

    sales = []
    for nom, chemin in PILOTES.items():
        with open(chemin, "rb") as f:
            if f.read() != origines[nom]:
                sales.append(os.path.basename(chemin))
    print("\n  restauration : %s"
          % ("les pilotes sont identiques à l'original" if not sales
             else "!! NON RESTAURÉ : " + ", ".join(sales)))
    print("  %s\n" % ("la suite détecte les %d défauts" % len(MUTATIONS)
                      if not manques else "%d défaut(s) passent au travers"
                      % manques))
    return 1 if (manques or sales) else 0


if __name__ == "__main__":
    sys.exit(main())
