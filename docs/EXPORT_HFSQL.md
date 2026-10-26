# Export HFSQL à demander au développeur TVM

## Texte de demande prêt à transmettre

> Merci de fournir un **export cohérent et complet de la base TVM en production**, avec ses 25 tables, identifiants d’origine et relations. L’archive de projet disponible contient le schéma XML génération 46 mais pas les données clients/SAV complètes. L’export doit être réalisé depuis HFSQL avec un outil WINDEV compatible et les droits autorisés, sans modification de production.
>
> Livrer un dossier `export_tvm_<date>/` comprenant `manifest.json`, un fichier JSONL UTF‑8 par table, les pièces jointes extraites et leurs empreintes, le diagramme courant et dictionnaire de données, la liste des statuts/privilèges et les règles de gestion exportées en texte. Conserver les noms exacts des colonnes, leurs accents, les identifiants et les clés étrangères. Ne pas exporter de mots de passe ou secrets ; les comptes et la configuration de messagerie seront recréés.
>
> Merci d’ajouter les nombres de lignes, les maxima d’identifiants, les totaux de contrôle métier, les anomalies/doublons/orphelins et une table de correspondance validée entre chaque onduleur physique et son client/site, car `onduleurs` ne contient pas d’`IDClient` dans l’analyse fournie. Ne pas fusionner ou corriger silencieusement les anciennes données.

## 1. Conditions de capture

1. Identifier la base active : HFSQL Classic ou Client/Serveur, version WINDEV/HFSQL, nom logique de la base, génération d’analyse réellement déployée, format/encodage et fuseau métier. Fournir des métadonnées, **pas les identifiants de connexion**.
2. Réaliser la capture dans une fenêtre sans écriture ou avec le mécanisme de sauvegarde/lecture cohérente supporté par HFSQL. Noter début/fin, `snapshot_id` unique et éventuels filtres. Ne pas concaténer des exports pris à des dates différentes comme un même instantané.
3. Exporter tous les enregistrements métier de chacune des 25 tables, y compris tables vides. Indiquer séparément les enregistrements logiquement supprimés, états d’archivage et règles de visibilité ; ne pas ressusciter des données supprimées sans décision métier.
4. Fournir des contrôles de volumétrie depuis HFSQL à la même date : compte par table, minimum/maximum d’ID, nombre de valeurs NULL par colonne clé, doublons de clés, clés étrangères orphelines et dernier ID auto alloué si disponible.
5. Livrer par un canal sécurisé au responsable de la reprise. Le dossier contient des données personnelles et documents SAV ; il ne doit pas être commité dans Git, servi par le serveur web ni envoyé à un service d’IA.

## 2. Structure attendue

```text
export_tvm_2026-10-22/
  manifest.json
  tables/
    01_qualifications.jsonl
    02_client.jsonl
    03_onduleurs.jsonl
    ...
    25_snumber.jsonl
  attachments_manifest.jsonl     # inventaire auxiliaire des binaires
  attachments/                 # binaires extraits, jamais exécutés
  documentation/
    dictionnaire_et_types.csv
    liaisons.csv
    statuts_et_transitions.csv
    privileges_et_roles.csv
    affectations_equipements.csv
    correspondance_techniciens.csv
    regles_metier/               # WLangage/SQL exportés en texte lisible
    controles_source.json
    anomalies.csv
```

Le nom physique des fichiers peut rester ASCII ; le champ `name` du manifeste et les clés JSON conservent les noms WINDEV exacts. Chaque fichier indiqué par le manifeste est un chemin relatif situé dans le dossier d’export. Pas de lien symbolique, de chemin absolu, de `../`, de lien réseau ou de nom de fichier réutilisé pour deux tables.

### `manifest.json`

Contrat de base reconnu par la commande de validation/staging de l’application :

