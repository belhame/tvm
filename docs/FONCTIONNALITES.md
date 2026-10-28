# Fonctionnalités, périmètre et suites

## Ce que livre cette étape

Cette version fournit une application serveur et son code source, avec des comptes authentifiés, une base PostgreSQL partagée et un premier parcours SAV complet. Les données fictives sont optionnelles et explicitement signalées. Les listes, graphiques et documents affichent les données de la base accessible au compte connecté.

| Domaine | Comportement de cette version | Limite à connaître |
|---|---|---|
| Comptes | Administrateur, responsable SAV, technicien, livreur et client ; sessions serveur ; gestion des comptes par l'administrateur | Pas de SSO ni d'authentification multifacteur fournis |
| Portail client | Consultation des dossiers de sa société, demande d'enlèvement et notifications propres | Pas de modification des dossiers SAV ni de création publique de compte |
| Clients | Annuaire recherchable, contacts, coordonnées, matricule fiscal et notes internes ; import CSV avec prévisualisation | Aucun écrasement de fiche ni reprise de compte ; conflits et valeurs incertaines à vérifier, CSV réel séparé des sources publiques |
| Onduleurs | Affectation client, modèle, marque, puissance, site et numéro de série unique | Le rattachement des anciens onduleurs HFSQL doit être confirmé |
| Lecture des séries Eaton | Analyse consultative en cinq segments dans la fiche équipement et le scanner, d'après le classeur fourni | Format de dix caractères à valider sur des étiquettes réelles ; aucun modèle, année civile ou garantie déduits automatiquement |
| Catalogue Eaton BN | Import XLS versionné dans PostgreSQL et consultation interne ; provenance des lignes, empreinte SHA-256 et conservation des collisions | Import administrateur/responsable, lecture technicien, aucun accès client ; fichier privé à importer dans chaque instance, sans modification automatique des équipements |
| Demandes SAV | Réception simple avec client, série et livreur d'arrivée ; affectation, confirmation de prise en charge et suivi avec observation obligatoire si l'état change | Série inconnue acceptée avec Modèle non identifié ; nouvelle demande Non affecté et arrivée serveur ; dossier ouvert existant conservé sans doublon |
| Numéros de dossier | N° d'intervention / appel TVM unique et commun aux visites ; N° d'appel client distinct, recherché dans le périmètre du compte | Références des centres conservées comme texte et non uniques globalement ; aucun client déduit du numéro |
| Demande avancée à partir d'une série | Recherche interne du modèle et de la garantie, puis création transactionnelle de la demande et, si nécessaire, de l'équipement et de sa garantie | Ancien formulaire conservé ; création contrôlée d'équipement administrateur/responsable ; données existantes prioritaires et choix ambigus explicites |
| Suivi et classement SAV | Vues par type d'opération et état, avec compteurs calculés depuis les dossiers accessibles | Les états web ne constituent pas une conversion automatique de tous les anciens codes WINDEV |
| Arrivée et durée de suivi | Arrivée explicite, jours cumulés du lundi au vendredi, alerte après 48 heures et compteur figé à la clôture | Samedi/dimanche exclus ; ni calendrier de jours fériés ni plages d'heures de bureau ; arrivée ancienne inconnue conservée comme telle |
| Historique métier | Suivi des événements réellement enregistrés autour des demandes et des équipements, avec observations et synthèse du dossier | État de référence des anciennes fiches distinct d'un changement utilisateur ; aucun ancien journal HFSQL importé automatiquement |
| Interventions | Affectation, dates, durée, diagnostic, travaux, recommandations, état et fiches de maintenance, échange, mise en service ou préventive | Cases et conclusions déclaratives ; aucun mouvement de stock, décision de garantie ou facturation déclenchés par une case |
| Échanges | File automatique des demandes classées Échange, remplacement et validation technique explicites, passage Prêt à être livré | Un classement ou une visite terminée ne constitue pas une validation ; aucune ancienne approbation inventée |
| Échanges à facturer | Confirmation financière séparée avec référence et date de facture externe ; contrôle avant clôture | Droit délégué par l'administrateur ; aucun ERP, envoi de facture ou paiement confirmé par cette saisie |
| Prêt à être livré | File commune des réparations avec tests validés et des échanges effectivement prêts ; colonne séparée des non-réparables à retourner | Un test absent ou échoué ne vaut pas validation ; aucune expédition physique automatique |
| Devis de diagnostic | Devis PDF créé dans TVM avec prix HT, TVA et devise explicites, document émis immuable | Aucun taux fiscal déduit ; aucune révision du devis émis dans cette version ; retour clôturable après facture ou gratuité approuvée, sans exemption de facture pour un échange |
| Planning | Vue des interventions datées enregistrées sur le serveur | Pas de synchronisation Outlook/Google Calendar |
| Visites préventives | Objectif par dossier et nombre réalisé calculé depuis ses fiches préventives terminées ; progression sur la fiche et le PDF | L'objectif ne crée pas de visites ; aucune date ou ancienne prévision inventée, aucun autre dossier inclus |
| Rapports | Rapport PDF d'intervention structuré d'après le modèle fourni et fiche PDF de suivi du dossier, soumis aux droits d'accès | Documents générés depuis la base ; pas de signature électronique, d'envoi automatique ni d'historique PDF immuable |
| Pièces jointes SAV | Fichiers privés côté serveur, liés aux dossiers et partagés au client uniquement de façon explicite | Formats autorisés et limite de taille ; contrôle de format, sans prétendre fournir un antivirus |
| Contrats | Fiche de contrat liée au client et éventuellement à un équipement, dates et couverture | Pas de facturation ni de génération automatique d'échéanciers |
| Garanties | Carte de vérification modèle/génération/références/dates ; fabrication + six mois calendaires, données enregistrées prioritaires ; orientation Garantie ou Devis/facturable | Référence générale de famille signalée comme provisoire ; inconnu distinct d'expiré ; aucun PDF de devis/facture automatique, aucune API Eaton directe |
| Batteries du dossier SAV | Configuration nominale du modèle exact après prise en charge acceptée ; quantité proposée puis confirmée ou corrigée explicitement dans le suivi | Variantes/générations distinctes ; EBM séparées, nombre inconnu distinct de zéro ; aucune réécriture des anciens rapports ni mouvement de stock |
| Pièces et stock | Catalogue, seuils et mouvements d'entrée/sortie ; contrôle du stock négatif ; rattachement possible à une intervention | Module nouveau : aucune table de stock n'a été identifiée avec certitude dans l'archive WINDEV |
| Bons de livraison | Fiches manuelles conservées ; BL logistique avec PDF immuable, individuel ou lot de 1–100 missions d'un même client et livreur | TVM : ses missions acceptées ; préparation du lot invalidée si une mission change ; aucune remise, clôture, facture ou sortie de stock implicite |
| Tableau de bord | Première rubrique et accueil des administrateurs, responsables et techniciens ; compteurs, activité et états issus de la base | Pas de statistiques historiques importées avant reprise des données |
| Recherche | Recherche de clients, dossiers, interventions et séries selon les droits du compte | Aucun accès implicite à une autre société via une recherche |
| Notifications internes | Boîte propre au compte ; disponibilité prête pour TVM/admin, mission affectée pour le TVM désigné, réception/remise pour le portail et rappel opt-in de 08:00 | Compteur réel relu toutes les 30 s et au retour sur l'onglet ; aucune notification push navigateur fermé ni envoi WhatsApp de ces alertes |
| Notifications du centre | Journal des affectations et collectes, destinataire responsable de la société, canaux e-mail/WhatsApp opt-in, aperçu et relance contrôlée | Canaux désactivés et accès absents dans l'instance de travail ; aucune reprise automatique des anciennes entrées bloquées ; accepté ne signifie pas reçu/lu |
| Logistique | Enlèvements, réception, file partagée TVM tous clients, missions confirmées et preuve de remise | Réservation protégée ; externe limité à ses missions ; acceptation distincte de la remise et de la clôture financière |
| Traçabilité | Journal des opérations accessible aux administrateurs / responsables via `/api/audit/` | Consultation via l'API ; pas de vue dédiée dans cette étape |

