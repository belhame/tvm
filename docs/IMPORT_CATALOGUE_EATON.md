# Importer le catalogue Eaton BN dans TVM

## Ce qui est importé

Le fichier original **`Product serial number Vers BN.xls`**, révision **BN du 30 novembre 2023**, fournit un catalogue de référence. Son import enregistre les données dans PostgreSQL avec leur version, leur empreinte SHA-256 et leur provenance dans le classeur. Il ne crée pas un parc d'onduleurs chez vos clients.

Les repères à contrôler pour le classeur fourni sont :

| Contrôle de référence | Valeur attendue |
|---|---:|
| Feuilles du classeur | 7 |
| Lignes produits de la feuille `Serial numbers` | 1 582 |
| Entrées de garantie de référence | 69 |
| Correspondances code/année, alias compris | 64 |
| Entrées `NA` conservées | 109 |
| Collisions au sein des profils, conservées | 5 |
| Codes présents dans plusieurs profils | 102 |

Ces valeurs décrivent le fichier de référence et le résultat attendu de son import. Elles ne prouvent pas qu'une installation donnée a déjà été mise à jour ou alimentée. Le compte rendu de validation est distinct : voir [VALIDATION.md](VALIDATION.md).

Les 1 582 lignes produits ne sont pas le total des sept feuilles : les correspondances d'années et les indications de garantie sont distinctes. Les quatre profils sont **Eaton**, **Pulsar**, **Powerware** et **NV DX**. Les documents incorporés et les schémas graphiques ne sont pas interprétés par l'importeur ; aucune table de correspondance des usines n'est créée.

Les entrées `NA` restent des références sans code utilisable. Elles ne sont pas supprimées ; les cinq collisions au sein d'un profil concernent des références différentes, qui restent elles aussi distinctes. Les 102 autres codes partagés entre profils ne doivent pas servir à les fusionner. Un code doit être lu dans son profil et avec sa provenance ; il ne suffit pas à identifier un modèle de façon universelle. Les correspondances d'années et les indications de garantie restent séparées des lignes de produits et des données de vos équipements.

## Importer sur votre installation Windows

Un import dans l'environnement cloud ne remplit pas la base Docker de votre PC. Ce sont deux instances PostgreSQL distinctes. Après la mise à jour, importer le fichier une fois dans **l'application ouverte sur votre PC**.

