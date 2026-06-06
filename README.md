# Synology HyperBackup for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/pierrec18/ha_hyperbackup.svg)](https://github.com/pierrec18/ha_hyperbackup/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Intégration Home Assistant pour monitorer vos tâches **Synology Hyper Backup** directement depuis votre NAS, sans passer par le cloud Synology.

![Synology HyperBackup](icon.png)

---

## Fonctionnalités

- **Connexion directe DSM** — communication locale avec l'API Synology DSM (pas de cloud)
- **Détection automatique** des tâches Hyper Backup configurées sur le NAS
- **3 capteurs par tâche** :
  - `last_backup` — timestamp du dernier backup réussi (Device Class: `timestamp`)
  - `result` — résultat : `Réussi` / `En cours` / `Erreur` / `Jamais exécuté`
  - `progress` — progression en % si un backup est actuellement en cours
- **Mise à jour toutes les 15 minutes**
- **Support 2FA** (OTP Synology Secure SignIn)
- **Config Flow** — configuration graphique via l'interface HA

---

## Installation via HACS

1. Dans HACS → **Intégrations** → menu ⋮ → **Dépôts personnalisés**
2. Ajouter l'URL `https://github.com/pierrec18/ha_hyperbackup` · Catégorie : **Intégration**
3. Rechercher **Synology HyperBackup** et cliquer **Télécharger**
4. Redémarrer Home Assistant

## Installation manuelle

Copier le dossier `custom_components/hyperbackup/` dans votre répertoire `config/custom_components/`, puis redémarrer Home Assistant.

---

## Configuration

1. Aller dans **Paramètres → Appareils et services → Ajouter une intégration**
2. Rechercher **Synology HyperBackup**
3. Renseigner :
   - Adresse IP / hostname du NAS
   - Port DSM (défaut : `5001` en HTTPS, `5000` en HTTP)
   - Nom d'utilisateur et mot de passe DSM
   - SSL activé (recommandé) / vérification du certificat

> **Note 2FA** : si votre compte DSM utilise la vérification en deux étapes, l'intégration vous demandera un code OTP lors de la première connexion.

---

## Entités créées

Pour chaque tâche Hyper Backup détectée, trois entités sont créées :

| Entité | Type | Description |
|--------|------|-------------|
| `sensor.hyperbackup_<nom>_dernier_backup` | `timestamp` | Date/heure du dernier backup réussi |
| `sensor.hyperbackup_<nom>_resultat` | `string` | Résultat de la dernière exécution |
| `sensor.hyperbackup_<nom>_progression` | `%` | Progression si backup en cours, sinon indisponible |

Les entités d'une même tâche sont regroupées sous un **appareil** nommé `HyperBackup — <nom de la tâche>`.

---

## Exemple de carte dashboard

```yaml
type: custom:mushroom-template-card
primary: "{{ state_attr('sensor.hyperbackup_google_drive_resultat', 'task_name') }}"
secondary: >
  {{ states('sensor.hyperbackup_google_drive_resultat') }} ·
  {{ states('sensor.hyperbackup_google_drive_dernier_backup') | as_timestamp | timestamp_custom('%d/%m à %H:%M') }}
icon: mdi:nas
icon_color: >
  {{ 'green' if states('sensor.hyperbackup_google_drive_resultat') == 'Réussi' else 'red' }}
layout: horizontal
fill_container: true
```

---

## Prérequis

- Home Assistant **2024.1.0** ou supérieur
- Synology DSM **7.x** avec Hyper Backup installé
- Un compte DSM avec accès à l'API Hyper Backup

---

## Licence

MIT — voir [LICENSE](LICENSE)
