# Installation et développement

Pour un PC Windows, utiliser le [guide avec lanceurs à double-clic](INSTALLATION_WINDOWS.md). Seul Docker Desktop est requis sur Windows pour ce mode ; les prérequis Python et Node.js ci-dessous concernent le développement hors conteneur.

## Choisir le mode

La configuration standard utilise une vraie base PostgreSQL 16 dans Docker, un serveur Django / Gunicorn et le frontend React compilé. Elle convient à l'installation sur un serveur unique auquel les utilisateurs accèdent avec leur navigateur.

Deux façons de lancer le serveur web sont fournies : Python local avec PostgreSQL dans Docker, ou application et PostgreSQL tous deux dans Docker. Ne pas lancer les deux serveurs web en même temps sur le port 8000.

SQLite est uniquement une option explicite pour des tests isolés (`TVM_ALLOW_SQLITE=1`, sans `DATABASE_URL`). Ce n'est pas le mode partagé livré pour les utilisateurs.

## Prérequis

- Python 3.12 avec `venv` et pip.
- Node.js 24 et npm pour compiler le frontend.
- Docker Engine / Docker Desktop avec Docker Compose v2 et un daemon démarré.
- Bash ; sous Windows, utiliser WSL2.
- Accès aux registres de paquets Python et npm, ainsi qu'au registre Docker pour PostgreSQL et, en mode conteneur complet, les images de construction.

Les dépendances Python directes sont déclarées dans `backend/requirements.txt` ; l'installation utilise `backend/requirements.lock.txt`, qui fige aussi les dépendances transitives. Le frontend utilise `frontend/package-lock.json`.

## Installer la version testable

À la racine du dépôt :

```bash
bash scripts/setup.sh --demo
```

Cette commande :

1. Crée `.env` une seule fois avec des secrets aléatoires et des permissions restreintes ; un fichier existant n'est pas écrasé.
2. Prépare `.venv` et installe les dépendances Python.
3. Démarre PostgreSQL et attend son contrôle de disponibilité.
4. Installe les dépendances JavaScript avec `npm ci` et compile React.
5. Applique les migrations Django, collecte les fichiers statiques et exécute le contrôle Django.
6. Avec `--demo` uniquement, crée le jeu de données fictives et les comptes de démonstration.

Les identifiants `admin`, `responsable`, `technicien`, `client` partagent un mot de passe de démonstration aléatoire. Le lire localement dans `.local/demo-access.txt`. Le fichier n'est pas versionné. `.env` contient lui aussi des secrets : ne pas le joindre à un ticket ni à une archive de livraison.

Un `.env` existant avec `TVM_DEMO_MODE=0` reste inchangé. La commande `--demo` ne doit pas être utilisée sur une base de production. L'interface signale le mode démonstration via la configuration du serveur.

## Démarrer et arrêter

```bash
bash scripts/start.sh
```

Le script démarre PostgreSQL si nécessaire, vérifie les migrations puis lance Gunicorn avec trois workers. Il sert l'API et le frontend compilé depuis la même origine, sur le port 8000. L'écoute est limitée à `127.0.0.1` par défaut. Les processus ne sont pas une partie durable des sources ; relancer ce script après le redémarrage de la machine.

Pour arrêter Gunicorn, utiliser `Ctrl+C` dans son terminal. PostgreSQL peut rester actif. Pour arrêter les services Docker en conservant la base :

```bash
docker compose stop
```

Les données relationnelles sont dans le volume Docker `tvm_postgres` du projet Compose. Les pièces jointes du service web conteneurisé sont dans le volume persistant `tvm_media`, monté sur `/app/backend/media`. Ne pas supprimer ces volumes pour « redémarrer » l'application. Ne pas utiliser `docker compose down -v` sur une installation contenant des données à conserver.

