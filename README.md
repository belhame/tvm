# PowerCare · TVM Web

Application de gestion du SAV des onduleurs : **React / TypeScript**, API **Django**, base **PostgreSQL 16** commune à tous les utilisateurs. Les dossiers sont enregistrés sur le serveur ; chaque ordinateur se connecte à la même application. Aucun dossier métier n'est stocké dans le `localStorage` du navigateur.

Le premier parcours fonctionnel est **client → onduleur / numéro de série → demande SAV → intervention → rapport PDF**. L'interface reprend la direction visuelle PowerCare : fond clair, navigation blanche, bleu électrique, cartes, tableaux et graphiques alimentés par la base.

Le compteur de prise en charge utilise la date d’arrivée réelle et passe en retard après deux jours ouvrés, samedi et dimanche exclus. Il se fige à la clôture. Les fiches de réception, les pièces jointes privées ou explicitement partagées et les PDF reprennent les dossiers enregistrés.

Chaque dossier possède un **N° d'intervention / appel TVM** commun à ses visites et un **N° d'appel client** distinct, fourni par le centre SAV client. L'équipe peut rechercher les deux ; le portail client privilégie la référence de son centre, dans le périmètre de sa société. Les `INT-…` restent des références secondaires de visite. Voir [le guide des numéros et du suivi](docs/GUIDE_SUIVI_SAV.md#identifier-un-dossier-avec-les-deux-numéros).

Le suivi SAV ajoute des catégories de demandes avec compteurs, des fiches d'échange, de mise en service et de prévention, ainsi qu'une chronologie des événements enregistrés. [Le guide de suivi](docs/GUIDE_SUIVI_SAV.md) distingue cet historique web de l'ancien journal HFSQL, qui n'est pas repris automatiquement.

