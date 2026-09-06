# -*- coding: utf-8 -*-
"""Ce qui part réellement chez les utilisateurs.

HACS ne lit pas le dépôt : il lit l'étiquette et le `version` du manifeste.
Les deux doivent dire la même chose, sinon Home Assistant propose une mise à
jour qui ne s'installe jamais, ou en installe une autre que celle qu'on a
testée. Et un fichier modifié mais non validé ne se retrouve dans AUCUNE
version publiée — on l'a testé chez soi, personne d'autre ne l'aura.
"""

import os
import re
import subprocess

from faux import RACINE, manifeste


def _git(*args):
    try:
        r = subprocess.run(("git", "-C", RACINE) + args,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _rang(v):
    return tuple(int(x) for x in v.split("."))


def executer(t):
    m = manifeste()
    version = m.get("version", "")

    t.vrai(re.fullmatch(r"\d+\.\d+\.\d+", version),
           "le manifeste porte une version en trois nombres (%s)" % version)
    for champ in ("domain", "name", "documentation", "issue_tracker",
                  "codeowners", "config_flow", "version"):
        t.vrai(champ in m, "le manifeste déclare « %s »" % champ)
    t.egal(m.get("domain"), "ha_pilote_com",
           "le domaine est celui du dossier du paquet")

    dossier = os.path.basename(
        os.path.dirname(os.path.join(RACINE, "custom_components",
                                     "ha_pilote_com", "manifest.json")))
    t.egal(dossier, m.get("domain"),
           "le dossier du paquet porte le nom du domaine")

    if _git("rev-parse", "--git-dir") is None:
        t.saute("cohérence avec les étiquettes git : pas de dépôt git ici. "
                "C'est le contrôle qui empêche de publier une version dont "
                "l'étiquette et le manifeste divergent.")
        return

    # --- l'arbre de travail doit être propre --------------------------
    if os.environ.get("PILOTE_MUTATION"):
        t.saute("état de l'arbre de travail : mutation en cours, il est sale "
                "par construction")
        return

    sale = _git("status", "--porcelain")
    noms = [l.split(None, 1)[1].strip().strip('"')
            for l in (sale or "").splitlines() if l.split(None, 1)[1:]]
    noms = [n for n in noms if not n.startswith("tests/")]
    t.vrai(not noms,
           "aucune modification non validée dans le paquet%s — une version "
           "publiée ne contient QUE ce qui est validé"
           % ("" if not noms else " (" + ", ".join(noms[:3]) + ")"))

    # --- la version doit être la plus haute ---------------------------
    etiquettes = [e[1:] for e in (_git("tag") or "").splitlines()
                  if re.fullmatch(r"v\d+\.\d+\.\d+", e)]
    if not etiquettes:
        t.saute("comparaison des versions : aucune étiquette dans le dépôt")
        return

    plus_haute = max(etiquettes, key=_rang)
    t.vrai(_rang(version) >= _rang(plus_haute),
           "la version du manifeste (%s) n'est pas inférieure à la dernière "
           "étiquette (%s)" % (version, plus_haute))

    # --- HEAD étiqueté : les deux doivent coïncider -------------------
    sur_head = [e for e in (_git("tag", "--points-at", "HEAD") or "").splitlines()
                if re.fullmatch(r"v\d+\.\d+\.\d+", e)]
    if sur_head:
        t.vrai("v" + version in sur_head,
               "l'étiquette posée sur HEAD (%s) correspond au manifeste (v%s)"
               % (", ".join(sur_head), version))
    else:
        # Ce n'est pas une faute : on travaille entre deux versions. Mais si
        # la version du manifeste réutilise une étiquette déjà publiée, la
        # prochaine publication écrasera une version que des gens ont déjà.
        t.vrai(version not in etiquettes,
               "la version du manifeste (%s) n'est pas une étiquette déjà "
               "publiée — sinon la prochaine publication écraserait une "
               "version installée chez des utilisateurs" % version)
        t.note("HEAD n'est pas étiqueté : version %s en préparation, "
               "dernière publiée %s." % (version, plus_haute))
