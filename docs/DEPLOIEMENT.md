# Déploiement pour une équipe de 5–15 utilisateurs

## Un serveur commun

Installer l'application une seule fois sur un serveur de l'entreprise ou un serveur hébergé. Les postes internes et les clients accèdent à cette même adresse avec leur navigateur. Ne pas installer une base séparée sur chaque ordinateur : cela empêcherait le partage des dossiers.

Le dimensionnement livré utilise trois workers Gunicorn et PostgreSQL 16. Il constitue un point de départ pour cette petite équipe ; aucun test de charge de production ne doit être déduit du nombre de workers. Choisir le stockage, les sauvegardes et la mémoire selon les volumes réels, notamment les pièces jointes enregistrées.

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
| `TVM_MEDIA_ROOT` | Stockage privé des pièces jointes ; conserver le chemin livré, ou adapter aussi les montages et sauvegardes si votre administrateur le modifie |
| `TVM_DEMO_MODE` | `0` sur l'installation réelle |
| `TVM_DEMO_PASSWORD` | Vide hors démonstration |

Changer une valeur d'environnement n'est pas une rotation automatique des identifiants d'un PostgreSQL déjà initialisé. Appliquer une rotation avec la procédure administrateur de la base puis mettre à jour les services concernés.

## HTTPS et réseau

Placer un reverse proxy avec certificat TLS devant le serveur web, sur un nom DNS contrôlé. Il transmet le nom d'hôte d'origine à Django et les requêtes au port web en boucle locale. Définir les hôtes et origines HTTPS exacts dans `.env`, puis activer les cookies sécurisés. Vérifier connexion, déconnexion, écriture et téléchargement PDF avec cette configuration.

L'import du catalogue accepte un fichier XLS de 8 Mio au maximum ; une pièce jointe de dossier peut atteindre 10 Mio. Le proxy doit laisser passer le fichier et l'enveloppe multipart : par exemple `client_max_body_size 11m;` dans le contexte Nginx concerné. Vérifier un import et un téléversement représentatifs après déploiement ; un refus HTTP 413 du proxy intervient avant les contrôles de Django.

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

## Rappels internes de 08:00

Le profil Compose `container` démarre également le service **`reminders`**, avec la même image que `web`, après disponibilité de la base et du serveur migré. Il vérifie les rappels toutes les 60 secondes, réglables par `TVM_REMINDER_POLL_SECONDS` entre 10 et 3 600. Les comptes doivent activer leur préférence ; le démarrage du worker n'active personne automatiquement. Il traite aussi la file des notifications externes décrite ci-dessous, uniquement si le serveur et la société ont explicitement activé le canal.

En mode Python local, après chargement du `.env`, lancer un second processus supervisé :

```bash
.venv/bin/python backend/manage.py logistics_reminders
```

Pour un contrôle ponctuel, ajouter `--once`. Ne pas utiliser la simple ouverture d'une page pour déclencher le traitement : les GET ne créent aucun rappel. Plusieurs workers gardent un seul rappel par destinataire et jour local ; un seul processus supervisé suffit à cette équipe. Le fuseau personnel du compte détermine 08:00, avec repli sur `TVM_TIMEZONE`. Aucun rappel ancien n'est conservé dans une file WhatsApp future.

Les alertes **Onduleur prêt à livrer** et **Livraison affectée** sont distinctes du rappel personnel de 08:00 : elles proviennent des opérations serveur et restent dans TVM. Elles ne demandent ni clé WhatsApp ni préférence de rappel activée. La cloche relit son compteur toutes les 30 secondes et au retour sur l'onglet ; aucun push navigateur fermé n'est fourni. WhatsApp reste soumis à sa configuration séparée.

Les notifications des devis de réparation restent elles aussi dans TVM : émission vers le centre client, nouvel avis vers l'administration. Elles ne déclenchent pas d'e-mail ou de WhatsApp et n'exigent aucune clé fournisseur pour ce parcours.

## Connecter les notifications externes du responsable client

Les adaptateurs SMTP et WhatsApp Cloud API sont fournis, **désactivés par défaut**. Aucun accès SMTP ou WhatsApp réel n'a été fourni ou validé dans la version de travail. Les essais automatisés utilisent une boîte e-mail en mémoire et des transports simulés ; ils ne prouvent pas l'acceptation par votre fournisseur.

Le destinataire est toujours le responsable du centre propriétaire : `Client.contact_name`, `Client.email` et `Client.phone`. Les coordonnées du client final d'une collecte servent au transport, sans remplacer ce destinataire. Dans la fiche société, les options `notify_email` et `notify_whatsapp` sont désactivées par défaut ; leur modification relève d'un administrateur ou responsable.