Les droits sont appliqués dans l'API. Masquer une rubrique du menu ne constitue pas à lui seul un contrôle d'accès. Les rapports et recherches doivent rester dans le périmètre autorisé ; les notes internes n'ont pas vocation à être exposées au client.

## Rôles

| Rôle | Autorisations métier |
|---|---|
| Administrateur | Création et modification des données métier ; gestion des comptes, rôles et délégations de validation financière ; autorisation financière implicite |
| Responsable SAV | Création et modification des données métier, affectation et suivi ; consultation de la traçabilité ; aucune gestion des comptes |
| Technicien | Lecture des données métier internes ; création de demandes Non affecté ; prise en charge directe ou relais motivé d'un dossier non clôturé ; suivi, fiches et consommation de pièces dans le cadre de son affectation courante confirmée, avec les limites propres à ses interventions |
| Livreur TVM | Espace restreint : collectes affectées, SAV simple/réception, file partagée des prêts, prise ou confirmation de mission, ses BL et remises ; notifications, sans diagnostics internes, factures ou comptes |
| Livreur client | Compte lié à sa société : ses livraisons/retours affectés, confirmation puis remise ; aucune file globale, nouveau BL PDF, collecte, réception, recherche de séries ou photo OCR |
| Client | Consultation de sa société et demande d'enlèvement, recherche prioritairement par son N° d'appel client ; aucun accès au stock, aux comptes, à la traçabilité ou aux intégrations |