```json
{
  "schema_version": 1,
  "format": "tvm-hfsql-jsonl",
  "snapshot_id": "TVM-2026-10-22T170000-source46",
  "timezone": "Africa/Tunis",
  "tables": [
    {
      "name": "Client",
      "file": "tables/02_client.jsonl",
      "row_count": 1,
      "sha256": "EMPREINTE_SHA256_HEXADECIMALE_REELLE_64_CARACTERES"
    }
  ]
}
```

**Cet extrait est illustratif** : le manifeste réel doit lister les **25 tables** ci-dessous, et contenir les véritables empreintes SHA‑256 des octets de chaque fichier. `Africa/Tunis` est un exemple à remplacer par le fuseau métier confirmé ; il n’est pas déduit de l’adresse d’un client ni du fuseau du poste. Le SHA‑256 ne constitue pas une signature d’origine ; utiliser également un canal de livraison authentifié.

### Sérialisation JSONL

- UTF‑8, une ligne JSON complète par enregistrement, fin de ligne `\n`. Les retours à la ligne dans les mémos texte sont échappés à l’intérieur des chaînes JSON. Conserver accents, texte complet et longueurs réelles ; aucun tronquage pour adapter l’ancien champ à un nouveau formulaire.
- **Tous les IDs et clés étrangères 64 bits sont des chaînes décimales** (`"123456789012345678"`), jamais des nombres JavaScript ni des valeurs arrondies. Conserver la valeur et les zéros significatifs des références métier ; ne pas confondre un numéro d’appel avec un ID auto. Exporter les rubriques ID auto du schéma, **pas** le numéro physique d’enregistrement `HNumEnr`, ni une numérotation de lignes recréée lors de l’export.
- `null` signifie NULL. `""` reste une chaîne vide. Préserver les valeurs sentinelles source dans un relevé d’anomalies : une date HFSQL vide/`00000000` devient `null`, avec son original et sa justification dans ce relevé, pas une date actuelle inventée. Les IDs sentinelles `0` ou vides dans des références doivent être documentés et traités avant promotion ; ne pas les transformer en un client fictif.
- Dates pures : `YYYY-MM-DD`. Horodatages : ISO 8601 avec décalage explicite quand connu ; si l’historique n’a pas de fuseau, documenter l’hypothèse et conserver le texte source dans le relevé. Ne pas inventer d’heure pour une simple date.
- Booléens : `true`/`false` uniquement pour les champs réellement booléens. Les petits entiers/énumérations (`Statut_onduleur`, `livree_par`, `interne_site`, `Embalage`) gardent leur valeur source ; fournir séparément le dictionnaire des codes.
- Montants/mesures décimaux : chaînes décimales canoniques avec point, unité dans le dictionnaire ; aucun arrondi binaire imposé. Les durées en texte (`Duree`, `Durée_de_garantie`) gardent leur valeur brute et leur unité doit être précisée.
- Ne pas encoder de mémo binaire en Base64 dans les JSONL métier. Exporter les fichiers séparément, laisser la colonne binaire à `null` et fournir l’inventaire auxiliaire décrit plus bas.
- Exclure entièrement les champs contenant des secrets. La liste des colonnes volontairement omises et la raison apparaissent dans `documentation/controles_source.json`, sans leurs valeurs.

Exemple **entièrement fictif**, sans secret :

```json
{"IDClient":"123","Raison_sociale":"Client exemple","Responsable":"Contact exemple","Telephone":"","Adresse":"","Mail":"contact@example.invalid","Matricule_fiscale":""}
```

## 3. Tables et clés à préserver

La liste complète des 239 rubriques figure dans [ANALYSE_WINDEV.md](ANALYSE_WINDEV.md). Exporter toutes les colonnes du schéma, sauf secrets explicitement exclus et mémos binaires déportés. Une rubrique absente doit être déclarée dans le dictionnaire ; elle ne doit pas être silencieusement abandonnée.