Renseigner les accès **sur le serveur**, dans `.env` protégé ou le gestionnaire de secrets de l'hébergement. Ne pas les copier dans le navigateur, Git, une archive publique ou un message de support. Conserver les valeurs des indicateurs d'envoi à `0` pendant cette préparation.

| Canal | Variables de configuration |
|---|---|
| SMTP | `TVM_SMTP_HOST`, `TVM_SMTP_PORT` (587 par défaut), `TVM_SMTP_USER`, `TVM_SMTP_PASSWORD`, `TVM_SMTP_FROM_EMAIL` (adresse seule, par exemple `sav@example.invalid`) |
| Chiffrement SMTP | `TVM_SMTP_USE_TLS=1` et `TVM_SMTP_USE_SSL=0` pour STARTTLS ; ou l'inverse pour SSL, généralement sur le port 465. Une connexion sans chiffrement ou les deux modes simultanés reste bloquée. |
| WhatsApp | `TVM_WHATSAPP_TOKEN`, `TVM_WHATSAPP_PHONE_ID` numérique, `TVM_WHATSAPP_API_VERSION` (version Meta active choisie), `TVM_WHATSAPP_TEMPLATE`, `TVM_WHATSAPP_LANGUAGE` (`fr` par défaut) |
| Activation explicite | `TVM_EMAIL_ENABLED=1` et/ou `TVM_WHATSAPP_ENABLED=1`, puis option correspondante activée sur chaque société destinataire |
| Délai réseau | `TVM_NOTIFICATION_TIMEOUT`, 10 secondes par défaut, borné de 1 à 30 |

Le numéro WhatsApp de la société doit être en format international avec `+` et indicatif ; aucun pays n'est deviné depuis un numéro local. Le seul hôte appelé est `graph.facebook.com`, en HTTPS avec vérification TLS et sans suivre les redirections. Aucun autre fournisseur ou URL arbitraire n'est configurable.

Le modèle WhatsApp doit être approuvé chez Meta et contenir **cinq paramètres de corps**, dans cet ordre : événement/heure réelle d'affectation/livreur, numéro TVM, référence du centre, numéro de série, adresse du transport. Le nom et le type du livreur proviennent de l'affectation réelle. L'heure d'affectation ne constitue pas un rendez-vous : le message indique que le créneau est à convenir. Ni diagnostic interne, ni notes, ni prix ou facture ne sont transmis.

Après configuration, redémarrer les services pour relire l'environnement. Vérifier le résumé des canaux et un événement de recette avec des destinataires autorisés avant l'ouverture aux centres. Le champ API `configured` contrôle la présence et le format des paramètres, pas la validité du mot de passe ou du jeton chez le fournisseur. `operational`/`ready` signifie que le serveur peut tenter l'envoi ; seul le résultat d'une tentative indique une acceptation.

Les nouveaux événements éligibles alimentent la file. **Activer un canal ne relance jamais les anciennes entrées bloquées.** Un responsable doit ouvrir l'aperçu courant puis relancer explicitement une entrée encore valable. Le destinataire et la mission sont revérifiés avant envoi ; un événement remplacé ou une société incohérente ne part pas. Une autorisation d'envoi de plus de 24 heures doit être revue. Les GET ne déclenchent aucun envoi.

Le worker `reminders` existant traite aussi cette file ; la sauvegarde l'arrête avec `web`. Pour un passage contrôlé, après chargement de `.env` :

```bash
.venv/bin/python backend/manage.py notification_outbox --once
```

Un succès signifie **accepté par le fournisseur**, sans preuve de réception ou de lecture. Un refus temporaire explicite est réessayé avec attente croissante, au plus cinq tentatives. Un timeout, une interruption ou une acceptation incertaine ne sont jamais relancés automatiquement : vérifier chez le fournisseur avant une relance manuelle susceptible de créer un doublon. Les webhooks de réception/lecture ne sont pas implémentés dans cette étape. Les secrets et réponses brutes des fournisseurs ne figurent pas dans les journaux applicatifs.

## Sauvegarder

```bash
bash scripts/backup.sh
```

La commande crée un dump PostgreSQL au format personnalisé dans `.local/backups/`, avec des permissions restrictives, puis vérifie que `pg_restore` peut lire son catalogue. Ce contrôle de lisibilité ne remplace pas un essai de restauration.

Les instantanés et les octets des BL PDF préparés et des devis de réparation émis sont conservés dans PostgreSQL et font partie du dump, avec les réponses client historisées. Ils ne se régénèrent pas depuis les fiches courantes ; conserver la base est donc nécessaire pour leurs réimpressions historiques. Les pièces jointes restent, elles, dans les fichiers média à sauvegarder avec la base.

Elle produit un ensemble portant le même préfixe `tvm-<horodatage UTC>-<suffixe>` :

