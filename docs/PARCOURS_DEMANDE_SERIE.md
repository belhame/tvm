# Créer une demande SAV à partir d'un numéro de série

## Principe

Le formulaire SAV simple est le parcours courant d'arrivée : client, numéro de série et livreur d'arrivée. Un employé choisit un livreur TVM ou un livreur actif de la société sélectionnée ; un livreur TVM créateur est enregistré lui-même. Il affiche les anciens passages et l'orientation de garantie. Une série inconnue n'oblige pas à inventer un modèle : **À identifier** reste explicite, et objet/description ne sont pas exigés. À la création, l'arrivée vient du serveur et la demande reste **Non affecté**. Un dossier déjà ouvert est proposé à la consultation, sans remise à zéro de son arrivée ou de son historique. Voir [la procédure simple et les résultats de garantie](GUIDE_SUIVI_SAV.md#enregistrer-une-arrivée-avec-le-formulaire-sav-simple).

L'administrateur et le responsable disposent des boutons **Saisie rapide** et **Options avancées**. Ce dernier conserve l'ancien formulaire pour retrouver ou préciser un modèle, sélectionner les références du catalogue et compléter les données manuelles justifiées. Les sections ci-dessous décrivent ce **formulaire avancé**, dont les droits et exigences restent distincts du formulaire simple. Sa recherche ne crée rien. Le bouton **Enregistrer** valide le dossier côté serveur. Pour un nouvel équipement, un administrateur ou responsable SAV peut créer l'équipement, la demande et, si les données nécessaires sont disponibles, la garantie dans une même transaction PostgreSQL. Le portail client n'a pas accès à cette recherche interne.

## Règle TVM confirmée pour le début de garantie

**Début de garantie = date de fabrication + six mois calendaires.**

Cette règle a été confirmée par l'utilisateur. Elle ne signifie pas « fabrication + 180 jours ». Lorsqu'un jour n'existe pas dans le mois d'arrivée, le calcul retient le dernier jour de ce mois. Par exemple, avec une date entièrement fictive de fabrication au **15 mars 2024**, le début calculé est le **15 septembre 2024**.

L'écran indique explicitement la base du calcul : **règle TVM, fabrication + 6 mois**. La durée de garantie est une donnée distincte, provenant d'une référence choisie ou d'une saisie manuelle justifiée. Le résultat n'est pas une vérification en direct auprès d'Eaton, ni une décision automatique de prise en charge.

## Utiliser le parcours avancé

1. Dans **Nouvelle demande SAV**, choisir **Options avancées**. Choisir un **Équipement concerné** déjà enregistré, ou saisir son **Numéro de série**.
2. Cliquer sur **Rechercher le modèle et la garantie**. Vérifier si le résultat provient de la base TVM ou du catalogue de l'instance.
3. Si l'équipement existe, conserver sa fiche et ses informations enregistrées. Si le catalogue présente plusieurs produits ou références de garantie, faire un choix explicite ; l'application ne prend pas arbitrairement la première ligne.
4. Pour un nouvel équipement, sélectionner le client et vérifier le modèle, la précision de la date de fabrication et la durée retenue. Un administrateur ou responsable peut compléter les données manuellement avec une raison explicite si la recherche ne suffit pas.
5. Renseigner l'objet, la description et la priorité de la demande, puis cliquer sur **Enregistrer**.

L'enregistrement recalcule la recherche et les règles côté serveur. Les valeurs affichées dans le navigateur ne suffisent pas à imposer une correspondance ou une garantie. Une validation refusée ne doit pas laisser un équipement ou une garantie créés sans la demande associée. Le parcours protège également contre la création de deux demandes lors du rejeu de la même soumission.

## Priorité aux données existantes

Un numéro de série déjà présent sert à rattacher la demande à l'équipement existant. Ses données, ses garanties et ses contrats restent prioritaires : ils ne sont pas remplacés par une suggestion du catalogue ou par une nouvelle saisie dans ce formulaire.