| Table exacte | Identifiant auto source | Références ou rapprochements à conserver |
|---|---|---|
| `qualifications` | `IDqualifications` | `Titre` ; la qualification d’un collaborateur est du texte, pas une FK confirmée |
| `Client` | `IDClient` | Identité, contacts, matricule ; exclure `mot_de_passe` |
| `onduleurs` | `IDonduleurs` | `Numéro_de_serie`, `Modele`, garantie ; demander l’affectation au client séparément |
| `modèles_des_onduleurs` | `IDmodèles_des_onduleurs` | `Modele` ; rapprochement texte à valider |
| `collaborateurs` | `IDcollaborateurs` | Nom, qualification, `privilage`, `compteAdmin` ; exclure `mot_de_passe` |
| `Demande` | `IDDemande` | `IDClient`, `IDcollaborateurs`, séries, modèle, numéros d’appel et l’ensemble des champs d’intervention |
| `param` | `IDparam` | Entête/pied et compteurs `DM/BL/MS/PR/EH` ; `Logo` extrait séparément |
| `journal` | `IDjournal` | `IDDemande`, horodatage `Date`, utilisateur historique et description |
| `BL` | `IDBL` | `IDDemande`, numéros et références historiques |
| `item_bl` | `IDitem_bl` | `IDBL`, séries et nouvelle série |
| `joints` | `IDjoints` | `IDDemande`, date, libellé ; `piece` extrait séparément |
| `echange` | `IDechange` | `IDClient`, ancienne/nouvelle série, validation ; `fichier` extrait séparément |
| `miseenservice` | `IDmiseenservice` | `IDClient`, série, technicien historique ; `fichier` extrait séparément |
| `Preventif` | `IDPreventif` | `IDClient`, série, technicien historique ; `fichier` extrait séparément |
| `Garantie` | `IDGarantie` | `IDClient`, série, dates ; `fichier` extrait séparément |
| `Contrat` | `IDContrat` | `IDClient`, numéro, série, dates, visites ; vérifier la clé unique sur `IDClient` |
| `user` | `IDuser` | `IDClient`, `slogin`, `sActif` ; exclure `spassword` |
| `JM` | `IDjoints` | `IDmiseenservice` ; `piece` extrait séparément |
| `JP` | `IDjoints` | `IDPreventif` ; `piece` extrait séparément |
| `JG` | `IDjoints` | `IDGarantie` ; `piece` extrait séparément |
| `JC` | `IDjoints` | `IDContrat` ; `piece` extrait séparément |
| `JE` | `IDjoints` | `IDechange` ; `piece` extrait séparément |
| `param_notif` | `IDparam_notif` | `Etat`, modèle `Mail`, sans identifiants ni secrets insérés dans le texte |
| `param_mail` | `IDparam_mail` | **ID seul recommandé** ; reconfigurer SMTP côté nouveau serveur, ne jamais exporter `mot_de_passe` |
| `snumber` | `IDsnumber` | Catalogue fabricant : séries, gamme, référence, garantie et structure série |

Les identifiants sont **propres à chaque table** : `JM.IDjoints="12"` et `JG.IDjoints="12"` sont deux enregistrements distincts. De même, un même numéro peut exister dans `Demande` et `BL` sans être le même objet. La clé de conservation brute est donc `(table_source, id_source)`.

### Distinguer numéro TVM, numéro du centre client et visites

Le modèle cible distingue désormais :

- **N° d'intervention / appel TVM** : numéro métier du dossier, stocké dans `ServiceRequest.reference` et commun à ses visites ;
- **N° d'appel client** : référence du centre SAV qui confie la réparation, stockée dans `client_reference` ;
- **Réf. de visite** : référence secondaire propre à une fiche ou visite, liée au dossier par sa clé, sans fusionner les visites.

Dans l'export brut, conserver intégralement **`Demande.Numero_appel` et `Demande.Numero_appel_interne`**, ainsi que `IDDemande` et `IDClient`. Le développeur doit confirmer explicitement lequel des deux champs joue chaque rôle dans la base de production ; ne pas décider le mapping par le seul nom d'une colonne. Garder également les champs de numéros présents dans `BL` et `item_bl`, avec leurs clés de relation, pour contrôler la concordance des documents.

