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
2. Crée la configuration locale `.env` avec des secrets aléatoires. **Un fichier `.env` existant est conservé sans modification.**
3. Construit l’application et prépare les tables PostgreSQL. Les comptes et les données fictives sont ajoutés uniquement si la configuration indique `TVM_DEMO_MODE=1`.
4. Démarre la base et le serveur, puis attend leurs contrôles de disponibilité avant d’ouvrir le navigateur.

Sur une installation neuve, le mode démonstration est activé pour vous permettre de tester le logiciel. Le Bloc-notes ouvre `.local\demo-access.txt`, qui contient le mot de passe généré localement pour les comptes fictifs :

| Identifiant | Usage |
|---|---|
| `admin` | Administration et gestion des comptes |
| `responsable` | Gestion du SAV |
| `technicien` | Interventions du technicien |
| `client` | Portail limité à sa société de démonstration |

L’interface signale le mode démonstration. Ces comptes servent à l’essai ; ils ne constituent pas une installation avec les données HFSQL de votre entreprise. L’export et la reprise réels sont décrits dans [EXPORT_HFSQL.md](EXPORT_HFSQL.md).

Si le navigateur ne s’ouvre pas automatiquement, ouvrez **http://localhost:8000** sur **ce même PC**. Si le Bloc-notes ne s’ouvre pas, ouvrez le fichier `.local\demo-access.txt` depuis l’Explorateur. Un ancien fichier d’accès peut ne plus correspondre aux comptes si vous avez changé leurs mots de passe ou réutilisé une configuration réelle ; l’installateur ne les réinitialise pas.

Vous pouvez tester le parcours : client → équipement et numéro de série → demande SAV → intervention → rapport PDF. Une fenêtre privée permet d’essayer en parallèle le compte `client` et son accès limité.

## 4. Utiliser l’application les jours suivants

Ouvrez Docker Desktop et attendez que son moteur soit prêt, puis double-cliquez sur **`DEMARRER_TVM.cmd`**. Ce script démarre l’installation existante et attend sa disponibilité ; il ne reconstruit pas l’image, ne réinstalle pas les dépendances et ne remet pas les comptes à zéro.

Pour arrêter l’application, double-cliquez sur **`ARRETER_TVM.cmd`**. Le serveur et PostgreSQL s’arrêtent, **les données et les comptes restent conservés**. Fermer l’onglet du navigateur seul n’arrête pas les services Docker.

Les scripts laissent leur fenêtre ouverte jusqu’à l’appui sur une touche, y compris en cas d’erreur. Ils conservent le code d’échec de la commande concernée. Un code `0` signifie que l’opération a abouti ; les codes non nuls sont accompagnés d’un message décrivant l’étape en échec. Le code `2` est utilisé lorsqu’un fichier nécessaire manque.

## Si quelque chose bloque

| Message ou symptôme | Action |
|---|---|
| Docker Desktop introuvable | Installer Docker Desktop, puis ouvrir une nouvelle fenêtre ou relancer le script après installation. |
| Moteur Docker non prêt | Ouvrir Docker Desktop, attendre son démarrage et appliquer ses instructions WSL 2 ou de redémarrage. |
| Conteneurs Linux requis | Passer au mode conteneurs Linux dans Docker Desktop. |
| Échec de téléchargement ou de certificat | Vérifier Internet et, en entreprise, le proxy et le certificat de confiance autorisé. Ne pas désactiver les vérifications TLS. |
| Fichiers manquants ou dossier inaccessible | Extraire toute l’archive dans un dossier local accessible, puis relancer le script dans ce dossier. |
| Port `8000` ou `55432` déjà utilisé | Identifier l’application qui utilise ce port. Ne pas arrêter un service inconnu ; faire adapter les ports par votre support si nécessaire. |
| Image locale manquante au prochain démarrage | Relancer `INSTALLER_TVM.cmd`. La configuration est conservée et les données ne sont pas effacées. |
| Échec de disponibilité après trois minutes | Lire les messages dans la fenêtre. Les services peuvent avoir démarré sans être prêts ; consulter leurs journaux avant de réessayer. |

Pour consulter l’état ou les derniers journaux, ouvrez un terminal **dans le dossier du projet** et utilisez :

```powershell
docker compose --profile container ps
docker compose --profile container logs --tail 80
```

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

Les données sont conservées dans le volume PostgreSQL Docker de cette installation. Gardez le dossier du projet et sa configuration, et prévoyez une sauvegarde de la base avant toute réinstallation de Docker ou migration vers un autre PC. Le script de sauvegarde actuel est en Bash ; faites préparer une procédure de sauvegarde Windows ou utilisez un environnement d’administration compatible avec [la procédure documentée](DEPLOIEMENT.md#sauvegarder).

## Périmètre de validation

L’application et le parcours conteneurisé sont validés dans l’environnement Linux de développement. Les fichiers Windows ont fait l’objet d’une revue statique ; **leur lancement natif dans Windows / Docker Desktop reste à vérifier sur votre PC**. L’état du cloud ne prouve pas que Docker, WSL 2, les ports ou les autorisations sont déjà configurés sur votre ordinateur personnel.
