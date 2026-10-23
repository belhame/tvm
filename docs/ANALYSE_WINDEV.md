# Analyse du projet WINDEV TVM

Analyse effectuée le 22 octobre 2026 sur l’archive `TVM_2026-10-22.zip` fournie dans cette conversation. Le nom réel du fichier reçu diffère du nom `TVM_2026-10-22(1).zip` mentionné dans la demande ; aucun second fichier n’a été supposé. L’archive a pu être déchiffrée. Son contenu a été traité comme données : aucun exécutable Windows n’a été lancé.

## Résultat et limites

- **Schéma récupéré : 25 tables, 239 rubriques**, dans `TVM.xdd`, analyse génération 46, structure XML version 2. Les deux copies `TVM.xdd` et `TVM.ana/TVM.xdd` sont identiques (SHA‑256 `a0e2f701bf4c06c9f2c8820521060f9d08926a679aa80155804cdd5c1b9060f4`).
- L’archive contient **1 089 entrées**, environ 22,7 Mo décompressés. Au niveau principal : 41 fenêtres `FEN*.wdw`, 62 requêtes `.WDR` et 12 états `ETAT*.wde`. Des gabarits, sauvegardes et caches sont aussi présents : ils ne représentent pas des modules supplémentaires.
- **Code WLangage non converti.** Les fenêtres, requêtes, états, projet `.wdp` et collection `.wdg` portent une signature binaire `PCS`. L’extraction texte courante ne fournit pas de fonctions WLangage ou de SQL complets et exploitables. Les noms des fichiers renseignent sur les écrans prévus, pas sur leurs règles d’exécution. Une ouverture dans la version compatible de WINDEV et un export du code restent nécessaires.
- Le XML décrit les rubriques, types, tailles et clés. Il **ne contient pas les objets de liaison**, ni les règles de suppression, de mise à jour ou les cardinalités. Douze créations de liaisons sont attestées dans les historiques texte de génération, sans certifier les contraintes actuellement actives.
- Les **données SAV complètes ne sont pas fournies**. Le seul fichier HFSQL métier directement identifié est `Exe/ser/snumber.fic` et son index : c’est un catalogue de numéros de série. Les autres `.FIC` (`RADFic`, `RADRub`, `RADProp`, variantes) sont des métadonnées RAD ; ils ne remplacent pas les données `Client`, `Demande`, etc. Un fichier `.fic` binaire n’a pas été interprété comme un export CSV.
- Les noms de colonnes contenant des mots de passe sont documentés ci-dessous pour l’exhaustivité du schéma. **Aucune valeur de mot de passe ni autre donnée personnelle de l’archive n’a été copiée dans le code, les exemples ou cette documentation.** Les comptes web nécessitent de nouveaux mots de passe ; aucun mécanisme d’authentification historique n’est supposé compatible.

## Fonctions repérées et récupération possible

