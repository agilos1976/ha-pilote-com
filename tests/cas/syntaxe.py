# -*- coding: utf-8 -*-
"""Ce qui empêche le plugin de se charger du tout.

Home Assistant importe l'intégration au démarrage. Une erreur de syntaxe, un
JSON malformé, et l'intégration n'apparaît simplement pas — sans message utile
pour l'utilisateur, qui voit ses entités disparaître et son pilotage s'arrêter.
Ce sont les seules vérifications qui coûtent une seconde et sauvent une version.
"""

import ast
import json
import os

from faux import RACINE

PAQUET = os.path.join(RACINE, "custom_components", "ha_pilote_com")


def executer(t):
    sources = []
    for dossier, _, fichiers in os.walk(PAQUET):
        if "__pycache__" in dossier:
            continue
        for f in sorted(fichiers):
            if f.endswith(".py"):
                sources.append(os.path.join(dossier, f))

    t.vrai(len(sources) >= 5,
           "les fichiers du paquet sont trouvés (%d)" % len(sources))

    # `compile()` plutôt que py_compile : ce dernier veut écrire un .pyc, et
    # sous Windows os.devnull vaut « nul », que Python refuse comme cible.
    for chemin in sources:
        court = os.path.relpath(chemin, RACINE).replace("\\", "/")
        try:
            with open(chemin, encoding="utf-8") as f:
                compile(f.read(), chemin, "exec")
            t.ok("%s compile" % court)
        except SyntaxError as e:
            t.echec("%s ne compile pas — ligne %s : %s"
                    % (court, e.lineno, e.msg))

    # --- les fichiers de description ----------------------------------
    for nom, chemin in (("manifest.json", os.path.join(PAQUET, "manifest.json")),
                        ("hacs.json", os.path.join(RACINE, "hacs.json")),
                        ("strings.json", os.path.join(PAQUET, "strings.json"))):
        try:
            with open(chemin, encoding="utf-8") as f:
                json.load(f)
            t.ok("%s est un JSON valide" % nom)
        except Exception as e:
            t.echec("%s : %s" % (nom, e))

    # --- les traductions doivent couvrir les mêmes clés ---------------
    trad = os.path.join(PAQUET, "translations")
    fichiers = sorted(f for f in os.listdir(trad) if f.endswith(".json"))

    def cles(o, prefixe=""):
        s = set()
        if isinstance(o, dict):
            for k, v in o.items():
                s.add(prefixe + k)
                s |= cles(v, prefixe + k + ".")
        return s

    charges = {}
    for f in fichiers:
        with open(os.path.join(trad, f), encoding="utf-8") as fh:
            charges[f] = cles(json.load(fh))
    if len(charges) >= 2:
        reference = max(charges.values(), key=len)
        for f, k in charges.items():
            manque = reference - k
            # Une clé absente d'une traduction s'affiche en brut à l'écran,
            # du genre « component.ha_pilote_com.config.step.user.data.hote ».
            t.vrai(not manque,
                   "%s : aucune clé manquante%s"
                   % (f, "" if not manque
                      else " (" + ", ".join(sorted(manque)[:4]) + "…)"))
    else:
        t.saute("comparaison des traductions : moins de deux fichiers")

    # --- pas d'import oublié dans le pilote ---------------------------
    # Un `import` retiré par mégarde ne se voit qu'à l'exécution, sur le
    # chemin de code qui l'utilisait — souvent l'échelle de réveil, qui ne
    # sert qu'une fois par mois.
    for chemin in sources:
        court = os.path.relpath(chemin, RACINE).replace("\\", "/")
        with open(chemin, encoding="utf-8") as f:
            arbre = ast.parse(f.read(), chemin)
        importes = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Import):
                for a in n.names:
                    importes.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    importes.add(a.asname or a.name)
        utilises = set(n.id for n in ast.walk(arbre) if isinstance(n, ast.Name))
        utilises |= set(n.value.id for n in ast.walk(arbre)
                        if isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name))
        # `annotations` vient de __future__, il ne s'utilise pas par son nom.
        inutiles = importes - utilises - {"annotations"}
        if inutiles:
            t.note("%s : import sans usage apparent — %s"
                   % (court, ", ".join(sorted(inutiles))))
    t.ok("les imports du paquet sont analysés")