Le technicien ne supprime pas de dossier et ne modifie pas les fiches clients, équipements, contrats, garanties, pièces ou bons de livraison. Les droits du portail sont liés à la société du compte, non à un simple filtre choisi dans l'interface.

L'administrateur ou le responsable affecte le dossier ; le technicien désigné confirme avec **Oui**, tandis qu'**Annuler** ne produit aucun refus. Une réaffectation managériale retire l'acceptation pour le travail à venir. Une ancienne visite permet de conserver l'accès en lecture, sans donner de droit de modification sur le dossier réaffecté. Seul l'administrateur peut confirmer au nom du technicien avec un motif historisé ; administrateur et responsable conservent leur suivi autorisé sans acceptation personnelle, avec les mêmes contrôles financiers et logistiques.

Un technicien peut aussi **Prendre en charge** un dossier sans personne désignée ou **Prendre le relais** d'une autre personne, sans accord préalable du responsable ou de l'ancien intervenant. Après confirmation explicite, ces actions affectent et acceptent le dossier ensemble ; le relais exige un motif interne historisé. Les dossiers clôturés sont exclus. L'état reste conservé, sauf `new` qui devient `pending` ; le passage En entretien se fait ensuite avec son observation. Les anciennes fiches gardent leur auteur, et le nouveau technicien crée sa propre visite si nécessaire.

Cette condition d'écriture du suivi ne retire pas la consultation de l'historique ni les contributions techniques autorisées à la bibliothèque depuis des interventions historiques terminées. Ces retours d'expérience restent soumis à leur propre validation.

La validation financière est une autorisation distincte : hors administrateur, elle doit être accordée explicitement à un compte interne actif éligible. Elle couvre la confirmation des factures et l'approbation d'une gratuité de diagnostic. Cette gratuité ne supprime pas l'exigence de facture d'un échange. Le rôle Responsable SAV ou Technicien n'accorde pas automatiquement ce droit ; un client ou un livreur ne peut jamais en bénéficier et sa gestion reste réservée à l'administrateur.

Le client peut être un centre SAV qui confie une réparation à TVM. Son numéro de dossier est enregistré dans `client_reference`, sans remplacer le numéro TVM ni servir à déterminer ses droits. L'appartenance au centre vient de la relation client du compte et de l'équipement. Le champ texte Client final ne crée pas une autre autorisation de portail.

Une société peut définir son livreur client et son référent TVM. Les nouvelles mises à disposition prêtes utilisent ces référents dans cet ordre ; sans référent valide, le dossier reste à affecter. Les choix manuels et les preuves de remise restent conservés. Une collecte chez le client final reste la propriété du centre et relève toujours des livreurs TVM.

L'import d'annuaire est réservé aux administrateurs et responsables. Il accepte une fiche avec son nom seul, garde les informations absentes vides et ne reprend aucune ancienne colonne de connexion. Les notes `Client.notes` et le nombre de comptes portail restent internes ; créer les accès utilisateurs est une opération distincte.

## Catégories et historique SAV