| Domaine | Preuve dans le projet | Ce qui est récupérable | Ce qui reste à reconstruire ou valider |
|---|---|---|---|
| Clients | `FEN_Fiche_client`, `FEN_List_client`, `Client` | Identité, contact, adresse, matricule fiscal et ID | Unicité, clients finaux, sites, contacts multiples, habilitations portail |
| Onduleurs / catalogue | `FEN_Fiche_onduleur`, `FEN_list_onduleur`, `FEN_import_eaton`, tables `onduleurs`, `modèles_des_onduleurs`, `snumber` | Séries, modèles, dates et durée de garantie, catalogue fabricant | Affectation à un client (pas d’`IDClient` dans `onduleurs`), doublons de série, historique des propriétaires, unité de durée |
| Demandes / intervention | `FEN_Demande`, `FEN_suivi`, `Demande`, `journal` | Fiche SAV, client, collaborateur, panne, observations, opération, conclusion, dates | Automate des statuts, clôture, priorités, droits d’édition, délais, numérotation, modalités atelier/site |
| Mise en service / préventif | `FEN_miseneservice`, `FEN_preventif`, `miseenservice`, `Preventif` | Documents, technicien, visite, synthèse, client final | Périodicité, planification, validation des visites et critères des essais |
| Contrats / garanties | `FEN_Contrat`, `FEN_garantie`, `Contrat`, `Garantie` | Périodes, numéro, visites, synthèse, documents | Portée exacte, exclusions, renouvellement, extension, calcul de prise en charge |
| Échanges | `FEN_echange`, `echange`, `Demande.Nouveau_SN` | Ancienne/nouvelle série, validation, document | Effet de l’échange sur la propriété, garantie et historique, approbateurs |
| Bons de livraison | `FEN_bl`, `FEN_fiche_bl`, `BL`, `item_bl`, `ETAT_BL2` | En-têtes, lignes, série réparée ou remplacée, lien vers demande | Numérotation, signature, caractère définitif, mise à jour de statut, fiscalité |
| Rapports | 12 états `ETAT_*.wde` dont intervention, contrat, garantie, préventif et ticket | Existence et catégories des documents | Mise en page et champs exacts, conditions d’impression, mentions, signatures. Les nouveaux PDF ne sont pas des reproductions certifiées des états binaires |
| Pièces jointes | `joints`, `JM`, `JP`, `JG`, `JC`, `JE` et champs `fichier` | Date, libellé et binaire relié à un dossier | Extraction mémo, nom/MIME, visibilité client, droits de téléchargement |
| Comptes | `collaborateurs`, `user`, `Client`, écrans utilisateur/menu client | Identifiants historiques et appartenance client pour `user` | Recréation sécurisée des comptes, conversion explicite des privilèges, aucune reprise des anciens mots de passe |
| Notifications | `FEN_mail_param`, `FEN_param_notif`, `param_mail`, `param_notif` | Présence d’une configuration SMTP et de messages selon état | Déclencheurs, modèles et consentements. Aucun support WhatsApp confirmé par le schéma |
| Pièces détachées / stock | Aucun référentiel ni mouvement de stock identifiable dans les 25 tables | Rien de certifié | Nouveau catalogue de pièces, seuils, entrées/sorties, réservation, consommation sur intervention |
| Planning / scan / IA | Pas de table dédiée identifiable | Séries et dates existantes utilisables comme données | Nouvelles fonctions web et mobiles ; moteur IA et WhatsApp soumis à accès et règles de confidentialité |

**Attention au vocabulaire** : `joints.piece` et les champs `piece` de `JM/JP/JG/JC/JE` sont des mémos binaires, donc des **pièces jointes documentaires**, et ne constituent pas un inventaire de pièces détachées.

## Relations et risques de reprise

Les historiques de `TVM.ana/LASTGEN` attestent les liaisons suivantes :

| Parent | Enfant | Colonnes | Preuve historique |
|---|---|---|---|
| Client | Demande | IDClient | MO002-003.TXT |
| collaborateurs | Demande | IDcollaborateurs | MO002-003.TXT |
| Demande | journal | IDDemande | MO010-011.TXT |
| Demande | BL | IDDemande | MO011-012.TXT |
| BL | item_bl | IDBL | MO012-013.TXT |
| Demande | joints | IDDemande | MO014-015.TXT |
| Client | user | IDClient | MO035-036.TXT |
| miseenservice | JM | IDmiseenservice | MO039-040.TXT |
| Preventif | JP | IDPreventif | MO039-040.TXT |
| Garantie | JG | IDGarantie | MO039-040.TXT |
| Contrat | JC | IDContrat | MO039-040.TXT |
| echange | JE | IDechange | MO039-040.TXT |

`IDClient` existe également dans `echange`, `miseenservice`, `Preventif`, `Garantie` et `Contrat` ; leur ajout apparaît en génération 40→41. Le rattachement à `Client.IDClient` est très plausible, mais la liaison actuelle et sa cardinalité doivent être exportées et validées.

Points à résoudre avant une reprise réelle :