| Fichier | Contenu |
|---|---|
| `.dump` | Base PostgreSQL |
| `-media.tar.gz` | Volume Docker média, s'il existe |
| `-media-host.tar.gz` | Dossier `backend/media/` du mode hors conteneur, s'il existe |
| `.env` | Copie de la configuration locale, si elle existe |
| `.sha256` | Empreintes des fichiers de cet ensemble |

Le script vérifie la lecture du dump, le catalogue des archives média et les empreintes. Il arrête brièvement les services Compose `reminders` puis `web` s'ils étaient actifs, et reprend seulement ces services à la fin, y compris après une erreur. **Un serveur Gunicorn ou un worker de rappels lancé hors Docker doit être arrêté avant la commande**, ainsi que toute autre source d'écriture ; le script ne peut pas arrêter ces processus à votre place. PostgreSQL doit être démarré.

Conserver les fichiers de même préfixe ensemble. Ne pas remplacer seulement `.env` avec une configuration provenant d'une autre base : les accès et fichiers doivent correspondre à la même installation sauvegardée. Le fichier `.env` copié et le contenu métier sont privés.

Planifier les sauvegardes selon la perte de données acceptable et conserver une copie chiffrée hors du serveur. Sauvegarder aussi la configuration nécessaire au redémarrage via un canal sécurisé. **La base et les pièces jointes doivent être sauvegardées de façon cohérente** : un dump seul ne contient pas les fichiers média.

En mode Docker, les fichiers sont dans `tvm-powercare_tvm_media`, monté sur `/app/backend/media` ; PostgreSQL utilise `tvm-powercare_tvm_postgres`. Hors conteneur, le stockage média par défaut est `backend/media/`. Suspendre les écritures pendant la capture coordonnée de la base et des fichiers. À la restauration, utiliser le même ensemble de sauvegarde, conserver les chemins attendus et attribuer les fichiers à l'UID `10001` du service web conteneurisé.

## Tester une restauration sans remplacer la base active

Utiliser d'abord une base **et un volume média neufs**, sur une machine de test ou le PostgreSQL de développement. Les commandes suivantes supposent que `tvm_restore_check` et `tvm_media_restore_check` n'existent pas. Choisir explicitement un ensemble créé par le script et remplacer le préfixe d'exemple :

```bash
set -e
tvm_restore_prefix='.local/backups/tvm-REMPLACER_PAR_LE_PREFIXE_REEL'
sha256sum --check "$tvm_restore_prefix.sha256"
if docker volume inspect tvm_media_restore_check > /dev/null 2>&1; then
  printf 'Ce volume de test existe déjà : choisir un nom neuf avant de poursuivre.\n' >&2
  exit 1
fi
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" tvm_restore_check'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --exit-on-error --no-owner -d tvm_restore_check' < "$tvm_restore_prefix.dump"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d tvm_restore_check -c "SELECT COUNT(*) FROM core_client;"'
if [[ -f "$tvm_restore_prefix-media.tar.gz" ]]; then
  docker volume create tvm_media_restore_check
  docker run --rm -i --mount type=volume,src=tvm_media_restore_check,dst=/restore postgres:16-alpine sh -c 'cd /restore && tar -xzf - && chown -R 10001:10001 /restore' < "$tvm_restore_prefix-media.tar.gz"
fi
```

La restauration du volume média ne s'effectue que si cet ensemble contient un fichier `-media.tar.gz`. En mode hors conteneur, restaurer l'archive `-media-host.tar.gz` dans un dossier de test distinct, sans écraser le dossier actif.

Vérifier les relations, le nombre de dossiers et les téléchargements d'un échantillon de pièces jointes depuis une instance web de test configurée sur **cette base et ce volume de test**. Vérifier aussi les refus d'accès client. Les commandes ci-dessus ne redirigent pas l'application active vers la copie. Ne supprimer une base ou un volume de test qu'après avoir vérifié son nom et conservé les résultats utiles. Une restauration de production demande une fenêtre de maintenance et un plan de retour séparés ; aucune commande de remplacement destructif de la base active n'est fournie ici.

## Vérifications avant ouverture aux utilisateurs

Exécuter les tests fournis et contrôler un dossier représentatif depuis deux sessions indépendantes. Vérifier les rôles, l'association de chaque compte client à sa société, les refus d'accès à un dossier tiers, le rapport PDF, la caméra d'un téléphone compatible et une restauration de sauvegarde.

Les comptes, données fictives, clés de démonstration et chemins locaux ne doivent pas être présentés comme une installation de production validée. SMTP et WhatsApp restent à connecter et à essayer avec les accès retenus ; leurs adaptateurs et leur journal ne prouvent pas un envoi réel. L'assistant IA reste non connecté.
