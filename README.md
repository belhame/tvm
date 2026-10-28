# PowerCare · TVM Web

Application de gestion du SAV des onduleurs : **React / TypeScript**, API **Django**, base **PostgreSQL 16** commune à tous les utilisateurs. Les dossiers sont enregistrés sur le serveur ; chaque ordinateur se connecte à la même application. Aucun dossier métier n'est stocké dans le `localStorage` du navigateur.

Le **Tableau de bord** s'ouvre par défaut pour les administrateurs, responsables et techniciens. Le formulaire SAV simple reçoit le client, la série et le livreur d'arrivée ; une série inconnue reste enregistrable avec **Modèle non identifié**. Il présente les anciens passages et oriente la garantie ou le devis provisoire sans émettre de facture ni inventer de garantie. **Options avancées** conserve l'ancien formulaire pour l'administrateur et le responsable. Voir [la réception SAV simple](docs/GUIDE_SUIVI_SAV.md#enregistrer-une-arrivée-avec-le-formulaire-sav-simple).

Le dossier suit ensuite le parcours affectation → confirmation du technicien → suivi, puis fiches d'intervention et rapports PDF selon l'opération. Un changement de statut dans le suivi exige une observation ; une réaffectation managériale remet la prise en charge à confirmer. L'administrateur et le responsable continuent à assurer le suivi, avec les validations techniques et financières habituelles. Voir [la prise en charge et le suivi](docs/GUIDE_SUIVI_SAV.md#affecter-et-confirmer-la-prise-en-charge).

La vérification de garantie présente le modèle, la génération, les références et les dates, avec la règle **fabrication + six mois calendaires** et priorité aux garanties enregistrées. Après confirmation de prise en charge, le dossier propose la configuration de batteries du modèle exact ; le technicien confirme ou corrige le nombre constaté, sans réécrire les anciens rapports. Voir [la garantie et les batteries](docs/GUIDE_SUIVI_SAV.md#vérifier-la-garantie-et-les-batteries).

Le technicien peut aussi **Prendre en charge** un dossier non affecté ou **Prendre le relais** avec un motif, après confirmation explicite, sans accord préalable d'un responsable. Ces actions conservent l'historique et les anciennes fiches au nom de leur auteur ; elles ne passent pas automatiquement le dossier en maintenance.

L'interface reprend la direction visuelle PowerCare : fond clair, navigation blanche, bleu électrique, cartes, tableaux et graphiques alimentés par la base.

Le compteur de prise en charge utilise la date d’arrivée réelle et passe en retard après deux jours ouvrés, samedi et dimanche exclus. Il se fige à la clôture. Les fiches de réception, les pièces jointes privées ou explicitement partagées et les PDF reprennent les dossiers enregistrés.

Chaque dossier possède un **N° d'intervention / appel TVM** commun à ses visites et un **N° d'appel client** distinct, fourni par le centre SAV client. L'équipe peut rechercher les deux ; le portail client privilégie la référence de son centre, dans le périmètre de sa société. Les `INT-…` restent des références secondaires de visite. Voir [le guide des numéros et du suivi](docs/GUIDE_SUIVI_SAV.md#identifier-un-dossier-avec-les-deux-numéros).

Le suivi SAV ajoute des catégories de demandes avec compteurs, des fiches d'échange, de mise en service et de prévention, ainsi qu'une chronologie des événements enregistrés. [Le guide de suivi](docs/GUIDE_SUIVI_SAV.md) distingue cet historique web de l'ancien journal HFSQL, qui n'est pas repris automatiquement.

L'annuaire clients propose un import CSV avec prévisualisation, sans écraser les fiches ni reprendre d'anciens comptes. Les données réelles et le CSV privé restent séparés du ZIP public ; [la procédure d'import](docs/GUIDE_SUIVI_SAV.md#annuaire-clients-et-import-csv) explique comment les charger dans sa propre instance.

Pour la prévention, l'objectif de visites du dossier reste distinct du nombre calculé de fiches réellement terminées. Les visites conservent le même appel TVM et leurs références secondaires ; la mise en service dispose de sa fiche et de son PDF dédiés.

Les demandes classées **Échange** alimentent automatiquement leur file de suivi. La validation technique du remplacement et la confirmation financière sont distinctes ; la clôture attend la confirmation d'une facture émise dans le système externe de l'entreprise.

Le menu **Livraisons & retours** réunit les réparations testées et les échanges prêts, avec une colonne **À retourner au client** pour les non-réparables. TVM crée le devis PDF de diagnostic ; la clôture du retour exige une facture externe confirmée ou une gratuité approuvée et justifiée. Cette gratuité ne dispense pas un échange de sa facture. Voir [le parcours](docs/GUIDE_SUIVI_SAV.md#prêt-à-être-livré-et-retour-dun-matériel-non-réparable).

Le portail permet de demander un enlèvement ; le responsable affecte les transports et le livreur enregistre la réception atelier puis la remise au client dans [son espace logistique](docs/GUIDE_SUIVI_SAV.md#enlèvement-réception-atelier-et-remise-au-client). La série peut venir d'une saisie, d'une douchette, d'une caméra compatible ou d'une photo, toujours vérifiée avant confirmation.

Les livreurs TVM disposent d'une **file partagée des prêts à livrer**, avec prise volontaire ou confirmation de mission affectée et notifications dans l'application. Ils préparent leurs **BL PDF individuels ou par lot d'un même client**, conservés à l'identique. Le BL reste distinct de la remise physique, du stock et de la facture. Voir [le parcours livraison et BL](docs/GUIDE_SUIVI_SAV.md#prendre-une-livraison-dans-la-file-partagée).

Les notifications sont enregistrées dans TVM. Le livreur peut activer son rappel interne de 08:00. Un journal prépare aussi les messages e-mail/WhatsApp du responsable du centre pour les affectations et collectes. **Ces canaux restent désactivés et à connecter** ; les adaptateurs fournis ne relancent pas automatiquement les anciens messages bloqués. Voir [les notifications et leurs réglages](docs/GUIDE_SUIVI_SAV.md#notifications-et-rappels-du-livreur).

L’**Assistant diagnostic** s’appuie sur une bibliothèque technique privée et des retours d’interventions terminées, soumis à validation humaine et filtrés par marque et modèle exacts. La recherche locale fonctionne sans clé IA. L’analyse OpenAI reste à configurer sur le serveur ; elle ne certifie pas une panne et ne modifie aucun dossier automatiquement. Voir [le parcours documents, cas et diagnostic](docs/ASSISTANT_DIAGNOSTIC.md).

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

Sur une installation neuve, les comptes fictifs sont `admin`, `responsable`, `technicien`, `livreur` et `client`. Leur mot de passe est **généré localement**, disponible dans `.local/demo-access.txt`, jamais codé en dur. Le compte `client` sert à tester le portail limité à sa société. Une démo déjà initialisée conserve ses comptes : l'administrateur ajoute le rôle Livreur depuis **Comptes & accès**. Le mode démonstration est signalé dans l'application.

`setup.sh --demo` initialise `.env`, installe les dépendances, démarre PostgreSQL, compile le frontend, applique les migrations et ajoute les données fictives. Un `.env` existant est conservé. Si ce fichier désactive la démo, le script n'y active pas silencieusement les comptes fictifs.

### Activer l’analyse IA, si souhaité

La bibliothèque et sa recherche n’exigent aucune clé. Pour autoriser l’analyse OpenAI, l’administrateur renseigne **uniquement dans le `.env` privé du serveur** `TVM_AI_API_KEY`, `TVM_AI_ENABLED=1`, `TVM_AI_MODEL=gpt-4.1-mini` et `TVM_AI_TIMEOUT=20`. La clé ne doit jamais être placée dans le navigateur, un fichier `VITE_*`, les sources ou une conversation.

Après modification de `.env`, recréer le service Docker pour charger les nouvelles valeurs, depuis le dossier du projet :

```bash
docker compose --profile container up -d --no-build --force-recreate --wait web
```

En mode Python local, arrêter Gunicorn puis relancer `bash scripts/start.sh`. Conserver les volumes de données. Une clé renseignée ne prouve pas une connexion réussie ; les appels réels peuvent être payants. `store: false` est demandé à OpenAI sans garantir une rétention nulle. Le [guide de l’assistant](docs/ASSISTANT_DIAGNOSTIC.md#activer-lanalyse-openai-sur-le-serveur) décrit l’activation et les limites.

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
| Ajouter des manuels et retours validés, rechercher puis activer l’IA côté serveur | [Assistant diagnostic](docs/ASSISTANT_DIAGNOSTIC.md) |
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
