# Installer TVM sur votre PC Windows

Cette procédure installe l’application sur **votre PC Windows 10 ou 11**, avec une base PostgreSQL conservée sur ce PC. Votre navigateur ouvre ensuite l’application à l’adresse **http://localhost:8000**. Le logiciel n’est pas installé dans le cloud par cette procédure.

## 1. Préparer Docker Desktop

Installez [Docker Desktop pour Windows](https://docs.docker.com/desktop/setup/install/windows-install/) depuis le site officiel. Votre version de Windows doit satisfaire ses prérequis actuels. Choisissez le moteur **WSL 2** si proposé, appliquez les instructions affichées par l’installateur et redémarrez Windows si nécessaire. Docker peut demander l’activation de la virtualisation matérielle ou une mise à jour de WSL.

Ouvrez ensuite Docker Desktop et attendez que son moteur soit démarré. Il doit utiliser les **conteneurs Linux**. Python, Node.js, PostgreSQL et Bash n’ont pas besoin d’être installés séparément sur votre PC : Docker exécute ces composants dans les conteneurs.

Une connexion Internet est nécessaire lors de la première installation pour télécharger les images et les dépendances. Le premier démarrage peut prendre plusieurs minutes. L’installation ne désactive ni la vérification des certificats, ni les signatures, ni la politique d’exécution Windows.

## 2. Extraire tous les fichiers

Extrayez **toute l’archive des sources**, par exemple dans `C:\TVM`. N’exécutez pas les scripts directement depuis l’aperçu du fichier ZIP et ne les déplacez pas seuls sur le Bureau.

Le dossier doit contenir notamment :

```text
INSTALLER_TVM.cmd
DEMARRER_TVM.cmd
ARRETER_TVM.cmd
REPARER_CONNEXION_TVM.cmd
compose.yaml
Dockerfile
backend\
frontend\
scripts\
docs\
```

Les chemins contenant des espaces sont pris en charge. Pour éviter les particularités des dossiers synchronisés ou des partages réseau, choisissez de préférence un dossier local simple comme `C:\TVM`. Le dossier doit être accessible en écriture et autorisé au partage avec Docker Desktop si celui-ci le demande.

## 3. Installer et essayer

Double-cliquez sur **`INSTALLER_TVM.cmd`**. Laissez la fenêtre ouverte pendant la construction et attendez le message « Installation terminée ».

Le programme :

1. Vérifie la présence de Docker Desktop, de son moteur actif et de Docker Compose, ainsi que le mode conteneurs Linux.
2. Crée la configuration locale `.env` avec des secrets aléatoires. **Un fichier `.env` existant est conservé sans modification.** Si le volume de base TVM existe déjà mais que le dossier ne contient pas de `.env`, l'installation s'arrête avant de générer de nouveaux secrets et demande de récupérer l'ancienne configuration.
3. Construit l’application et prépare les tables PostgreSQL. Les comptes et les données fictives sont ajoutés uniquement si la configuration indique `TVM_DEMO_MODE=1`.
4. Démarre la base et le serveur, puis attend leurs contrôles de disponibilité avant d’ouvrir le navigateur.

Sur une installation neuve, le mode démonstration est activé pour vous permettre de tester le logiciel. Le Bloc-notes ouvre `.local\demo-access.txt`, qui contient le mot de passe généré localement pour les comptes fictifs :

| Identifiant | Usage |
|---|---|
| `admin` | Administration et gestion des comptes |
| `responsable` | Gestion du SAV |
| `technicien` | Interventions du technicien |
| `livreur` | Réception physique et tournées affectées, sur une démo neuve |
| `client` | Portail limité à sa société de démonstration |

L’interface signale le mode démonstration. Ces comptes servent à l’essai ; ils ne constituent pas une installation avec les données HFSQL de votre entreprise. L’export et la reprise réels sont décrits dans [EXPORT_HFSQL.md](EXPORT_HFSQL.md).

Si le navigateur ne s’ouvre pas automatiquement, ouvrez **http://localhost:8000** sur **ce même PC**. Si le Bloc-notes ne s’ouvre pas, ouvrez le fichier `.local\demo-access.txt` depuis l’Explorateur. Un ancien fichier d’accès peut ne plus correspondre aux comptes si vous avez changé leurs mots de passe ou réutilisé une configuration réelle ; l’installateur ne les réinitialise pas.

Vous pouvez tester le parcours : client → équipement et numéro de série → demande SAV → intervention → rapport PDF. Une fenêtre privée permet d’essayer en parallèle le compte `client` et son accès limité.

## 4. Utiliser l’application les jours suivants

Ouvrez Docker Desktop et attendez que son moteur soit prêt, puis double-cliquez sur **`DEMARRER_TVM.cmd`**. Ce script démarre l’installation existante et attend sa disponibilité ; il ne reconstruit pas l’image, ne réinstalle pas les dépendances et ne remet pas les comptes à zéro.

Pour arrêter l’application, double-cliquez sur **`ARRETER_TVM.cmd`**. Le serveur et PostgreSQL s’arrêtent, **les données et les comptes restent conservés**. Fermer l’onglet du navigateur seul n’arrête pas les services Docker.

Les scripts laissent leur fenêtre ouverte jusqu’à l’appui sur une touche, y compris en cas d’erreur. Ils conservent le code d’échec de la commande concernée. Un code `0` signifie que l’opération a abouti ; les codes non nuls sont accompagnés d’un message décrivant l’étape en échec. Le code `2` est utilisé lorsqu’un fichier nécessaire manque.

## Mettre à jour l’application sans perdre la configuration

Le plus simple est de conserver le dossier TVM qui fonctionnait déjà. Avant de remplacer les sources :

1. Arrêtez l’application avec `ARRETER_TVM.cmd`.
2. Sauvegardez ensemble **la base, les pièces jointes déjà présentes et la configuration locale**, selon [la procédure ci-dessous](#sauvegarder-la-base-et-les-pièces-jointes-sur-windows).
3. Remplacez les fichiers sources par ceux de la nouvelle archive en conservant **`.env`, `.local` et les données Docker**.
4. Relancez `INSTALLER_TVM.cmd` depuis ce même dossier pour reconstruire et démarrer l’application avec ses migrations.

Les fichiers joints utilisent le volume Docker persistant `tvm-powercare_tvm_media` ; la base utilise `tvm-powercare_tvm_postgres`. Garder `.env` et `.local` est nécessaire, mais ne copie pas automatiquement ces volumes. Ne les supprimez pas pour mettre à jour l’application.

Si vous préférez utiliser un nouveau dossier extrait, copiez-y d’abord **le fichier `.env` et le dossier `.local` de l’ancienne installation**. Si le nouveau dossier possède déjà ces éléments, conservez-en une copie dans un dossier de sauvegarde local avant de les remplacer par ceux de l’ancienne installation. Relancez ensuite `INSTALLER_TVM.cmd` dans le dossier que vous utiliserez désormais.

Si ces éléments ne sont pas visibles, ouvrez l’Explorateur Windows et activez **Afficher → Afficher → Éléments masqués**. Sous Windows 10, cochez **Éléments masqués** dans l’onglet **Affichage**. Le fichier à récupérer s’appelle exactement `.env`, et non `.env.example`.

Un nouveau dossier d’archive **ne crée pas une nouvelle base** : les lanceurs utilisent un nom de projet Docker Compose fixe et retrouvent le volume PostgreSQL existant. La mise à jour ne demande ni suppression de volume, ni réinitialisation de la base. Gardez les fichiers de configuration et leur copie de sauvegarde sur votre PC ; ils ne doivent pas être partagés.

La version ajoute le suivi des échanges et une validation financière distincte. Après installation, l'administrateur peut accorder **Peut valider la facturation** dans **Comptes** aux personnes internes choisies. Ce droit n'est pas donné automatiquement au rôle Responsable SAV ou Technicien ; les délégations déjà enregistrées restent conservées.

Les anciens échanges et visites restent conservés sans approbation technique ou facture inventée. La procédure **Échange → validation technique → Prêt à être livré**, puis **Échanges à facturer → Confirmer la facturation** est décrite dans [le guide](GUIDE_SUIVI_SAV.md#échange--remplacement-et-facturation). La mise à jour du code ne signifie pas que cette procédure a déjà été effectuée dans la base du PC.

Le suivi commun **Prêt à être livré** et les devis de diagnostic TVM utilisent aussi cette mise à jour. Les anciens dossiers ne reçoivent pas de tests validés ou de gratuité par déduction. Après installation, saisir le résultat réel, les données du devis et les décisions financières dans votre instance, selon [le parcours prêt / retour](GUIDE_SUIVI_SAV.md#prêt-à-être-livré-et-retour-dun-matériel-non-réparable).

Le service Docker `reminders` démarre avec l'application après les migrations. Il prépare les rappels internes de 08:00 et traite le journal des messages du responsable client. Les canaux e-mail/WhatsApp restent désactivés tant que leurs accès serveur et l'option de la société ne sont pas configurés. Une mise à jour ne provoque pas l'envoi des anciennes entrées bloquées. `ARRETER_TVM.cmd` suspend aussi ce worker ; notifications et préférences restent dans la base conservée. Voir [la connexion des canaux](DEPLOIEMENT.md#connecter-les-notifications-externes-du-responsable-client).

## Importer son annuaire clients après la mise à jour

Le ZIP public contient les sources génériques, pas les noms et contacts réels issus des captures. Le CSV des clients est un fichier privé fourni séparément ; ne le publier ni avec les sources ni avec d'anciens identifiants de connexion.

1. Mettre à jour l'installation avec la procédure ci-dessus, en conservant `.env`, `.local` et les volumes, puis relancer `INSTALLER_TVM.cmd` pour appliquer les migrations.
2. Se connecter comme administrateur ou responsable, ouvrir **Clients → Importer des clients** et sélectionner le fichier privé UTF-8.
3. Cliquer sur **Prévisualiser l'import**, examiner les erreurs ou conflits et les valeurs marquées à vérifier, puis **Appliquer l'import** des lignes saines.
4. Contrôler le bilan et retrouver les fiches dans l'annuaire. Les anciens comptes et mots de passe ne sont pas importés ; l'administrateur gère les accès séparément.

Un import effectué dans le cloud ne signifie pas que la base de votre PC est déjà alimentée. Cette opération doit être faite dans votre instance Windows. Voir [le format CSV et les règles de conservation](GUIDE_SUIVI_SAV.md#annuaire-clients-et-import-csv).

## Si quelque chose bloque

| Message ou symptôme | Action |
|---|---|
| Docker Desktop introuvable | Installer Docker Desktop, puis ouvrir une nouvelle fenêtre ou relancer le script après installation. |
| Moteur Docker non prêt | Ouvrir Docker Desktop, attendre son démarrage et appliquer ses instructions WSL 2 ou de redémarrage. |
| Le moteur a indiqué le mode Windows | Dans la zone de notification Windows, faire un clic droit sur l’icône baleine Docker, choisir **Switch to Linux containers…** si cette option est proposée, puis attendre que le moteur soit prêt. |
| Mode Docker absent ou non reconnu | Exécuter la commande de diagnostic ci-dessous. Cette erreur ne prouve pas que Docker utilise des conteneurs Windows ; ne pas changer de mode sans vérifier le résultat. |
| Échec de téléchargement ou de certificat | Vérifier Internet et, en entreprise, le proxy et le certificat de confiance autorisé. Ne pas désactiver les vérifications TLS. |
| `lookup auth.docker.io: no such host` | Problème DNS d'accès au registre Docker : suivre le dépannage réseau ci-dessous. Ce message ne concerne pas le mot de passe PostgreSQL. |
| Fichiers manquants ou dossier inaccessible | Extraire toute l’archive dans un dossier local accessible, puis relancer le script dans ce dossier. |
| Port `8000` ou `55432` déjà utilisé | Identifier l’application qui utilise ce port. Ne pas arrêter un service inconnu ; faire adapter les ports par votre support si nécessaire. |
| Image locale manquante au prochain démarrage | Relancer `INSTALLER_TVM.cmd`. La configuration est conservée et les données ne sont pas effacées. |
| `password authentication failed for user "tvm"` | Récupérer d’abord la configuration de l’ancienne installation. Si le refus persiste, suivre la procédure `REPARER_CONNEXION_TVM.cmd` ci-dessous. Ne pas supprimer la base. |
| Échec de disponibilité après trois minutes | Lire les messages dans la fenêtre. Les services peuvent avoir démarré sans être prêts ; consulter leurs journaux avant de réessayer. |

### Docker ne résout pas `auth.docker.io`

Le message `lookup auth.docker.io: no such host` signale un problème de résolution réseau pendant le téléchargement d'une image. Il ne signale pas une panne de la base TVM ou un mauvais mot de passe PostgreSQL.

1. Ouvrir **PowerShell en tant qu'administrateur** et vider le cache DNS Windows :

```powershell
ipconfig /flushdns
```

2. Dans Docker Desktop, ouvrir **Troubleshoot**, puis **Restart Docker Desktop**. Attendre le redémarrage du moteur ; ne pas utiliser l'effacement des données ou le retour aux paramètres d'usine.
3. Tester l'accès au registre :

```powershell
docker pull node:24-alpine
```

4. Si le téléchargement réussit, relancer `INSTALLER_TVM.cmd` depuis le **même dossier**, avec son `.env` et ses volumes conservés. Si le DNS échoue encore, faire vérifier le réseau ou le proxy Windows avant de poursuivre ; modifier un DNS dans le moteur Docker ne garantit pas la correction des téléchargements du daemon.

Cette procédure conserve les données. Elle ne réinitialise ni PostgreSQL ni ses accès. Son exécution sur le PC Windows reste à vérifier ; un succès dans le cloud Linux ne prouve pas la résolution du problème réseau local.

### Erreur de mot de passe PostgreSQL après une mise à jour

L’erreur `password authentication failed for user "tvm"` peut se produire si le nouveau dossier contient un `.env` généré avec un nouveau mot de passe, alors que Docker conserve la base de l’installation précédente. **Modifier le mot de passe dans `.env` ne change pas celui d’une base PostgreSQL déjà initialisée.**

Pour retrouver les bons accès sans effacer les données :

1. Fermez la fenêtre de l’installateur en échec et retrouvez le dossier TVM utilisé lorsque l’application fonctionnait.
2. Dans l’Explorateur, activez **Afficher → Afficher → Éléments masqués** si nécessaire. Repérez le fichier `.env` et le dossier `.local` dans cet ancien dossier.
3. Dans le dossier où vous lancez maintenant TVM, conservez d’abord une copie locale du `.env` et du dossier `.local` qui s’y trouvent déjà. Ne les écrasez pas avant cette copie.
4. Copiez ensuite **le `.env` et le dossier `.local` de l’ancienne installation** vers ce dossier, en acceptant le remplacement des nouveaux éléments après la sauvegarde.
5. Relancez `INSTALLER_TVM.cmd` depuis ce même dossier. Le programme réutilise la base existante avec sa configuration d’origine.

### Si le refus persiste : réparer la connexion existante

Si l’erreur persiste après avoir recopié l’ancien `.env`, utilisez le réparateur fourni dans la version corrigée. Vous pouvez aussi l’utiliser si l’ancien `.env` est introuvable mais que **le dossier en échec possède déjà son propre `.env`**. Le réparateur ne génère pas de configuration manquante.

1. Ouvrez Docker Desktop et attendez que son moteur Linux soit prêt.
2. Depuis la nouvelle archive, copiez **`REPARER_CONNEXION_TVM.cmd` et le dossier complet `scripts`** dans le dossier où `INSTALLER_TVM.cmd` affiche le refus de connexion. Acceptez le remplacement des scripts. **Conservez le `.env` et le dossier `.local` déjà présents.**
3. Dans ce même dossier, double-cliquez sur **`REPARER_CONNEXION_TVM.cmd`** et laissez la fenêtre ouverte jusqu’au résultat.
4. Si la fenêtre annonce que la connexion fonctionne déjà ou que la réparation est terminée, fermez-la puis relancez **`INSTALLER_TVM.cmd` depuis ce même dossier**.

Le réparateur vérifie d’abord la connexion sur le réseau Docker. Si elle fonctionne, il ne change aucun mot de passe. Si un refus de mot de passe est confirmé, il sauvegarde la base et une copie de la configuration dans **`.local\backups`**, vérifie la copie de sauvegarde sur le PC, puis aligne le mot de passe technique PostgreSQL sur celui du `.env` existant. Il contrôle ensuite la connexion et vérifie qu’un mauvais mot de passe est bien refusé. Si la sauvegarde ne peut pas être copiée et vérifiée, l’alignement n’est pas effectué.

Le contenu du `.env` reste inchangé. Le réparateur ne recrée pas la base, ne supprime aucun volume ni dossier et ne modifie pas les règles d’authentification PostgreSQL. **Les comptes TVM et leurs mots de passe restent ceux de l’installation précédente.** Si `.local\demo-access.txt` a été créé dans un nouveau dossier lors de l’échec, son mot de passe peut ne pas correspondre aux comptes déjà présents dans la base : le réparateur ne les réinitialise pas. Utilisez vos accès précédents.

Si le lanceur signale que l’image web manque, relancez `INSTALLER_TVM.cmd` pour la construire, puis revenez au réparateur si le refus PostgreSQL est toujours présent. Pour toute autre interruption, conservez le message affiché et les sauvegardes pour le diagnostic ; ne relancez pas des réparations au hasard.

Ne régénérez pas des mots de passe au hasard, ne supprimez aucun volume et n’utilisez pas la réinitialisation de Docker Desktop. Ne publiez ni `.env`, ni `.local`, ni les fichiers de `.local\backups` : les copies de configuration et la base contiennent des informations privées.

Pour consulter l’état ou les derniers journaux, ouvrez un terminal **dans le dossier du projet** et utilisez :

```powershell
docker compose --profile container ps
docker compose --profile container logs --tail 80
```

Pour vérifier directement le mode du moteur, sans installer ni modifier quoi que ce soit :

```powershell
docker info --format "{{.OSType}}"
```

Le résultat attendu est **`linux`**. Si le résultat est **`windows`**, utilisez le menu **Switch to Linux containers…** de Docker Desktop. Si le menu propose au contraire **Switch to Windows containers…**, ne choisissez pas cette option : elle ferait passer vers les conteneurs Windows. Si une erreur s’affiche ou si le résultat diffère, conservez la sortie exacte pour le diagnostic ; les scripts n’en déduisent plus automatiquement un mode Windows et ne changent jamais le moteur à votre place.

Les lanceurs affichent désormais le mode détecté et distinguent une réponse `windows` d’une sortie absente ou inconnue. Ils n’utilisent plus la correspondance exacte d’une ligne par `FINDSTR` pour ce contrôle. Une réponse `linux` permet de continuer l’installation normalement.

Ne partagez pas le fichier `.env` ni `.local\demo-access.txt` : ils contiennent les secrets de votre installation. N’utilisez pas la suppression des volumes ou une réinitialisation des données de Docker Desktop pour réparer un démarrage : cela peut effacer la base. Une simple relance des scripts ne demande aucune suppression de données.

## Configuration réelle déjà présente

Si le dossier contient déjà une configuration avec `TVM_DEMO_MODE=0`, l’installateur la conserve, applique les migrations et **n’ajoute aucun compte ni dossier de démonstration**. Il ne change pas vos mots de passe.

Pour une base réelle neuve préparée par votre support mais ne possédant aucun administrateur, exécutez une seule fois dans le terminal du dossier, une fois le serveur démarré :

```powershell
docker compose --profile container exec web python manage.py createsuperuser --username admin
```

Le mot de passe est saisi de manière interactive et ne s’affiche pas. Créez ensuite les comptes nominatifs dans l’application. Le passage d’une démonstration à une utilisation réelle doit prévoir une base propre, les sauvegardes et la reprise validée des données ; changer simplement la bannière de démonstration ne transforme pas les données fictives en données réelles.

## Accès depuis d’autres ordinateurs et sauvegardes

`localhost` désigne toujours l’ordinateur sur lequel le navigateur est ouvert. L’installation livrée lie le serveur au PC local ; ouvrir `localhost:8000` sur un autre ordinateur ne se connectera pas à votre PC. Un accès partagé pour les 5–15 utilisateurs demande une installation serveur commune avec une adresse réseau, HTTPS et les réglages décrits dans [DEPLOIEMENT.md](DEPLOIEMENT.md).

Les données sont conservées dans le volume PostgreSQL Docker de cette installation. Gardez le dossier du projet et sa configuration, et prévoyez une sauvegarde de la base avant toute réinstallation de Docker ou migration vers un autre PC.

Les pièces jointes sont stockées dans un **second volume**, `tvm-powercare_tvm_media`, et non dans le ZIP des sources. Une sauvegarde et une restauration doivent conserver ensemble le contenu de ce volume et la base qui référence les fichiers. Les droits du volume média doivent permettre l'accès au serveur web, exécuté avec l'UID `10001`.

### Sauvegarder la base et les pièces jointes sur Windows

Le script `scripts/backup.sh` prépare l'ensemble de sauvegarde en environnement Bash compatible ; il n'est pas un lanceur Windows à double-clic. Avec Docker Desktop, la procédure d'administration suivante permet de garder les écritures arrêtées pendant la copie :

1. Fermez l'application avec **`ARRETER_TVM.cmd`** et ne la redémarrez pas pendant la capture. Ce lanceur arrête **le serveur web et le worker de rappels `reminders`**, afin de suspendre les écritures pendant la sauvegarde de la base et des fichiers.
2. Ouvrez **l'Invite de commandes Windows (`cmd.exe`) dans le dossier TVM** : depuis l'Explorateur, saisir `cmd` dans sa barre d'adresse puis appuyer sur Entrée. Pour les redirections de fichiers binaires ci-dessous, **ne pas utiliser PowerShell 5**.
3. Exécutez les commandes suivantes. Elles correspondent à la configuration livrée, avec une base et un rôle nommés `tvm` ; si votre support les a changés, il doit adapter ces deux noms.

```bat
set "TVM_BACKUP_DIR=.local\backups\avant-mise-a-jour-%RANDOM%-%RANDOM%"
mkdir "%TVM_BACKUP_DIR%"
docker compose up -d --wait db
docker compose exec -T db pg_dump -U tvm -d tvm -Fc > "%TVM_BACKUP_DIR%\database.dump"
docker compose exec -T db pg_restore --list < "%TVM_BACKUP_DIR%\database.dump" > NUL
copy /b ".env" "%TVM_BACKUP_DIR%\.env"
echo Dossier de sauvegarde : %TVM_BACKUP_DIR%
```

Une erreur à l'une de ces étapes doit être examinée avant de poursuivre. Le catalogue lisible du dump ne remplace pas un test de restauration.

4. Sans redémarrer le serveur web ni le worker de rappels, ouvrez la vue **Volumes** de Docker Desktop et sélectionnez **`tvm-powercare_tvm_media`**. Utilisez son export/sauvegarde vers **un fichier local**, dans le dossier de sauvegarde affiché par l'Invite de commandes. Ne choisissez pas une publication vers un registre ou un cloud. Conservez cette archive avec `database.dump` et `.env` du même instant.
5. Si ce volume n'existe pas encore, il n'y a pas de volume média à exporter. Si un ancien dossier `backend\media` contient déjà des fichiers, faites-en également une copie pendant l'arrêt. Si l'export local n'est pas proposé par votre version de Docker Desktop, utilisez le script Bash documenté avec votre support plutôt que de copier seulement la base.
6. Une fois la base et les fichiers conservés ensemble, relancez **`DEMARRER_TVM.cmd`**, ou **`INSTALLER_TVM.cmd`** si vous appliquez la mise à jour des sources.

Conservez ces sauvegardes dans un emplacement privé et gardez une copie hors du PC selon votre organisation. Ne partagez pas `.env`, le dump ou les pièces jointes. Pour vérifier une restauration, utiliser d'abord **une base et un volume média neufs**, conformément à [la procédure de restauration de test](DEPLOIEMENT.md#tester-une-restauration-sans-remplacer-la-base-active) ; ne pas écraser la base active pour essayer.

## Périmètre de validation

L’application et le parcours conteneurisé sont validés dans l’environnement Linux de développement. Les fichiers Windows ont fait l’objet d’une revue statique ; **leur lancement natif dans Windows / Docker Desktop reste à vérifier sur votre PC**. L’état du cloud ne prouve pas que Docker, WSL 2, les ports ou les autorisations sont déjà configurés sur votre ordinateur personnel.

Ce périmètre s’applique également à `REPARER_CONNEXION_TVM.cmd` : sa revue et les contrôles de ses composants sous Linux ne constituent pas une validation de son exécution native sous Windows.