1. Arrêter TVM avec `ARRETER_TVM.cmd` et mettre à jour les sources dans le dossier déjà utilisé. **Conserver `.env`, `.local` et les données Docker.** Voir la [procédure de mise à jour Windows](INSTALLATION_WINDOWS.md#mettre-à-jour-lapplication-sans-perdre-la-configuration).
2. Relancer **`INSTALLER_TVM.cmd`** depuis ce même dossier. L'installation applique notamment les migrations nécessaires au catalogue ; elle ne remplace pas votre base par celle du cloud.
3. Se connecter avec un compte **administrateur** ou **responsable SAV**, puis ouvrir le menu **Catalogue Eaton**.
4. Sélectionner le fichier XLS original **`Product serial number Vers BN.xls`**, puis lancer l'import. Ne pas sélectionner le petit classeur `eaton structure.xlsx` ni une capture d'écran.
5. Attendre le résultat affiché. Sans filtre de recherche, contrôler le total attendu de **1 582 lignes**, la révision et les informations de version présentées par l'application.

Le classeur fourni se lit sans déchiffrement. Aucun mot de passe de protection n'est nécessaire pour cet import, et aucune clé de ce type n'est stockée dans TVM.

Si vous relancez l'import avec exactement le même fichier déjà actif, son empreinte SHA-256 permet de le reconnaître : aucune nouvelle copie des lignes ni nouvelle activation n'est effectuée. Réimporter un fichier connu correspondant à une ancienne version réactive cette version sans la dupliquer. Un fichier modifié est une autre version, même si son nom est identique.

Le fichier accepté par l'import doit respecter la limite de **8 Mio**. Le classeur original fourni, d'environ 3,8 Mo, reste sous cette limite.

## Droits et versions

| Compte | Accès au catalogue |
|---|---|
| Administrateur | Consultation et import |
| Responsable SAV | Consultation et import |
| Technicien | Consultation uniquement |
| Client | Aucun accès au catalogue ni à son import |

L'import prépare une version complète avant de l'activer de façon atomique. Un échec de lecture ou de validation ne doit pas remplacer partiellement la version active. La provenance de chaque ligne est conservée pour retrouver sa feuille et son emplacement dans le fichier source.

Le contrôle SHA-256 reconnaît le contenu du fichier ; il ne certifie pas son origine ni sa validité technique. Conserver le classeur reçu par le canal autorisé et vérifier sa révision avant de l'importer.

## Commande d'administration

L'import par l'interface est la méthode à privilégier sous Windows. Sur un serveur disposant de l'environnement Python local du projet, les commandes suivantes sont disponibles depuis la racine des sources, après installation et migrations :

```bash
set -a
source .env
set +a
.venv/bin/python backend/manage.py import_eaton_catalogue "/chemin/prive/Product serial number Vers BN.xls" --validate-only
```

La validation lit et contrôle le fichier sans écriture en base. Elle ne requiert pas de compte acteur. Pour importer et activer la version :

```bash
.venv/bin/python backend/manage.py import_eaton_catalogue "/chemin/prive/Product serial number Vers BN.xls" --actor admin
```

Remplacer `admin` par l'identifiant d'un compte **actif**, administrateur ou responsable SAV, déjà présent dans cette instance. L'acteur est obligatoire pour l'import effectif et permet d'attribuer l'opération au bon compte. Aucun mot de passe n'est passé en argument. Cette commande travaille uniquement sur la base désignée par la configuration chargée ; elle ne contacte pas les autres installations TVM.

## Différence avec l'aide de lecture des numéros de série

Le premier classeur `eaton structure.xlsx` contient neuf cellules décrivant un format de dix caractères. Il alimente une **aide consultative de découpage en cinq segments**, documentée dans [NUMEROS_SERIE_EATON.md](NUMEROS_SERIE_EATON.md).

Le catalogue BN est une source de référence plus riche, importée et consultable côté serveur. Son ajout ne transforme pas cette première aide en un décodeur universel des quatre profils. Le code d'un profil ne doit pas être appliqué silencieusement aux autres.

Ni l'import ni la consultation du catalogue ne modifient automatiquement le numéro de série, le modèle, la date de fabrication ou la garantie d'un équipement. Une correspondance de code ou une durée mentionnée dans le catalogue ne vaut pas une décision de prise en garantie d'un dossier SAV.

## Utiliser le catalogue pendant une nouvelle demande SAV

Un parcours distinct permet de saisir la série pendant une nouvelle demande, puis de rechercher le modèle et les informations de garantie côté serveur. La recherche ne crée rien. Lors de l'enregistrement explicite par un administrateur ou responsable, un nouvel équipement, sa demande et une garantie calculable peuvent être créés de façon atomique. Les fiches, garanties et contrats existants ne sont jamais écrasés par ce parcours.

Le début de garantie suit la règle TVM confirmée par l'utilisateur : **date de fabrication + six mois calendaires**. Il ne s'agit pas d'une réponse en direct d'Eaton. Une précision limitée au mois, un code d'année ambigu ou un modèle non identifié doit être signalé ; les données manuelles nécessitent une justification. Voir [le parcours demande à partir d'une série](PARCOURS_DEMANDE_SERIE.md) et [son contrat API](API_CONTRACT.md#demande-sav-à-partir-dune-série).

## Confidentialité et conservation

Le code source de l'importeur et de l'application peut être livré séparément. **Le fichier XLS fourni et les données privées du catalogue ne sont pas inclus dans les sources publiques, dans GitHub ou dans l'archive des sources.** Ils sont chargés dans la base de l'instance autorisée lors de l'import.

Conserver le fichier original dans un emplacement privé. Les sauvegardes PostgreSQL effectuées après l'import contiennent aussi les lignes du catalogue et doivent bénéficier de la même protection. Une capture d'écran, un journal ou un export partagé ne doit pas exposer le catalogue à des destinataires non autorisés.