1. **Absence de propriétaire sur l’onduleur** : `onduleurs` ne contient pas d’`IDClient`. Retrouver un équipement à partir de `Demande.Onduleur`, `SN`, `Nserie`, `Num_serie` nécessite une table d’affectation validée ; ne pas attribuer automatiquement un appareil au premier client rencontré.
2. **Séries non certifiées uniques** : `onduleurs.Numéro_de_serie` n’est pas une clé dans cet XML ; `snumber.Serialnumber` et `Demande.Onduleur` sont des clés avec doublons autorisés. Distinguer les séries physiques, séries de référence catalogue et remplacements.
3. **`Contrat.IDClient` marqué clé unique** : contrairement aux autres `IDClient` indexés avec doublons. Cela peut refléter une restriction historique ou une erreur d’analyse ; ne pas en déduire une clé primaire composite ni imposer un seul contrat par client sans validation.
4. **Techniciens libres** : plusieurs tables stockent `Technicien` en texte, sans ID collaborateur. Demander une table de correspondance plutôt que fusionner automatiquement des homonymes.
5. **Champs dénormalisés** : `Client`, `Model`/`Modele`, `Onduleur`, adresse et numéros d’appel sont parfois répétés à côté des IDs. Conserver les valeurs historiques comme instantanés et enregistrer les écarts.
6. **Intervention incluse dans la demande** : il n’existe pas de table `Intervention` indépendante dans ce schéma. La séparation web demande/interventions est un nouveau modèle ; les règles pour convertir une ancienne demande en une ou plusieurs interventions doivent être approuvées sur échantillon.
7. **Dates seules / textes de garantie** : les colonnes date ne prouvent pas un horaire, fuseau ou rendez-vous. `Durée_de_garantie`, `Duree` et certains indicateurs sont des textes/octets : leurs unités et valeurs doivent être documentées.
8. **Statuts, délais, compteurs, accès** : les libellés possibles, transitions, délais `Etat_depasser`/`Date_etat`, compteurs `param.DM/BL/MS/PR/EH` et `privilage` ne sont pas reconstruisibles avec certitude depuis les noms des rubriques.

## Dictionnaire des 25 tables

Les noms et accents ci-dessous sont repris de l’XML, **y compris les fautes historiques** (`Debur_garantie`, `debut_contart`, `Répatation`, `privilage`, etc.). Aucun renommage silencieux n’est appliqué au contrat d’export.

Légende des codes observés : `2` texte ; `5` entier sur 4 octets ; `14` date ; `24` identifiant automatique sur 8 octets ; `25` entier sur 8 octets ; `29` mémo texte ; `30` mémo binaire ; `36` entier sur 1 octet ; `37` booléen. Le code `34` est conservé brut ci-dessous : son interprétation doit être confirmée par l’éditeur d’analyse. `TYPE_CLE=0` : sans clé ; `1` : clé unique ; `2` : clé avec doublons. Les types et contraintes définitifs doivent être confirmés dans l’export WINDEV officiel. Pour les mémos, `TAILLE=8` est un descripteur interne et **pas** une limite de contenu de huit octets.

### 1. `qualifications` — 2 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDqualifications` | 24 / ID auto 8 octets | 8 | unique |
| `Titre` | 2 / texte | 50 | — |

### 2. `Client` — 8 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDClient` | 24 / ID auto 8 octets | 8 | unique |
| `Raison_sociale` | 2 / texte | 50 | — |
| `Responsable` | 2 / texte | 50 | — |
| `Telephone` | 2 / texte | 50 | — |
| `Adresse` | 2 / texte | 100 | — |
| `Mail` | 2 / texte | 50 | — |
| `mot_de_passe` | 2 / texte | 50 | — |
| `Matricule_fiscale` | 2 / texte | 50 | — |

### 3. `onduleurs` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDonduleurs` | 24 / ID auto 8 octets | 8 | unique |
| `Numéro_de_serie` | 2 / texte | 50 | — |
| `Modele` | 2 / texte | 50 | — |
| `Durée_de_garantie` | 2 / texte | 50 | — |
| `Début_du_garantie` | 14 / date | 8 | — |

### 4. `modèles_des_onduleurs` — 2 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDmodèles_des_onduleurs` | 24 / ID auto 8 octets | 8 | unique |
| `Modele` | 2 / texte | 50 | — |

### 5. `collaborateurs` — 8 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDcollaborateurs` | 24 / ID auto 8 octets | 8 | unique |
| `Nom_Prenom` | 2 / texte | 50 | — |
| `Qualification` | 2 / texte | 50 | — |
| `Telephone` | 2 / texte | 50 | — |
| `Mail` | 2 / texte | 50 | — |
| `mot_de_passe` | 2 / texte | 50 | — |
| `privilage` | 2 / texte | 100 | — |
| `compteAdmin` | 37 / booléen | 1 | — |

