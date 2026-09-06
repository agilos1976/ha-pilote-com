# Vérifications avant publication du plugin

```bash
python3 tests/run.py
```

Code de sortie **0** si tout passe, **1** sinon. Aucune dépendance : ni Home
Assistant, ni pytest, ni rien à installer. **Python 3.12 minimum** — le plugin
emploie la syntaxe `type X = …` et tourne sur le Python 3.13 de Home Assistant ;
le vérifier sous un interpréteur plus ancien ne prouverait rien.

À lancer avant chaque étiquette et chaque publication GitHub. Une version
publiée part chez tous les utilisateurs par HACS, et rien ne la rattrape.

## Ce n'est pas un port

Le pilote Easee n'importe qu'**une seule chose** de Home Assistant : le
registre des entités. `faux.py` le remplace, et tout le reste — la résolution
des entités, l'échelle de réveil, la discipline d'écriture — s'exécute **tel
qu'il tourne chez l'utilisateur**. Il n'y a pas de transcription, donc rien qui
puisse diverger d'une version à l'autre.

Le temps est faux lui aussi : un `await asyncio.sleep(6)` avance l'horloge de
six secondes sans que personne n'attende. Une heure de charge se déroule en
quelques millisecondes, et les temporisations sont vérifiées à la seconde.

## Ce qui est vérifié

| Série | Ce qu'elle attrape |
|---|---|
| **Syntaxe** | Un fichier qui ne compile pas, un JSON malformé, une clé de traduction manquante. L'intégration n'apparaîtrait simplement pas au démarrage. |
| **Version** | Étiquette et manifeste qui divergent, version en recul, fichier modifié mais non validé — donc absent de la version publiée. |
| **Lecture** | Conversion kW → W, calibre du circuit, résolution des entités par `unique_id` plutôt que par nom, charge en cours quand le capteur de puissance manque. |
| **Consigne de courant** | `time_to_live` non nul, renouvellement avant échéance, une seule écriture par changement, aucune écriture inutile. |
| **Phases** | Coupure avant la bascule, réouverture après, consigne réécrite plutôt que supposée. |
| **Programmation** | Le bouton « ignorer la programmation » pressé, sans le marteler ; l'échelle de réveil laissée hors du coup. |
| **Réveil** | Les trois barreaux dans l'ordre, jamais laissée à 0 A même interrompue, jamais déclenchée sur une charge saine. |
| **Arrêt** | Pause plutôt que fermeture de session, insistance si la borne débite quand même, borne rendue proprement. |

## Vérifier que la suite mord encore

```bash
python3 tests/mutation.py
```

Réintroduit sept défauts connus un par un, confirme que la suite les rejette,
restaure et compare octet à octet. Une suite verte qui ne sait plus échouer est
pire qu'une absence de tests.

Cinq de ces défauts ont été livrés en production. Deux ont été trouvés par
cette suite en l'écrivant :

- la consigne réécrite à **chaque cycle** pendant toute la charge, au lieu
  d'une fois toutes les cinq minutes ;
- l'échelle de réveil qui se déroulait jusqu'à **désactiver la borne** sur une
  borne qui attendait simplement l'heure de sa programmation.

## Ce qui n'est pas couvert

- `__init__.py`, `config_flow.py`, `switch.py` : seule leur syntaxe est
  vérifiée. Les exercer demanderait la moitié de Home Assistant en carton —
  config entries, recorder, gestion du temps — pour un rapport douteux.
- Le pilote **générique** (`drivers/generic.py`).
- Les échanges réels avec le serveur et avec l'API Easee : ici, les services
  sont enregistrés, pas appelés.

## Publier une version

Dans l'ordre, et pas autrement :

1. `python3 tests/run.py` — vert, y compris « aucune modification non validée »
2. la version du manifeste montée d'un cran
3. commit, puis `git tag vX.Y.Z`
4. `git push && git push --tags`
5. la publication GitHub, qui est ce que HACS propose aux utilisateurs
