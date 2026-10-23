# Fonctionnalités, périmètre et suites

## Ce que livre cette étape

Cette version fournit une application serveur et son code source, avec des comptes authentifiés, une base PostgreSQL partagée et un premier parcours SAV complet. Les données fictives sont optionnelles et explicitement signalées. Les listes, graphiques et documents affichent les données de la base accessible au compte connecté.

| Domaine | Comportement de cette version | Limite à connaître |
|---|---|---|
| Comptes | Administrateur, responsable SAV, technicien et client ; sessions serveur ; gestion des comptes par l'administrateur | Pas de SSO ni d'authentification multifacteur fournis |
| Portail client | Lecture des équipements, demandes, interventions et documents autorisés de sa société | Portail en lecture seule ; pas de création publique de compte |
| Clients | Fiches clients, contacts et coordonnées | Pas de synchronisation CRM externe |
| Onduleurs | Affectation client, modèle, marque, puissance, site et numéro de série unique | Le rattachement des anciens onduleurs HFSQL doit être confirmé |
| Demandes SAV | Dossier lié à un équipement, description, priorité et état | Les significations exactes des anciens états WINDEV restent à valider |
| Interventions | Affectation, date, durée, diagnostic, travaux, recommandations et état | Pas d'optimisation automatique des tournées |
| Planning | Vue des interventions datées enregistrées sur le serveur | Pas de synchronisation Outlook/Google Calendar |
| Rapports | Téléchargement PDF par intervention, soumis aux mêmes droits que le dossier | Pas de signature électronique, d'envoi automatique ni d'historique PDF immuable |
| Contrats | Fiche de contrat liée au client et éventuellement à un équipement, dates et couverture | Pas de facturation ni de génération automatique d'échéanciers |
| Garanties | Périodes et conditions par équipement | La décision de prise en charge et les règles WINDEV ne sont pas converties automatiquement |
| Pièces et stock | Catalogue, seuils et mouvements d'entrée/sortie ; contrôle du stock négatif ; rattachement possible à une intervention | Module nouveau : aucune table de stock n'a été identifiée avec certitude dans l'archive WINDEV |
| Bons de livraison | Fiche de livraison, lignes, client et rattachement éventuel à une intervention | Pas de PDF de BL dans cette étape ; un BL ne débite pas implicitement le stock, enregistrer le mouvement une seule fois |
| Tableau de bord | Compteurs, interventions récentes, activité et répartition des états issus de la base | Pas de statistiques historiques importées avant reprise des données |
| Recherche | Recherche de clients, dossiers, interventions et séries selon les droits du compte | Aucun accès implicite à une autre société via une recherche |
| Traçabilité | Journal des opérations accessible aux administrateurs / responsables via `/api/audit/` | Consultation via l'API ; pas de vue dédiée dans cette étape |

Les droits sont appliqués dans l'API. Masquer une rubrique du menu ne constitue pas à lui seul un contrôle d'accès. Les rapports et recherches doivent rester dans le périmètre autorisé ; les notes internes n'ont pas vocation à être exposées au client.

## Rôles

| Rôle | Autorisations métier |
|---|---|
| Administrateur | Création et modification des données métier ; gestion des comptes et de leurs rôles |
| Responsable SAV | Création et modification des données métier, affectation et suivi ; consultation de la traçabilité ; aucune gestion des comptes |
| Technicien | Lecture des données métier internes ; création de demandes ; création d'interventions affectées à lui-même et modification de ses interventions ; consommation de pièces pour ses interventions |
| Client | Lecture seule des ressources de sa société ; aucun accès au stock, aux comptes, à la traçabilité ou aux intégrations |

Le technicien ne supprime pas de dossier et ne modifie pas les fiches clients, équipements, contrats, garanties, pièces ou bons de livraison. Les droits du portail sont liés à la société du compte, non à un simple filtre choisi dans l'interface.

## Scan sur téléphone