L'annuaire clients propose un import CSV avec prévisualisation, sans écraser les fiches ni reprendre d'anciens comptes. Les données réelles et le CSV privé restent séparés du ZIP public ; [la procédure d'import](docs/GUIDE_SUIVI_SAV.md#annuaire-clients-et-import-csv) explique comment les charger dans sa propre instance.

Pour la prévention, l'objectif de visites du dossier reste distinct du nombre calculé de fiches réellement terminées. Les visites conservent le même appel TVM et leurs références secondaires ; la mise en service dispose de sa fiche et de son PDF dédiés.

[Aperçu du tableau de bord](docs/screenshots/tableau-de-bord.png) · [Détail d'une intervention](docs/screenshots/intervention.png) · [Affichage mobile](docs/screenshots/mobile.png).

## Essayer la version de démonstration

### Sur un PC Windows

Installer et ouvrir **Docker Desktop**, puis décompresser le projet et double-cliquer sur **`INSTALLER_TVM.cmd`**. Le lanceur prépare la base et la démonstration, attend le serveur, puis ouvre le navigateur et les accès locaux. Python et Node.js sont exécutés dans Docker ; leur installation sur Windows n'est pas nécessaire.

Les fois suivantes, utiliser **`DEMARRER_TVM.cmd`**. **`ARRETER_TVM.cmd`** arrête les services en conservant les données. Voir le [guide Windows pas à pas](docs/INSTALLATION_WINDOWS.md).

En cas de refus de mot de passe PostgreSQL malgré la récupération de l’ancienne configuration, le [réparateur de connexion Windows](docs/INSTALLATION_WINDOWS.md#si-le-refus-persiste--réparer-la-connexion-existante) fournit une procédure avec sauvegarde préalable, sans réinitialiser la base ni les comptes TVM.

### Sur Linux / macOS, ou pour développer hors conteneur

Prérequis : Bash, **Python 3.12**, **Node.js 24**, npm, Docker et Docker Compose v2. Le serveur Docker doit être démarré. Sous Windows, ce mode de développement peut aussi s'utiliser dans WSL2.

Depuis la racine du projet :

```bash
bash scripts/setup.sh --demo
bash scripts/start.sh
```

Ouvrir sur la machine exécutant le serveur l'adresse locale indiquée par Gunicorn, port **8000**. Le serveur écoute par défaut uniquement sur cette machine. Pour un accès depuis plusieurs ordinateurs, suivre [le déploiement sur un serveur partagé](docs/DEPLOIEMENT.md).

Les comptes fictifs sont `admin`, `responsable`, `technicien` et `client`. Leur mot de passe est **généré localement**, disponible dans `.local/demo-access.txt`, jamais codé en dur. Le compte `client` sert à tester le portail limité à sa société. Le mode démonstration est signalé dans l'application.

`setup.sh --demo` initialise `.env`, installe les dépendances, démarre PostgreSQL, compile le frontend, applique les migrations et ajoute les données fictives. Un `.env` existant est conservé. Si ce fichier désactive la démo, le script n'y active pas silencieusement les comptes fictifs.

## Documents et commandes

| Besoin | Document ou commande |
|---|---|
| Installer, démarrer, développer | [Installation](docs/INSTALLATION.md) |
| Comprendre ce qui fonctionne et ce qui reste à connecter | [Fonctionnalités et limites](docs/FONCTIONNALITES.md) |
| Mettre en service pour 5–15 personnes | [Déploiement, comptes et sauvegardes](docs/DEPLOIEMENT.md) |
| Examiner les 25 tables et les limites de récupération WINDEV | [Analyse du projet fourni](docs/ANALYSE_WINDEV.md) |
| Demander l'export au développeur HFSQL | [Spécification d'export](docs/EXPORT_HFSQL.md) |
| Comprendre l'aide de lecture des séries Eaton | [Structure des numéros de série Eaton](docs/NUMEROS_SERIE_EATON.md) |
| Importer le catalogue Eaton BN dans sa propre instance TVM | [Import du catalogue Eaton](docs/IMPORT_CATALOGUE_EATON.md) |
| Retrouver modèle et garantie depuis la série pendant une nouvelle demande | [Parcours de demande SAV par numéro de série](docs/PARCOURS_DEMANDE_SERIE.md) |
| Suivre les dossiers, opérations et événements enregistrés | [Guide du suivi SAV et de l'historique](docs/GUIDE_SUIVI_SAV.md) |
| Voir deux fiches PDF entièrement fictives | [Exemples de fiches](docs/exemples/README.md) |
| Contrat HTTP des ressources | [API](docs/API_CONTRACT.md) |
| Résultats des tests et limites vérifiées | [Validation](docs/VALIDATION.md) |
| Exécuter les contrôles backend et la compilation frontend | `bash scripts/test.sh` |
| Tester le parcours dans Chromium sur une base distincte | `bash scripts/e2e.sh` |
| Sauvegarder PostgreSQL, les pièces jointes et la configuration | `bash scripts/backup.sh` |

## Installation sans données fictives

```bash
bash scripts/setup.sh
set -a
source .env
set +a
.venv/bin/python backend/manage.py createsuperuser --username admin
bash scripts/start.sh
```

Le superutilisateur créé a les droits administrateur effectifs. Depuis l'application, créer ensuite les comptes de responsable SAV, technicien et client ; associer chaque compte client à la bonne société. Ne pas exposer les comptes de démonstration à des utilisateurs réels.

## Sources

```text
backend/       Django, modèles, API, droits, PDF, migrations et tests
frontend/      React, TypeScript, interface responsive et scanner
scripts/       Installation, démarrage, tests et sauvegarde
docs/          Analyse WINDEV, contrat d'export et instructions
compose.yaml   PostgreSQL persistant et service web conteneurisé optionnel
Dockerfile     Compilation frontend puis serveur web Python
```

L'archive WINDEV et les exports de données restent hors des sources versionnées. Le schéma récupéré n'est pas une traduction des traitements binaires WLangage. La reprise HFSQL commence par une validation et un stockage de préparation ; elle ne met pas automatiquement en production des relations ou règles métier non confirmées.
