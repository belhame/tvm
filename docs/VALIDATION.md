# Validation de la version livrée

Contrôles exécutés le **22 octobre 2026** dans l'environnement cloud, sur PostgreSQL 16 et Chromium 154. Les données utilisées sont fictives. Le serveur et les données de démonstration sont distincts de la base réservée aux essais navigateur.

| Contrôle exécuté | Résultat |
|---|---|
| `bash scripts/setup.sh --demo` | Installation puis répétition réussies ; `.env` strictement conservé, démo et données préservées, migrations et compilation réussies |
| `bash scripts/test.sh` | **52 tests réussis, 0 échec, 0 ignoré**, base PostgreSQL de test supprimée ; TypeScript et compilation Vite réussis |
| `bash scripts/e2e.sh` | **5 scénarios navigateur réussis**, base séparée `tvm_e2e` |
| `npm audit --json` dans `frontend/` | Aucun avis de vulnérabilité signalé par le registre lors du contrôle |
| Sauvegarde / restauration | Dump PostgreSQL restauré dans une base distincte ; volumes, connexion, tableau de bord et PDF vérifiés ; base temporaire supprimée |
| Image Docker | Construction complète, exécution non privilégiée, connexion PostgreSQL, SPA et assets, session/CSRF, tableau de bord et PDF vérifiés |
| Distribution statique | Fichiers compilés hôte / image comparés par SHA-256 et identiques ; HTML sans cache durable, API privées `no-store` |

## Ce que couvrent les tests

Les 52 tests serveur comprennent 21 contrôles d'import HFSQL, 21 contrôles métier et de permissions, 5 contrôles d'authentification/CSRF, 3 contrôles d'initialisation démo et 2 contrôles de concurrence PostgreSQL. Ils exercent notamment :

- le parcours client → équipement → demande → intervention terminée → PDF ;
- les listes, détails, recherches, tableaux de bord et rapports du portail client, avec refus des identifiants d'une autre société ;
- l'exclusion des notes internes, la gestion des comptes et les droits des techniciens ;
- les séries uniques, les dates, les relations client/contrat/livraison et la clôture avec plusieurs interventions ;
- le refus du stock négatif et deux sorties concurrentes sur la dernière pièce disponible ;
- deux créations simultanées d'interventions pour un même dossier ;
- les identifiants HFSQL longs, SHA-256, chemins, doublons, secrets exclus, transaction et répétition du staging.

Les 5 scénarios Chromium exercent les formulaires du parcours complet, la persistance dans une seconde session, l'isolation client y compris les PDF, l'affichage mobile avec données chargées, et un changement administrateur → client pendant qu'une ancienne réponse est retardée.

La restauration a conservé **5 clients, 8 équipements, 12 demandes, 12 interventions et 6 comptes fictifs**. Le catalogue et les contraintes PostgreSQL ont été restaurés ; une authentification et un téléchargement PDF ont été exécutés sur cette copie avant sa suppression.

La recherche manuelle d'une série a aussi été exécutée dans l'écran scanner et a retrouvé l'équipement autorisé. Les captures dans `docs/screenshots/` présentent les données de démonstration de l'instance principale, sans les enregistrements ajoutés par les tests navigateur.

## Limites de ces résultats