Le profil Docker `container` démarre aussi `reminders` pour les rappels internes de 08:00 et les notifications externes explicitement activées. En mode Python local, le lancer séparément après chargement de `.env` : `.venv/bin/python backend/manage.py logistics_reminders`. Voir [le fonctionnement du worker](DEPLOIEMENT.md#rappels-internes-de-0800) et [les accès SMTP/WhatsApp à connecter](DEPLOIEMENT.md#connecter-les-notifications-externes-du-responsable-client). Ces canaux sont désactivés par défaut ; les entrées bloquées ne partent pas automatiquement après configuration.

## Fichiers privés et sauvegardes

Les pièces jointes sont conservées côté serveur, séparément des sources et des fichiers statiques de l'interface. Hors conteneur, le stockage par défaut est `backend/media/` ; dans le mode Docker livré, il utilise le volume média. Le téléchargement passe par l'API authentifiée, pas par une publication du dossier média sur le Web.

Avec le nom de projet Compose livré, les volumes sont `tvm-powercare_tvm_postgres` et `tvm-powercare_tvm_media`. Le service web utilise l'UID `10001` ; les fichiers restaurés doivent rester lisibles par cet utilisateur. Conserver les noms et montages de l'installation existante lors d'une mise à jour.

Une sauvegarde exploitable doit réunir **la base PostgreSQL et les fichiers média d'un même état**, ainsi que la configuration locale conservée de façon sécurisée. Prévoir cette sauvegarde avant d'appliquer des migrations ou de déplacer une installation. Copier le dépôt ou `.local` ne sauvegarde pas à lui seul les volumes Docker. Voir [la sauvegarde et la restauration](DEPLOIEMENT.md#sauvegarder).

## Tester le parcours métier

Avec le compte administrateur, créer au besoin le client et le compte du livreur. Depuis **Nouvelle demande SAV**, choisir le client, saisir une série unique et sélectionner le livreur ; le modèle et la panne peuvent rester à compléter. Un livreur TVM connecté renseigne seulement le client et la série, son identité étant ajoutée par le serveur. Vérifier le reçu, la garantie et les anciens passages éventuels, puis cliquer sur **Terminer**. Le dossier est reçu en **Non affecté**. Les administrateurs et responsables gardent le formulaire détaillé dans **Options avancées**.

Les administrateurs, responsables et techniciens ouvrent le **Tableau de bord** après connexion, puis accèdent à **Demandes SAV**. Un technicien peut prendre le dossier avec **Prendre en charge**, puis commencer le suivi avec ses observations. Il peut aussi **Prendre le relais** d'un collègue avec un motif. L'administrateur ou le responsable peut affecter une autre personne, qui confirme alors sa prise en charge ; l'ancien intervenant garde la lecture sans pouvoir modifier le suivi. Créer ensuite une fiche d'intervention si l'opération le nécessite et télécharger son rapport PDF. Les confirmations existantes restent conservées. Voir [le guide de prise en charge](GUIDE_SUIVI_SAV.md#affecter-et-confirmer-la-prise-en-charge).

Ouvrir un deuxième navigateur ou une fenêtre privée et se connecter au portail client. Le dossier du client doit être visible, les dossiers des autres sociétés et les notes internes doivent rester inaccessibles. Les modifications sont lues depuis la même base serveur ; changer d'ordinateur ne crée pas une base locale distincte.

Le rapport PDF est un document généré depuis le dossier actuel. Sa disponibilité ne signifie ni signature du client, ni envoi automatique, ni archivage d'une version immuable.

Renseigner une arrivée réelle et vérifier le compteur de jours ouvrés ; une ancienne fiche sans arrivée doit rester inconnue. Ajouter ensuite une pièce jointe interne et une autre explicitement partagée. Depuis la session client, vérifier que seule la pièce partagée de sa société est consultable et que le téléchargement d'un document tiers est refusé. La fiche PDF de suivi et le rapport d'intervention doivent utiliser les données du dossier sans notes internes.

## Contrôles automatisés

```bash
bash scripts/test.sh
```

Le script démarre PostgreSQL, lance les tests Django de l'application `core` puis compile le frontend. Les tests utilisent une base de test séparée créée par Django ; le compte PostgreSQL de développement doit pouvoir créer cette base. Les données de démonstration ne sont pas le résultat des tests.

Pour cibler le backend :

```bash
set -a
source .env
set +a
.venv/bin/python backend/manage.py test core --noinput
```

Les commandes sont fournies pour être rejouées. Seul un compte rendu d'exécution permet d'affirmer qu'elles sont passées sur une machine donnée.

Pour les scénarios dans un vrai navigateur :

```bash
bash scripts/e2e.sh
```

Cette commande utilise une base PostgreSQL distincte `tvm_e2e`, installe le runner Playwright et utilise Chromium s'il est disponible. Sinon, elle télécharge le navigateur Playwright ; les bibliothèques système requises par Chromium doivent être présentes. `TVM_CHROMIUM_PATH` permet de choisir un exécutable compatible. Les accès de cette base d'essai restent locaux dans `.local/e2e-password` et sont conservés entre les exécutions ; ils ne sont pas des comptes de production. Les résultats et captures sont sous `.local/`.

## Développer avec rechargement

Terminer une installation avant de lancer ces commandes. Dans un premier terminal, depuis la racine :

```bash
set -a
source .env
set +a
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Dans un deuxième terminal :

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Vite utilise le port 5173 et transmet `/api/` au backend. Les cookies de session et les jetons CSRF restent nécessaires ; ne pas désactiver ces contrôles pour développer. Après modification du frontend, `npm run build` met à jour les fichiers compilés ; redémarrer Gunicorn pour que WhiteNoise recharge le nouvel ensemble d'assets.

## Variante entièrement conteneurisée

Créer la configuration locale :

```bash
python3 scripts/init_env.py
docker compose --profile container up -d --build
docker compose --profile container exec web python manage.py createsuperuser --username admin
```

La construction compile le frontend et installe le backend. Le service `web` applique les migrations et collecte les fichiers statiques avant Gunicorn. La base est accessible au service web par le réseau privé Compose ; elle n'est exposée sur l'hôte qu'en boucle locale.

Dans ce mode, utiliser `docker compose --profile container logs web` pour consulter le démarrage, et `docker compose --profile container exec web python manage.py ...` pour les commandes de gestion. Ne jamais afficher l'environnement complet pour diagnostiquer un problème : il contient les secrets du serveur.

## Préparer l'import HFSQL

Demander au développeur le dossier d'export décrit dans [EXPORT_HFSQL.md](EXPORT_HFSQL.md), puis le conserver hors des sources versionnées. Charger les variables serveur avant les commandes :

```bash
set -a
source .env
set +a
.venv/bin/python backend/manage.py import_hfsql /chemin/absolu/export --validate-only
.venv/bin/python backend/manage.py import_hfsql /chemin/absolu/export --stage
```

La première commande valide sans insérer de données. La seconde conserve les enregistrements sources dans les tables de préparation PostgreSQL, avec les identifiants d'origine. Elle ne crée pas automatiquement les dossiers métier, ni des mots de passe utilisateurs. Les relations et les états doivent être confirmés avant une étape de transformation validée.