Les catégories des demandes donnent accès aux dossiers nouveaux, en maintenance, en test, traités, en devis, en attente, approuvés, rejetés, échangés, prêts, à retourner ou clôturés. Le dépassement en cours est calculé depuis l'arrivée au-delà de **48 heures cumulées du lundi au vendredi** et peut recouper un autre état. L'échéance manuelle reste distincte. Les compteurs sont produits par le serveur dans le périmètre autorisé ; ils ne sont pas des chiffres de démonstration ajoutés à l'interface.

La chronologie d'une demande ou d'un onduleur expose les événements enregistrés, leur date et leur auteur, les changements d'état, les observations et les synthèses ajoutées. Les notes sont internes par défaut ; le portail client ne voit que les événements publics de ses propres dossiers. Une synthèse est un événement conservé, pas une réponse de l'assistant IA.

Le formulaire **Mettre à jour le suivi** réunit l'état du dossier, l'observation et la synthèse facultative, sans exiger une fiche d'intervention. Un changement d'état exige une observation ; à état inchangé, une observation ou une synthèse suffit. L'état public et les notes internes sont enregistrés séparément. Un état ou une affectation devenus obsolètes imposent une actualisation avant l'enregistrement.

Les fiches préexistantes disposent d'un état de référence distinct des nouveaux événements. Cet état ne reconstitue pas les étapes passées : **l'ancien historique HFSQL n'est pas importé dans la chronologie par cette mise à jour**. Voir [le guide du suivi SAV](GUIDE_SUIVI_SAV.md).

La conservation des événements protège aussi leurs liens : supprimer un compte auteur, un équipement ou un dossier historisé peut être refusé. Désactiver le compte ou utiliser les états Hors service / Clôturé permet d'arrêter leur utilisation en conservant le suivi.

Les fiches d'intervention structurées enregistrent les vérifications propres au type d'opération, le matériel de remplacement pour un échange, les références de contrat ou d'extension et une synthèse/conclusion. Le PDF reprend ces données connues sans notes internes. Une conclusion « non applicable / facturable » exige une justification humaine ; elle ne résulte pas d'une déduction automatique depuis la garantie.