### 6. `Demande` — 42 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDDemande` | 24 / ID auto 8 octets | 8 | unique |
| `Numero_appel` | 2 / texte | 50 | — |
| `Numero_appel_interne` | 2 / texte | 50 | — |
| `Date_arrivee` | 14 / date | 8 | — |
| `Client` | 2 / texte | 50 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `Onduleur` | 2 / texte | 50 | doublons |
| `Model` | 2 / texte | 50 | — |
| `Debur_garantie` | 14 / date | 8 | — |
| `Duree` | 2 / texte | 50 | — |
| `Statut_onduleur` | 36 / entier 1 octet | 1 | — |
| `Description_panne` | 29 / mémo texte | 8 | — |
| `livree_par` | 36 / entier 1 octet | 1 | — |
| `Livreur` | 2 / texte | 50 | — |
| `Prise_en_charge` | 2 / texte | 50 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |
| `IDcollaborateurs` | 25 / entier 8 octets | 8 | doublons |
| `interne_site` | 36 / entier 1 octet | 1 | — |
| `Embalage` | 36 / entier 1 octet | 1 | — |
| `Demande_retour` | 37 / booléen | 1 | — |
| `Etat` | 2 / texte | 50 | doublons |
| `Observation` | 29 / mémo texte | 8 | — |
| `Operation` | 2 / texte | 50 | — |
| `typeintervention` | 2 / texte | 50 | — |
| `Conclusion` | 2 / texte | 50 | — |
| `travaux` | 2 / texte | 50 | — |
| `Miseenservice` | 2 / texte | 50 | — |
| `ContratN` | 2 / texte | 50 | — |
| `debut_contart` | 14 / date | 8 | — |
| `Fin_contrat` | 14 / date | 8 | — |
| `debut_extension` | 14 / date | 8 | — |
| `Fin_extension` | 14 / date | 8 | — |
| `Nbre_bAT` | 2 / texte | 50 | — |
| `Armoire_SN` | 2 / texte | 50 | — |
| `Nouveau_SN` | 2 / texte | 50 | doublons |
| `Ville` | 2 / texte | 50 | — |
| `Personne` | 2 / texte | 50 | — |
| `Accessoir` | 2 / texte | 50 | — |
| `Clientfinal` | 2 / texte | 50 | — |
| `Date_traitement` | 14 / date | 8 | — |
| `Etat_depasser` | 37 / booléen | 1 | — |
| `Date_etat` | 14 / date | 8 | — |

### 7. `param` — 11 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDparam` | 24 / ID auto 8 octets | 8 | unique |
| `entete` | 29 / mémo texte | 8 | — |
| `pied` | 29 / mémo texte | 8 | — |
| `Logo` | 30 / mémo binaire | 8 | — |
| `activelogo` | 37 / booléen | 1 | — |
| `DM` | 2 / texte | 50 | — |
| `BL` | 2 / texte | 50 | — |
| `Hauteur` | 5 / entier 4 octets | 4 | — |
| `MS` | 2 / texte | 50 | — |
| `PR` | 2 / texte | 50 | — |
| `EH` | 2 / texte | 50 | — |

### 8. `journal` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjournal` | 24 / ID auto 8 octets | 8 | unique |
| `Date` | 34 / code 34 — à confirmer | 8 | — |
| `Description` | 29 / mémo texte | 8 | — |
| `User` | 2 / texte | 50 | — |
| `IDDemande` | 25 / entier 8 octets | 8 | doublons |

### 9. `BL` — 14 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDBL` | 24 / ID auto 8 octets | 8 | unique |
| `Date` | 14 / date | 8 | — |
| `NUM` | 2 / texte | 50 | — |
| `Client` | 2 / texte | 50 | — |
| `Adresse` | 2 / texte | 100 | — |
| `TVA` | 2 / texte | 50 | — |
| `Numero_appel` | 2 / texte | 50 | — |
| `numero_interne` | 2 / texte | 50 | — |
| `Reference` | 2 / texte | 50 | — |
| `Num_serie` | 2 / texte | 50 | — |
| `Répatation` | 29 / mémo texte | 8 | — |
| `commentaire` | 29 / mémo texte | 8 | — |
| `IDDemande` | 25 / entier 8 octets | 8 | doublons |
| `Etat` | 2 / texte | 50 | doublons |

