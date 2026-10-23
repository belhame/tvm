# Déploiement pour une équipe de 5–15 utilisateurs

## Un serveur commun

Installer l'application une seule fois sur un serveur de l'entreprise ou un serveur hébergé. Les postes internes et les clients accèdent à cette même adresse avec leur navigateur. Ne pas installer une base séparée sur chaque ordinateur : cela empêcherait le partage des dossiers.

Le dimensionnement livré utilise trois workers Gunicorn et PostgreSQL 16. Il constitue un point de départ pour cette petite équipe ; aucun test de charge de production ne doit être déduit du nombre de workers. Choisir le stockage, les sauvegardes et la mémoire selon les volumes réels, notamment les pièces jointes futures.

## Créer une installation sans démo

Pour un nouveau serveur, depuis les sources :

```bash
bash scripts/setup.sh
set -a
source .env
set +a
.venv/bin/python backend/manage.py createsuperuser --username admin
```

Le mot de passe administrateur est saisi de façon interactive. Le superutilisateur a les droits administrateur effectifs même si le champ technique de rôle possède une valeur par défaut différente. Créer ensuite les comptes nominatifs depuis l'application, avec leur rôle et, pour un compte client, la société autorisée.

Ne pas copier la base de démonstration sur un serveur utilisé avec des dossiers réels. Sur un serveur déjà utilisé, préserver la base et définir une procédure de migration ; réinstaller les sources ne doit jamais servir de méthode d'effacement.

## Configuration à régler

Le fichier `.env` local est généré avec des secrets aléatoires et n'est pas versionné. Le conserver avec des permissions restreintes, en dehors des archives à partager. Les données non secrètes et les secrets y sont séparés par leurs noms, mais aucun affichage global de l'environnement n'est nécessaire au diagnostic.

| Variable | Réglage attendu |
|---|---|
| `DJANGO_SECRET_KEY` | Secret aléatoire durable ; ne pas changer à chaque redémarrage |
| `DATABASE_URL` | Connexion à la base commune ; le service Docker `web` utilise l'hôte privé `db` |
| `POSTGRES_PASSWORD` | Secret serveur pour la base ; coordonner tout changement avec PostgreSQL |
| `DJANGO_ALLOWED_HOSTS` | Noms DNS exacts utilisés par l'application, séparés par des virgules ; ne pas utiliser `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origines exactes autorisées, comprenant le schéma et un éventuel port |
| `DJANGO_SECURE_COOKIES` | `1` en HTTPS pour les cookies de session et CSRF |
| `DJANGO_TRUST_PROXY_HEADERS` | `1` uniquement derrière un proxy de confiance qui écrase l'en-tête `X-Forwarded-Proto` reçu du client |
| `DJANGO_SSL_REDIRECT` | `1` pour forcer HTTPS une fois le proxy de confiance correctement configuré |
| `DJANGO_DEBUG` | `0` sur le serveur partagé |
| `TVM_TIMEZONE` | Fuseau métier IANA confirmé, par défaut `Africa/Lagos` |
| `TVM_DEMO_MODE` | `0` sur l'installation réelle |
| `TVM_DEMO_PASSWORD` | Vide hors démonstration |

Changer une valeur d'environnement n'est pas une rotation automatique des identifiants d'un PostgreSQL déjà initialisé. Appliquer une rotation avec la procédure administrateur de la base puis mettre à jour les services concernés.

## HTTPS et réseau

Placer un reverse proxy avec certificat TLS devant le serveur web, sur un nom DNS contrôlé. Il transmet le nom d'hôte d'origine à Django et les requêtes au port web en boucle locale. Définir les hôtes et origines HTTPS exacts dans `.env`, puis activer les cookies sécurisés. Vérifier connexion, déconnexion, écriture et téléchargement PDF avec cette configuration.

L'application ne fournit pas de certificat ni de nom de domaine. L'accès HTTPS est aussi nécessaire à la caméra d'un téléphone distant. Les options `DJANGO_TRUST_PROXY_HEADERS=1` et `DJANGO_SSL_REDIRECT=1` sont à activer après configuration du proxy : celui-ci doit écraser l'en-tête `X-Forwarded-Proto` et empêcher l'accès direct au backend depuis les clients. Vérifier la redirection et l'absence de boucle avant ouverture. HSTS et la politique de certificat restent à définir dans l'infrastructure retenue ; ne pas supposer leur activation par le seul lancement de Gunicorn.

Ne pas publier le port PostgreSQL sur Internet. Compose le lie à `127.0.0.1` sur l'hôte ; les navigateurs communiquent avec l'application, jamais directement avec la base. Le port web est également local par défaut pour être placé derrière le proxy.

## Lancer le service

Mode Python local :

```bash
bash scripts/start.sh
```

Pour un service durable, faire exécuter ce script par le gestionnaire de services de l'hôte avec le bon répertoire de travail et un compte dédié. Arrêter le processus web proprement lors des mises à jour. Un terminal ouvert n'est pas une supervision de production.

Mode Docker complet :

```bash
docker compose --profile container up -d --build
docker compose --profile container exec web python manage.py createsuperuser --username admin
```

La seconde commande n'est requise qu'à la création du premier compte. Les services Compose ont une politique de redémarrage `unless-stopped`. Le service web applique les migrations avant son lancement ; sauvegarder avant une mise à jour des sources ou du schéma.

Les fichiers du dépôt et la configuration conservée ne garantissent pas que des processus sont actifs après une restauration de machine. Relancer les services et vérifier un vrai parcours authentifié, pas seulement un port ouvert.

## Sauvegarder

```bash
bash scripts/backup.sh
```

La commande crée un dump PostgreSQL au format personnalisé dans `.local/backups/`, avec des permissions restrictives, puis vérifie que `pg_restore` peut lire son catalogue. Ce contrôle de lisibilité ne remplace pas un essai de restauration.

Planifier les sauvegardes selon la perte de données acceptable et conserver une copie chiffrée hors du serveur. Sauvegarder aussi la configuration nécessaire au redémarrage via un canal sécurisé. Les pièces jointes ajoutées ultérieurement devront faire partie de cette politique.

## Tester une restauration sans remplacer la base active

Utiliser d'abord une base distincte sur une machine de test ou le PostgreSQL de développement. Les commandes suivantes supposent le nom de base temporaire `tvm_restore_check`, encore inexistant, et un dump choisi explicitement :

```bash
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" tvm_restore_check'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --exit-on-error --no-owner -d tvm_restore_check' < .local/backups/NOM_DU_DUMP.dump
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d tvm_restore_check -c "SELECT COUNT(*) FROM core_client;"'
```

Vérifier aussi les relations, le nombre de dossiers et un parcours dans une instance web de test configurée sur cette base. Ces commandes ne redirigent pas l'application active vers la copie. Ne supprimer une base de test qu'après avoir vérifié son nom et conservé les résultats utiles. Une restauration de production demande une fenêtre de maintenance et un plan de retour séparés.

## Vérifications avant ouverture aux utilisateurs

Exécuter les tests fournis et contrôler un dossier représentatif depuis deux sessions indépendantes. Vérifier les rôles, l'association de chaque compte client à sa société, les refus d'accès à un dossier tiers, le rapport PDF, la caméra d'un téléphone compatible et une restauration de sauvegarde.

Les comptes, données fictives, clés de démonstration et chemins locaux ne doivent pas être présentés comme une installation de production validée. WhatsApp et l'IA restent indisponibles jusqu'à une intégration et des essais réels avec les accès retenus.