- Aucun export des données SAV HFSQL réelles n'a été fourni. L'import est testé sur des fixtures ; les données réelles ne sont ni migrées ni promues vers les tables métier. Voir [l'export à demander](EXPORT_HFSQL.md).
- Les traitements WLangage binaires ne sont pas convertis. Les règles reconstruites doivent être confrontées à des dossiers de l'entreprise.
- La lecture d'une vraie étiquette par la caméra d'un téléphone physique reste à essayer en HTTPS. La compatibilité dépend du navigateur et de `BarcodeDetector`.
- Aucun message WhatsApp ni appel à un fournisseur IA n'a été effectué. Les écrans indiquent leur état non connecté ; les adaptateurs restent à développer et tester avec les accès retenus.
- Le déploiement sur un domaine de production et un test de charge de 15 utilisateurs simultanés n'ont pas été réalisés. Le serveur partagé est préparé pour cette petite équipe, avec les réglages décrits dans [DEPLOIEMENT.md](DEPLOIEMENT.md).
- La configuration cloud a été enregistrée en brouillon. Sa publication et la restauration dans une nouvelle tâche relèvent de l'interface de l'environnement et n'ont pas été prétendues validées.

## Particularité de la construction Docker dans ce cloud

Le builder a nécessité le proxy existant, une résolution explicite de son nom, le réseau hôte et le certificat CA fourni par la plateforme. Les vérifications TLS ont été maintenues. Le Dockerfile accepte un secret BuildKit optionnel `build_ca` ; ce certificat n'est pas incorporé à l'image. La construction standard décrite dans le guide reste adaptée à un serveur disposant d'un accès réseau normal. Aucun identifiant de proxy n'est enregistré dans les sources.

## Installation Windows — complément du 24 octobre 2026

Les lanceurs `INSTALLER_TVM.cmd`, `DEMARRER_TVM.cmd` et `ARRETER_TVM.cmd` utilisent Docker Desktop, sans installation locale de Python ou Node.js. Leur format ASCII/CRLF, les chemins cités, les destinations de saut et la conservation des codes d'erreur ont été revus statiquement. Les fichiers CMD conservent leurs fins de ligne Windows dans Git et les archives.

Les étapes Docker ont été exécutées sur Linux, dans un projet et un volume PostgreSQL distincts : génération de configuration, migrations sur base neuve, comptes de démonstration, authentification et tableau de bord, disponibilité HTTP et PostgreSQL, répétition sans modifier `.env`, puis arrêt et redémarrage avec conservation d'un client ajouté. Les six clients attendus étaient présents après redémarrage. Le contrôle de disponibilité fonctionne aussi avec un domaine personnalisé et la configuration HTTPS d'un proxy de confiance.

Le lancement natif des fichiers CMD, l'ouverture du Bloc-notes et la configuration Docker Desktop / WSL 2 sur un PC Windows ne peuvent pas être validés depuis ce cloud Linux. Ils restent à vérifier sur le PC de l'utilisateur avec le [guide Windows](INSTALLATION_WINDOWS.md).

## Lecture des séries Eaton — complément du 25 octobre 2026

L'analyse du classeur fourni a relevé une feuille et neuf cellules de description, sans inventaire ni dictionnaire des usines ou des produits. Le classeur reste hors du dépôt. La fonctionnalité ajoutée est une aide de lecture, sans migration de base ni écriture automatique.

- `bash scripts/test.sh` : **65 tests serveur réussis sur PostgreSQL, 0 échec, 0 ignoré**, puis compilation TypeScript / Vite réussie. Les 13 contrôles ajoutés couvrent les segments et zéros initiaux, les exclusions différentes selon la position, les semaines 01–53, les autres formats, les entrées invalides, les quatre rôles, CSRF et l'absence de requêtes métier pendant l'analyse. Aucune année civile n'est calculée ; les exemples A/B ne sont pas utilisés pour interdire les chiffres dans le code d'année.
- `bash scripts/e2e.sh` : **6 scénarios Chromium réussis**, dont l'analyse dans la fiche équipement, l'effacement du résultat après modification du numéro, l'enregistrement d'un autre format, la conservation du modèle et des dates saisis, puis l'analyse et la recherche manuelle dans le scanner sur écran mobile sans débordement horizontal.
- Image Docker reconstruite avec les nouvelles sources ; API d'analyse exécutée dans cette image avec la base PostgreSQL distincte de test, assets compilés et utilisateur non privilégié vérifiés. Les nombres d'équipements et d'événements d'audit sont conservés pendant ces appels d'analyse.

La compatibilité avec des étiquettes Eaton réelles, la portée du format et les correspondances de codes restent à confirmer. Voir [les ambiguïtés du document et les règles appliquées](NUMEROS_SERIE_EATON.md). Aucun appel à Eaton, calcul de garantie ou essai caméra physique n'a été effectué pour cette évolution.

## Réparation de connexion PostgreSQL — complément du 25 octobre 2026

L'erreur d'authentification provoquée par un nouveau mot de passe de configuration et un volume conservant l'ancien a été reproduite sur des projets et volumes PostgreSQL jetables. La base de démonstration principale n'a pas été modifiée par ces essais.

- Les phases réelles de `scripts/repair_database.sh` ont été exécutées : sauvegarde personnalisée, copie sur l'hôte, restauration vérifiée dans une base distincte, puis alignement du mot de passe du seul rôle connecté avec `psql \password`. Le mot de passe en clair n'apparaît ni dans les arguments, ni dans les sorties, ni dans les journaux PostgreSQL même avec `log_statement=all`.
- Les données, identifiants, clés étrangères, attributs de droits du rôle et autorisations sont identiques avant et après réparation. Le nouveau mot de passe permet une connexion TCP sur le réseau Docker ; l'ancien et un mot de passe aléatoire sont refusés.
- Les appels du diagnostic Python monté en lecture seule dans l'image web passent du code `10` (refus d'authentification) au code `0` (connexion vérifiée avec témoin incorrect refusé). Aucun accès aux dossiers n'est nécessaire au diagnostic ; il exécute `SELECT 1` dans une transaction en lecture seule. Le petit conteneur de diagnostic utilise ponctuellement l'UID 0 pour lire les scripts montés ; le serveur web reste non privilégié.
- Une tentative sans sauvegarde, un nouvel échec de sauvegarde après une première vérification, un dump altéré et un verrou concurrent sont refusés avant alignement. Le marqueur de vérification est consommé avant changement du mot de passe.
- La copie de sauvegarde hôte est contrôlée par SHA-256 et par lecture du catalogue avant l'étape de réparation du lanceur. Ces contrôles Docker fonctionnent avec des espaces, une virgule et des parenthèses dans le chemin hôte Linux ; une copie altérée est refusée.
- **72 tests Django réussis sur PostgreSQL**, dont sept nouveaux tests du diagnostic et de la non-divulgation des erreurs de connexion. L'image Docker reconstruite passe aussi ces 72 tests.