### 10. `item_bl` — 9 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDitem_bl` | 24 / ID auto 8 octets | 8 | unique |
| `NUM_appel` | 2 / texte | 50 | — |
| `Num_interne` | 2 / texte | 50 | — |
| `Reference` | 2 / texte | 50 | — |
| `Num_serie` | 2 / texte | 50 | — |
| `Reparation` | 29 / mémo texte | 8 | — |
| `IDBL` | 25 / entier 8 octets | 8 | doublons |
| `Nouveau_SN` | 2 / texte | 50 | — |
| `Etat` | 2 / texte | 50 | doublons |

### 11. `joints` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `IDDemande` | 25 / entier 8 octets | 8 | doublons |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |

### 12. `echange` — 14 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDechange` | 24 / ID auto 8 octets | 8 | unique |
| `Date` | 14 / date | 8 | — |
| `NUM_appel` | 2 / texte | 50 | — |
| `Validation` | 37 / booléen | 1 | — |
| `Date_validation` | 14 / date | 8 | — |
| `Nserie` | 2 / texte | 50 | — |
| `Etat` | 2 / texte | 50 | doublons |
| `Ancien_SN` | 2 / texte | 50 | — |
| `Model` | 2 / texte | 50 | — |
| `Client` | 2 / texte | 50 | — |
| `fichier` | 30 / mémo binaire | 8 | — |
| `nomfichier` | 2 / texte | 100 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |

### 13. `miseenservice` — 18 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDmiseenservice` | 24 / ID auto 8 octets | 8 | unique |
| `NUM_appel` | 2 / texte | 50 | — |
| `Client` | 2 / texte | 50 | — |
| `Client_final` | 2 / texte | 50 | — |
| `Date` | 14 / date | 8 | — |
| `Lieu` | 2 / texte | 50 | — |
| `SN` | 2 / texte | 50 | — |
| `Model` | 2 / texte | 50 | — |
| `Technicien` | 2 / texte | 50 | — |
| `synthese` | 29 / mémo texte | 8 | — |
| `Contact` | 2 / texte | 50 | — |
| `Armoire_SN` | 2 / texte | 50 | — |
| `Etat` | 2 / texte | 50 | doublons |
| `fichier` | 30 / mémo binaire | 8 | — |
| `Tel` | 2 / texte | 50 | — |
| `nomfichier` | 2 / texte | 100 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |

### 14. `Preventif` — 15 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDPreventif` | 24 / ID auto 8 octets | 8 | unique |
| `NUM_appel` | 2 / texte | 50 | — |
| `Client` | 2 / texte | 50 | — |
| `Date` | 14 / date | 8 | — |
| `Onduleur` | 2 / texte | 50 | — |
| `NBR_Visite` | 5 / entier 4 octets | 4 | — |
| `Technicien` | 2 / texte | 50 | — |
| `Etat` | 2 / texte | 50 | doublons |
| `Client_final` | 2 / texte | 50 | — |
| `synthese` | 29 / mémo texte | 8 | — |
| `Model` | 2 / texte | 50 | — |
| `fichier` | 30 / mémo binaire | 8 | — |
| `nomfichier` | 2 / texte | 100 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |

### 15. `Garantie` — 13 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDGarantie` | 24 / ID auto 8 octets | 8 | unique |
| `Client` | 2 / texte | 50 | — |
| `Client_final` | 2 / texte | 50 | — |
| `Onduleur` | 2 / texte | 50 | — |
| `Modele` | 2 / texte | 50 | — |
| `Duree_DU` | 14 / date | 8 | — |
| `Duree_AU` | 14 / date | 8 | — |
| `synthese` | 29 / mémo texte | 8 | — |
| `fichier` | 30 / mémo binaire | 8 | — |
| `nomfichier` | 2 / texte | 100 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |
| `Technicien` | 2 / texte | 50 | — |

### 16. `Contrat` — 16 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDContrat` | 24 / ID auto 8 octets | 8 | unique |
| `Num_Contrat` | 2 / texte | 50 | — |
| `Client` | 2 / texte | 50 | — |
| `Onduleur` | 2 / texte | 50 | — |
| `Modele` | 2 / texte | 50 | — |
| `Duree_AU` | 14 / date | 8 | — |
| `Duree_DU` | 14 / date | 8 | — |
| `preventif_Visite` | 5 / entier 4 octets | 4 | — |
| `Curatif_Visite` | 5 / entier 4 octets | 4 | — |
| `synthese` | 29 / mémo texte | 8 | — |
| `Client_final` | 2 / texte | 50 | — |
| `fichier` | 30 / mémo binaire | 8 | — |
| `nomfichier` | 2 / texte | 100 | — |
| `Date_cloture` | 14 / date | 8 | — |
| `IDClient` | 25 / entier 8 octets | 8 | unique |
| `Technicien` | 2 / texte | 50 | — |