Toutes ces références restent des **chaînes exactes**, avec leurs zéros initiaux, lettres, barres obliques et tirets. Ne pas les convertir en nombres ni supprimer leur ponctuation. Un numéro de centre n'est pas unique globalement et ne permet pas d'identifier le client : le rattachement doit venir des clés et des correspondances validées. Ne jamais joindre deux dossiers de centres différents sur la seule égalité de ce numéro.

Fournir en complément `documentation/correspondance_numeros.csv` :

```text
source_table,source_id,source_client_id,tvm_number,client_reference,visit_reference,parent_request_source_id,validation_status,notes
```

Ce fichier documente les correspondances ; il ne remplace pas les colonnes brutes et n'est pas un format de promotion automatique accepté par la commande de staging. Signaler les numéros TVM historiques dupliqués, absents ou trop longs pour le nouveau champ, sans troncature ni renumérotation silencieuse.

Les nouvelles demandes web utilisent une numérotation serveur annuelle `YY-NNNNN`. Cette règle ne doit pas être appliquée rétroactivement aux références importées. Conserver les anciens numéros et IDs ; si plusieurs visites résultent d'une ancienne demande, préserver la relation un dossier → plusieurs visites au lieu de fusionner leurs données. Voir [la convention des deux numéros](GUIDE_SUIVI_SAV.md#identifier-un-dossier-avec-les-deux-numéros).

## 4. Pièces jointes et mémos

Extraire les colonnes suivantes avec l’API HFSQL/WINDEV supportée, jamais en découpant les `.mmo` à la main :

- `param.Logo` ;
- `joints.piece`, `JM.piece`, `JP.piece`, `JG.piece`, `JC.piece`, `JE.piece` ;
- `echange.fichier`, `miseenservice.fichier`, `Preventif.fichier`, `Garantie.fichier`, `Contrat.fichier`.

Chaque fichier extrait doit avoir une entrée dans `attachments_manifest.jsonl`, par exemple :

```json
{"table":"joints","legacy_id":"42","column":"piece","file":"attachments/joints/42_piece.pdf","original_name":"rapport-exemple.pdf","mime":"application/pdf","size_bytes":12345,"sha256":"EMPREINTE_SHA256_REELLE"}
```

Fournir l’empreinte et la taille **réelles**, le nom original s’il est connu, le type MIME constaté, le lien parent et un état explicite pour un mémo manquant/vide/endommagé. Ne pas attribuer un faux `.pdf` à un contenu dont le format n’est pas connu. Les droits de visibilité client devront être attribués lors de la promotion validée, pas déduits de l’extension. La commande de staging initiale ne promet pas l’import des binaires dans les documents web ; elle ne doit jamais exécuter ni servir ces fichiers.

## 5. Relations et correspondances à livrer

`documentation/liaisons.csv` doit contenir pour **chaque liaison courante**, y compris celles qui ne figurent pas dans les anciens historiques :

```text
constraint_name,parent_table,parent_columns,child_table,child_columns,parent_cardinality,child_cardinality,on_delete,on_update,enforced,nullable
```

Exiger l’export depuis l’éditeur d’analyse ou les métadonnées HFSQL, pas un diagramme redessiné de mémoire. Les douze liaisons historiquement attestées sont listées dans l’analyse ; les contraintes actuelles restent à confirmer.

Livrer également :