Le parcours d'échange distingue la validation technique du remplacement, l'état Prêt à être livré et la confirmation de facturation. La clôture attend une facture confirmée ; aucune case de fiche ou ancienne opération terminée ne remplace cette validation. Voir [le guide des échanges](GUIDE_SUIVI_SAV.md#échange--remplacement-et-facturation).

Les réparations testées rejoignent la même file prête que les échanges validés. Les non-réparables utilisent une colonne distincte et un devis de diagnostic TVM, suivi d'une facture externe confirmée ou d'une gratuité approuvée. Les statuts anciens restent conservés sans preuves inventées. Voir [le parcours livraison / retour](GUIDE_SUIVI_SAV.md#prêt-à-être-livré-et-retour-dun-matériel-non-réparable).

## Scan sur téléphone et photo d'étiquette

Le scanner utilise la caméra du navigateur et l'API `BarcodeDetector` lorsqu'elle est disponible. Il lit un code-barres ou QR code contenant le numéro, puis effectue une recherche réelle côté serveur. La vidéo reste sur l'appareil ; elle n'est pas envoyée pour reconnaissance.

La caméra requiert un contexte sécurisé : HTTPS en déploiement, ou l'exception locale du navigateur pour `localhost`. Le navigateur doit accepter l'accès caméra et supporter les formats de code concernés. La saisie manuelle du numéro de série reste disponible si le navigateur ou la caméra ne convient pas. La compatibilité d'un téléphone précis se valide avec une vraie étiquette de l'entreprise.

La réception logistique accepte aussi une douchette USB qui saisit le numéro comme un clavier, ou une **photo JPEG/PNG/WEBP** analysée sur le serveur. Pour la photo, le serveur cherche un code-barres avec ZXing puis du texte avec Tesseract local, sans fournisseur IA ni API extérieure. Il propose des numéros à choisir et vérifier ; la photo ne confirme aucune réception et ne modifie aucun dossier. Elle n'est pas conservée, ses métadonnées sont retirées et les fichiers temporaires supprimés. Limites : 8 Mio, 12 millions de pixels et traitement borné. Les outils sont fournis dans l'image Docker ; hors Docker leur disponibilité doit être vérifiée.

Une lecture OCR dépend de la netteté, de l'étiquette et du repérage du champ S/N. Elle peut proposer plusieurs numéros ou n'en trouver aucun ; la saisie manuelle reste disponible. Les tests fictifs ne valident pas toutes les étiquettes ni la caméra d'un téléphone physique.

Une aide de lecture des séries Eaton est proposée dans le scanner et la fiche équipement. Elle découpe le format documenté en codes usine, produit, année, semaine et ordre de fabrication sans modifier les données. Les autres formats restent autorisés. Le document source comporte des ambiguïtés et ne permet pas de calculer une année civile ou une garantie ; voir [le détail et les points à valider](NUMEROS_SERIE_EATON.md).

## Catalogue Eaton BN

Le menu interne **Catalogue Eaton** permet d'importer et de consulter le fichier de référence `Product serial number Vers BN.xls`. L'import conserve les versions, la provenance des lignes, les entrées `NA` et les collisions de codes. Il reconnaît un fichier identique par SHA-256 et active une version complète de façon atomique ; les références d'années et de garanties restent distinctes.

Ce catalogue ne transforme pas l'aide de lecture initiale en décodeur universel des quatre profils et ne modifie aucun équipement automatiquement. Un import dans le cloud n'alimente pas la base de votre PC : le fichier original doit être importé une fois dans votre propre instance après mise à jour. Voir [la procédure et les contrôles attendus](IMPORT_CATALOGUE_EATON.md).

## Nouvelle demande à partir d'un numéro de série

Le formulaire simple accepte client, série et livreur ; le livreur TVM créateur est indiqué automatiquement. Un employé peut choisir un livreur TVM ou un livreur actif de la société concernée. Modèle, objet et description ne bloquent pas la réception ; l'écran indique Modèle non identifié pour un équipement inconnu, sans garantie inventée. Les anciens appels et leurs dates connues signalent les retours. Un dossier ouvert provoque un conflit avec proposition de l'ouvrir, sans modifier son arrivée ni recréer son suivi.

Une couverture globale active disponible oriente vers Garantie ; des dates enregistrées actives sans étendue précisée permettent une orientation provisoire avec étendue à confirmer. Une garantie expirée ou une absence de couverture établie oriente vers Devis/facturable. Une garantie indéterminée ou pas encore commencée reste Devis/facturable provisoire avec Garantie à vérifier. Une couverture de composant ou un contrat ne devient pas une garantie globale par déduction. Aucun devis PDF ni facture n'est émis par cette orientation.

**Options avancées**, accessible à l'administrateur et au responsable, conserve l'ancien formulaire et la recherche interne du modèle et des informations de garantie à partir de la série. Les fiches, garanties et contrats déjà enregistrés sont prioritaires. Dans ce parcours avancé, un administrateur ou responsable peut enregistrer l'équipement, la demande et une garantie calculable dans une même transaction. **Saisie rapide** revient au formulaire simple.

La règle confirmée est **début de garantie = fabrication + six mois calendaires**, affichée comme règle TVM. Les profils utilisent leurs propres références d'années ; les dates imprécises, les cycles ambigus et les modèles non déductibles ne sont pas remplacés par des suppositions. Voir [le parcours et les limites par profil](PARCOURS_DEMANDE_SERIE.md).

## Intégrations à connecter

| Intégration | État livré | Éléments requis avant activation |
|---|---|---|
| E-mail | Adaptateur SMTP et file persistante, désactivés ; essais en mémoire seulement | Serveur SMTP, compte, expéditeur et TLS/SSL, activation serveur et option par société, essai réel à effectuer |
| WhatsApp | Adaptateur Cloud API avec modèle à cinq paramètres, aperçu et journal ; désactivé, accès à connecter plus tard | Compte WhatsApp Business / Meta, numéro validé, jeton et modèle approuvé, activation serveur et option par société ; réception/lecture par webhook non fournie |
| Assistant IA | Écran d'état ; aucun diagnostic ni réponse simulés | Fournisseur et modèle retenus, accès API côté serveur, règles de confidentialité, filtrage des dossiers avant chaque requête et validation des réponses |

Fournir une clé ne prouve pas une intégration validée : les accès et les essais réels restent à effectuer. Les adaptateurs SMTP/WhatsApp contrôlent les erreurs et l'acceptation ; ils ne simulent pas une réception ou une lecture. Aucun secret fournisseur n'est demandé dans un formulaire navigateur ou enregistré dans les sources.

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