`REPARER_CONNEXION_TVM.cmd` a été revu statiquement : ASCII/CRLF, chemins cités, codes de sortie, destinations des sauts, copie et vérification de la sauvegarde avant alignement. Le lancement natif Windows / Docker Desktop reste à vérifier sur le PC de l'utilisateur. Aucun mot de passe de compte applicatif n'est réinitialisé. Le guide précise qu'un fichier d'accès démo généré dans un nouveau dossier peut ne pas correspondre aux comptes conservés.

L'installateur refuse désormais de générer un nouveau `.env` si le volume TVM existe déjà sans configuration dans le dossier courant. Il demande de récupérer la configuration précédente ; aucun volume n'est supprimé et aucune règle d'authentification n'est modifiée.

## Import du catalogue BN — complément du 25 octobre 2026

Le fichier privé original `Product serial number Vers BN.xls` a été validé puis importé dans PostgreSQL de l'instance cloud de travail. Le fichier et son contenu ne figurent pas dans les sources publiques. L'instance Windows de l'utilisateur reste une base distincte, à alimenter via le nouvel écran **Catalogue Eaton**.

| Contrôle | Résultat exécuté |
|---|---|
| Fichier original, révision BN du 30 novembre 2023 | 1 582 produits, 69 entrées de garantie, 64 correspondances code/année |
| Fidélité source | Lignes produits 2–1583 toutes conservées ; 109 codes NA, 5 collisions au sein des profils et 102 codes partagés entre profils conservés |
| Téléversement du fichier original | POST multipart de 3 886 080 octets traité par l'API avec Django `APIClient`, import actif et consultable |
| Réimport via la commande d'administration | Même version active, aucun produit ni aucune garantie dupliqués |
| Données métier préexistantes | Comptages et empreintes SHA-256 des lignes clients, équipements, comptes, demandes, interventions, contrats, garanties métier, pièces, mouvements, livraisons et staging identiques avant/après |
| Contrôles serveur sur PostgreSQL | **120 tests réussis, 0 échec, 0 ignoré**, y compris deux imports simultanés, rollback et activation atomique |
| Interface | TypeScript et compilation Vite réussis ; **8 scénarios Chromium réussis** sur base distincte avec un XLS entièrement fictif |
| Image Docker | Construction réussie avec `xlrd==2.0.2` ; les **120 tests** passent également dans l'image non privilégiée |
| Conservation | Sauvegardes PostgreSQL privées créées avant et après l'import ; catalogue original, exports et sauvegardes exclus de Git |

Les 48 nouveaux contrôles serveur comprennent 28 tests du parseur et 20 tests du stockage, de l'API, des droits et de la concurrence. Ils couvrent les alias d'année propres à chaque profil, les zéros initiaux, les unités de garantie, les durées ambiguës conservées textuellement, le format XLS et ses bornes, les permissions et CSRF, la limite de 8 Mio, la pagination et l'épinglage à une version, l'idempotence et les erreurs sans remplacement partiel du catalogue actif.

Les scénarios navigateur ajoutés exercent l'import depuis le sélecteur de fichier, les compteurs et la révision, les onglets garanties/années, les codes ambigus, le réimport sans doublon, la consultation technicien et le refus client. Le choix explicite d'un modèle ne modifie ni série ni dates ; annuler la fiche n'enregistre aucun équipement. L'affichage du catalogue a été vérifié sur écran mobile sans débordement horizontal.

Cette étape importe un référentiel ; elle ne remplace pas l'ancienne aide de série par une identification universelle des quatre profils et ne calcule aucune fin de garantie. Les limites Windows natives et caméra physique décrites plus haut restent applicables.