- `affectations_equipements.csv` : `IDonduleurs`, série source, `IDClient` validé, site, client final, début/fin d’affectation si connu, justification, valideur. Signaler les appareils partagés, revendus ou présents chez plusieurs clients.
- `correspondance_techniciens.csv` : table/ID de dossier, valeur texte `Technicien`, `IDcollaborateurs` proposé, niveau de certitude, validation. Ne pas fusionner les homonymes automatiquement.
- `statuts_et_transitions.csv` : objet, valeur exacte source, libellé, état cible web proposé, transitions, conditions, rôle, notification, clôture/réouverture. Inclure `Etat_depasser`, `Date_etat` et les codes entiers.
- `privileges_et_roles.csv` : collaborateur ou utilisateur source, rôle historique, droits effectifs, client de rattachement, actif/inactif, rôle web proposé. La reprise n’accorde jamais automatiquement le rôle administrateur à partir d’un texte ambigu.
- Documentation des unités de garantie, calcul des extensions, quotas de visites contrat, règles d’échange et numérotation des BL/demandes/rapports.
- Sources lisibles `.txt`/`.wl`/SQL des procédures projet, fenêtres métier, requêtes et états, exportées depuis WINDEV ; ajouter les dépendances et appels externes. Les fichiers binaires `.wdw/.WDR/.wdg/.wde` seuls ne suffisent pas à valider ces règles.

## 6. Reprise en deux étapes et commandes disponibles

La version initiale fournit une **validation puis une zone de staging**. Elle n’importe pas directement des lignes HFSQL dans les écrans métier. Cette séparation conserve l’original et empêche d’inventer les propriétaires d’équipements, les rôles et les FK manquantes.

Depuis la racine du projet, avec la base configurée selon le README et l’environnement Python installé :

```sh
set -a
. ./.env
set +a
.venv/bin/python backend/manage.py import_hfsql /chemin/securise/export_tvm_2026-10-22
```

Cette commande valide le manifeste et le contenu, sans écrire les données métier. Après examen du résultat :

```sh
.venv/bin/python backend/manage.py import_hfsql /chemin/securise/export_tvm_2026-10-22 --stage
```

Le staging stocke les enregistrements bruts avec identité source ; il **ne crée pas de clients, comptes, équipements, demandes ou rapports dans l’application**. Les anciens secrets doivent déjà avoir été exclus ; un export contenant des colonnes de mots de passe est refusé, même si leur valeur est `null` ou vide. La commande n’importe ni ne vérifie les fichiers binaires de `attachments/` à ce stade. Les mêmes IDs de tables différentes restent distincts.

La promotion vers le nouveau modèle est une étape suivante, après validation des correspondances sur un échantillon. Les nouvelles tables utilisent leur propre clé primaire serveur et un `legacy_id`/une provenance source conservée ; il n’y a pas de réutilisation silencieuse des auto-IDs Django. Si plusieurs tables historiques sont fusionnées dans une entité web, conserver aussi `legacy_table` ou une table de correspondance pour éviter les collisions. Une éventuelle vue normalisée `normalized/core.jsonl` pourra être convenue ultérieurement avec son mapping explicite ; elle n’est pas présentée comme un format accepté ni une commande disponible dans cette version.

### Recette de reprise avant production

1. Valider les empreintes, la présence des 25 tables, les IDs et les comptes source ; examiner chaque anomalie.
2. Charger le staging dans une base de recette, à accès restreint. Vérifier qu’un second chargement du même instantané ne duplique ni n’écrase silencieusement un contenu différent.
3. Valider les correspondances client/appareil/technicien et les règles de statuts avec le responsable SAV sur des dossiers représentatifs : ouvert, clos, garantie, contrat, échange, BL multiligne et pièces jointes.
4. Construire la promotion transactionnelle et réversible ; comparer les nombres source/staging/métier, les relations et un échantillon de PDF. Conserver toute valeur historique non représentée dans le nouveau schéma et le journal du mapping.
5. Créer les comptes avec nouveaux mots de passe, appliquer l’appartenance client, puis tester deux clients sans accès réciproque, y compris par URL/ID direct, recherche, export et PDF.
6. Sauvegarder et tester la restauration de la base serveur et des documents avant le basculement. Figer la dernière capture et conserver l’ancien logiciel en consultation selon la politique de conservation.

La réception d’un export ne vaut pas une reprise terminée. Les rapprochements ambigus et les règles historiques non exportées empêchent une promotion fiable ; ils seront signalés au lieu d’être résolus par des suppositions.
