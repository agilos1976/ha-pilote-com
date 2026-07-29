# HA Pilote Com

Intégration [Home Assistant](https://www.home-assistant.io/) pour envoyer automatiquement vos courbes de charge (production et consommation) vers [Romande Dynamics](http://carrard.ch/RomandeDynamics/).

## Fonctionnalités

- Sélection des entités de production et consommation via l'interface Home Assistant
- Envoi automatique des données à intervalle configurable (1 à 24 heures)
- Configuration entièrement via l'UI (pas de YAML)
- Reconfiguration possible sans supprimer l'intégration

## Installation via HACS

1. Ouvrir HACS dans Home Assistant
2. Cliquer sur le menu **⋮** (trois points) en haut à droite
3. Sélectionner **Dépôts personnalisés**
4. Coller l'URL : `https://github.com/marccarrard/ha-pilote-com`
5. Catégorie : **Intégration**
6. Cliquer **Ajouter**, puis installer **HA Pilote Com**
7. Redémarrer Home Assistant

## Installation manuelle

Copier le dossier `custom_components/ha_pilote_com/` dans le dossier `custom_components/` de votre installation Home Assistant, puis redémarrer.

## Configuration

1. Aller dans **Paramètres** > **Appareils et services**
2. Cliquer **Ajouter une intégration**
3. Chercher **HA Pilote Com**
4. Renseigner :
   - **Entité de production** : le capteur de votre courbe de charge de production (ex: puissance PV)
   - **Entité de consommation** : le capteur de votre courbe de charge de consommation
   - **Intervalle de mise à jour** : fréquence d'envoi en heures
   - **Clé API** : votre clé API Romande Dynamics
5. Cliquer **Enregistrer**

## Obtenir une clé API

Contactez Romande Dynamics pour obtenir votre clé API personnelle.

## Licence

MIT