Les garanties sont comparées à portée identique : une garantie batterie ne devient pas une garantie électronique. Les anciennes dates globales restent utilisables pour une recherche globale, sans être attribuées à un composant précis. Si une seule période enregistrée compatible est active, une extension active peut être affichée à la place d'une période de base expirée ; les autres périodes restent visibles.

Le client indiqué doit correspondre à celui de l'équipement. La création d'une nouvelle garantie par ce parcours concerne uniquement un nouvel équipement, lorsque la date et la durée nécessaires ont été retenues. La mise à jour d'une garantie ou d'un contrat existant se traite dans sa fiche avec les droits appropriés, pas par une réécriture silencieuse pendant la création d'un SAV.

## Limites selon le profil

Les tables d'années sont propres à leur profil dans le catalogue. Une correspondance d'un profil ne doit pas être appliquée à un autre.

| Situation | Comportement attendu |
|---|---|
| Plusieurs produits partagent un code | Présenter les candidats et demander un choix ; ne pas dédupliquer ou choisir la première ligne |
| Plusieurs références de garantie sont possibles | Présenter les références et leur provenance ; ne pas imposer une durée arbitraire |
| Profil reconnu avec année et semaine ISO exploitables | Utiliser le lundi de la semaine ISO comme convention affichée ; ce n'est pas un jour réel de fabrication certifié |
| Profil Pulsar dont la semaine ISO est reconstruite | Afficher l'avertissement lié à cette reconstruction et la base du calcul |
| Profil NV avec une précision limitée au mois | Conserver cette précision ; ne pas inventer le premier jour du mois comme date de fabrication |
| Profil DX avec année sur deux chiffres | Signaler l'ambiguïté du siècle ; ne pas inventer un siècle ou une décennie |
| Profil Powerware sans code produit dans la série | Ne pas annoncer de modèle déduit de la série ; utiliser la fiche existante ou une saisie contrôlée |
| Numéro hors format reconnu ou référence absente | Autoriser un traitement manuel justifié pour les rôles autorisés ; ne pas présenter une donnée inventée comme résultat du catalogue |

Pour les profils dont l'année et la semaine ISO sont exploitables, le calcul retient explicitement le **lundi de cette semaine**. La date obtenue et les six mois calendaires qui lui sont ajoutés reposent sur cette convention ; ils ne certifient pas le jour réel de fabrication. Une reconstruction de date Pulsar fait l'objet d'un avertissement. Les références reconditionnées dont le format n'est pas établi n'ont pas de date automatique.

Une date fournie manuellement nécessite une justification. Un résultat limité au mois ou dont le cycle d'année est ambigu ne doit pas devenir une date exacte cachée dans le calcul de garantie.

## Préparer l'instance Windows

Mettre à jour les sources dans le dossier TVM utilisé en conservant `.env`, `.local` et les données Docker, puis relancer `INSTALLER_TVM.cmd`. Importer ensuite le catalogue dans le menu **Catalogue Eaton** si cette instance ne le contient pas : voir [la procédure d'import BN](IMPORT_CATALOGUE_EATON.md).

Les bases cloud et PC sont distinctes. Le chargement du catalogue ou la création d'un dossier dans le cloud n'alimente pas automatiquement votre installation Windows.

## Origine des règles et confidentialité

Les noms de procédures `getdate`, `getannee` et `testgarantie`, ainsi que les références `Garantie.Duree_DU` et `Garantie.Duree_AU`, ont été retrouvés dans les éléments WINDEV. Les corps des traitements au format binaire PCS ne sont pas lisibles : cela ne démontre pas une conversion du code WLangage. Le comportement web est reconstruit avec les données disponibles et la règle des six mois confirmée par l'utilisateur.

Les exemples publics doivent utiliser des séries et clients fictifs. Les captures utilisateur contenant de vrais clients, le catalogue privé et les dossiers métier ne sont pas ajoutés au dépôt ni à l'archive publique des sources.

Les deux opérations HTTP sont distinctes : recherche sans écriture via `POST /api/serial-lookup/`, puis enregistrement transactionnel via `POST /api/requests/intake/`. Les champs, rôles et erreurs sont décrits dans [le contrat API](API_CONTRACT.md#demande-sav-à-partir-dune-série).