Le scanner utilise la caméra du navigateur et l'API `BarcodeDetector` lorsqu'elle est disponible. Il lit un code-barres ou QR code contenant le numéro, puis effectue une recherche réelle côté serveur. La vidéo reste sur l'appareil ; elle n'est pas envoyée pour reconnaissance.

La caméra requiert un contexte sécurisé : HTTPS en déploiement, ou l'exception locale du navigateur pour `localhost`. Le navigateur doit accepter l'accès caméra et supporter les formats de code concernés. La saisie manuelle du numéro de série reste disponible si le navigateur ou la caméra ne convient pas. La compatibilité d'un téléphone précis se valide avec une vraie étiquette de l'entreprise.

## Intégrations à connecter

| Intégration | État livré | Éléments requis avant activation |
|---|---|---|
| WhatsApp | Écran d'état et besoins d'intégration ; aucun message envoyé | Compte WhatsApp Business / Meta, numéro validé, accès serveur, modèles approuvés, webhooks et consentement des destinataires |
| Assistant IA | Écran d'état ; aucun diagnostic ni réponse simulés | Fournisseur et modèle retenus, accès API côté serveur, règles de confidentialité, filtrage des dossiers avant chaque requête et validation des réponses |

Fournir une clé ne suffit pas à déclarer une intégration opérationnelle : les adaptateurs, les contrôles d'accès, les erreurs, la réception des événements et les essais réels doivent être réalisés. Aucun secret fournisseur n'est demandé dans un formulaire navigateur ou enregistré dans les sources.

## Ce qui est récupéré du projet WINDEV

Le fichier d'analyse fournit **25 tables et 239 rubriques**. L'analyse des noms, types, clés et traces de génération permet de documenter la structure et certaines relations historiques. Les fenêtres, requêtes et collections WLangage sont dans des formats binaires dont le code source métier n'est pas récupéré sous forme lisible.

Les tables de pièces jointes ne sont pas un catalogue de pièces détachées. Une table `Intervention` indépendante n'existe pas dans l'analyse récupérée : plusieurs champs de `Demande` portent déjà ces informations. La nouvelle séparation demande / intervention est donc un modèle reconstruit, à confronter aux cas de l'entreprise.

Voir [ANALYSE_WINDEV.md](ANALYSE_WINDEV.md) pour les preuves et les zones d'incertitude, et [EXPORT_HFSQL.md](EXPORT_HFSQL.md) pour les données, relations et traitements à demander au développeur.

## Reprise des données

La commande d'import valide le dossier d'export, ses empreintes et ses enregistrements, puis peut le stocker dans une zone de préparation serveur. Les identifiants longs restent des chaînes exactes ; ils ne transitent pas comme nombres JavaScript arrondis. Les champs `legacy_id` du nouveau modèle servent à conserver la référence HFSQL à côté des clés techniques de l'application.

La promotion vers les tables métier n'est pas automatique dans cette étape. Elle doit être précédée d'une validation des rattachements client / équipement, du vocabulaire des états, des doublons, des dates et des pièces jointes. Aucun mot de passe HFSQL n'est réutilisé ; les comptes sont recréés avec de nouveaux accès.

## Étapes suivantes

1. Valider les règles métier reconstruites avec des dossiers représentatifs : clôture, prise en garantie, opérations et visibilité client.
2. Réaliser un export HFSQL cohérent, contrôler les volumes, documenter les exceptions et tester la transformation sur une copie.
3. Mettre en service le serveur partagé en HTTPS, créer les vrais comptes et tester depuis plusieurs ordinateurs et un téléphone.
4. Relier WhatsApp avec ses événements de livraison et ses modèles autorisés.
5. Ajouter l'assistant IA avec filtrage serveur par dossier, journalisation adaptée et validation humaine des recommandations.

Ces étapes n'empêchent pas d'utiliser et tester le premier parcours sur des données saisies dans l'application. Elles distinguent ce parcours opérationnel des reprises et intégrations qui nécessitent des informations externes.