### 17. `user` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDuser` | 24 / ID auto 8 octets | 8 | unique |
| `slogin` | 2 / texte | 50 | — |
| `spassword` | 2 / texte | 50 | — |
| `sActif` | 37 / booléen | 1 | — |
| `IDClient` | 25 / entier 8 octets | 8 | doublons |

### 18. `JM` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |
| `IDmiseenservice` | 25 / entier 8 octets | 8 | doublons |

### 19. `JP` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |
| `IDPreventif` | 25 / entier 8 octets | 8 | doublons |

### 20. `JG` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |
| `IDGarantie` | 25 / entier 8 octets | 8 | doublons |

### 21. `JC` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |
| `IDContrat` | 25 / entier 8 octets | 8 | doublons |

### 22. `JE` — 5 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDjoints` | 24 / ID auto 8 octets | 8 | unique |
| `piece` | 30 / mémo binaire | 8 | — |
| `Date` | 14 / date | 8 | — |
| `Libelle` | 2 / texte | 50 | — |
| `IDechange` | 25 / entier 8 octets | 8 | doublons |

### 23. `param_notif` — 3 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDparam_notif` | 24 / ID auto 8 octets | 8 | unique |
| `Etat` | 2 / texte | 50 | doublons |
| `Mail` | 29 / mémo texte | 8 | — |

### 24. `param_mail` — 7 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDparam_mail` | 24 / ID auto 8 octets | 8 | unique |
| `Serveur_Smtp` | 2 / texte | 50 | — |
| `port` | 2 / texte | 50 | — |
| `SSL` | 37 / booléen | 1 | — |
| `email` | 2 / texte | 50 | — |
| `Login` | 2 / texte | 50 | — |
| `mot_de_passe` | 2 / texte | 50 | — |

### 25. `snumber` — 12 rubriques

| Rubrique | Type brut / lecture | Taille XML | Clé |
|---|---|---:|---|
| `IDsnumber` | 24 / ID auto 8 octets | 8 | unique |
| `Serialnumber` | 2 / texte | 50 | doublons |
| `Range` | 2 / texte | 100 | — |
| `Productname` | 2 / texte | 100 | — |
| `Yearoflaunching` | 5 / entier 4 octets | 4 | — |
| `Industrialpartnumber` | 2 / texte | 100 | — |
| `Cataloguenumber` | 2 / texte | 100 | — |
| `Warranty` | 5 / entier 4 octets | 4 | — |
| `Notes` | 2 / texte | 200 | — |
| `Version` | 2 / texte | 50 | — |
| `Return_` | 2 / texte | 50 | — |
| `Serial_structure` | 2 / texte | 50 | — |

## Règles à faire valider avec le développeur TVM

- Diagramme courant des liaisons et cascades, y compris droits liés au client final et aux groupes de clients.
- Liste complète des états, transitions autorisées, conditions de clôture/réouverture et déclencheurs de notification.
- Identification fiable de chaque appareil et de son propriétaire, règles des doublons et des échanges.
- Garantie constructeur, extension, contrat, prise en charge et décompte des visites.
- Séquences de numérotation, année/remise à zéro, formats des documents et valeur juridique des signatures.
- Planning : horaires, affectations, absences, priorité et éventuels SLA.
- Calculs électriques et protocole de mesure : unités, tolérances, test batterie, critères de remise en service. Un nouveau logiciel ne doit pas inventer de diagnostic de sécurité.
- Visibilité des observations, coûts et pièces jointes pour le portail client.
- Rôles `privilage`, `compteAdmin`, `user.sActif` et règles réellement appliquées dans le code.

Le fichier [EXPORT_HFSQL.md](EXPORT_HFSQL.md) fournit la demande d’export précise. Les nouveaux modules web doivent être évalués comme une réimplémentation documentée ; aucune équivalence complète au logiciel historique n’est revendiquée.
