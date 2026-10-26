# Suivre les demandes et l'historique SAV

## Identifier un dossier avec les deux numéros

Le **N° d'intervention / appel TVM** est le numéro métier du dossier SAV. Il reste commun à toutes les visites et opérations de ce dossier. Le **N° d'appel client** est la référence donnée par le centre SAV ou l'organisation qui confie la réparation à TVM.

| Référence | Rôle |
|---|---|
| N° d'intervention / appel TVM | Numéro unique du dossier dans TVM, attribué par le serveur |
| N° d'appel client | Référence du dossier chez le centre client, saisie comme du texte |
| Réf. de visite `INT-…` | Référence secondaire d'une visite ou fiche d'intervention liée au dossier |

Un dossier peut avoir plusieurs visites : elles gardent le même numéro TVM, avec des références de visite distinctes. Les visites ne sont pas fusionnées pour obtenir un seul numéro métier.

Pour les nouvelles demandes, le serveur attribue un numéro **`YY-NNNNN`**, par exemple `26-00123` dans un exemple entièrement fictif. L'année est celle du fuseau de l'application. Les anciennes références restent inchangées ; la mise à jour ne renumérote pas les anciens dossiers.

Le numéro du centre peut contenir des zéros initiaux, lettres, barres obliques et tirets, par exemple `0007/DEMO-AB` pour une référence entièrement fictive. Ne pas le convertir en nombre. Deux centres peuvent utiliser la même référence : elle ne permet pas de déduire le client ni de réunir automatiquement leurs dossiers.

Lors d'une nouvelle demande, sélectionner le centre client et renseigner son numéro dans **N° d'appel client**. Le numéro TVM est attribué à l'enregistrement ; il ne remplace pas la référence du centre.

L'équipe interne peut rechercher un dossier par l'un ou l'autre numéro. Dans le portail client, la recherche met en avant le **N° d'appel client** du centre ; le client n'a pas besoin de connaître la référence TVM pour retrouver son dossier. Les résultats restent limités à la société du compte connecté, même si un autre centre utilise le même numéro. Si plusieurs dossiers correspondent, utiliser le matériel et les autres informations affichées pour les distinguer.

Les deux PDF présentent clairement **N° d'intervention / appel TVM** et **N° d'appel client**. Les `INT-…` y figurent sous **Réf. de visite**. Une référence client absente reste **Non renseigné**.

## Annuaire clients et import CSV

L'annuaire **Clients** permet de retrouver une société par son nom, son contact, son matricule fiscal, son email, son téléphone ou sa ville. Le matricule fiscal reste du texte, avec ses zéros initiaux. Les notes internes de la fiche ne sont pas exposées au portail client.

Un administrateur ou responsable peut utiliser **Importer des clients** pour charger un fichier **UTF-8**, séparé de préférence par des **points-virgules** ; la virgule et le marqueur UTF-8 d'Excel sont aussi acceptés. La seule colonne obligatoire est `name`. Les coordonnées absentes peuvent rester vides : ne pas inventer un téléphone, un pays ou une adresse pour terminer la saisie.

En-têtes autorisés : `name`, `contact_name`, `tax_id`, `email`, `phone`, `address`, `city`, `postal_code`, `country`, `notes`. Exemple entièrement fictif :

```csv
name;notes
Client fictif;Coordonnées à vérifier
```

1. Sélectionner le **Fichier clients CSV**, ou choisir **Coller un CSV**, puis cliquer sur **Prévisualiser l'import**. Cette étape ne crée aucune fiche ; le modèle CSV proposé ne contient que les en-têtes.
2. Examiner les lignes nouvelles, déjà présentes, en doublon, en conflit ou invalides et leurs messages. Une information tronquée ou incertaine dans une capture doit rester à vérifier ; utiliser une note interne sans reconstituer une valeur supposée.
3. Corriger le fichier si nécessaire et refaire la prévisualisation, puis cliquer sur **Appliquer l'import**.
4. Contrôler le bilan : seules les lignes nouvelles et saines sont créées ; les lignes ignorées ou en erreur restent signalées. Une ligne invalide ne bloque pas à elle seule toutes les autres.

L'import ne remplace aucune fiche existante. Un même nom est comparé après normalisation de l'Unicode, des espaces et de la casse ; une divergence d'informations déjà renseignées est signalée comme conflit. Si une fiche existante manque d'une coordonnée fournie dans le CSV, un avertissement invite à la compléter manuellement : l'import ne la renseigne pas silencieusement. Un même matricule fiscal associé à un autre nom est également un conflit ; un email seul ne sert jamais d'identité.

Deux lignes identiques du même nom dans le fichier sont signalées en doublon ; si elles se contredisent, elles sont signalées en conflit. Réimporter les mêmes données ne crée pas une nouvelle copie de ces clients. Vérifier les cas ambigus plutôt que fusionner des sociétés sur une ressemblance de nom.

**Aucun compte portail ni mot de passe n'est créé ou modifié par cet import.** Les anciennes colonnes de connexion visibles dans des captures ne doivent pas être incluses ; les en-têtes non autorisés sont refusés. Ne pas recopier d'anciens accès dans les notes. Les comptes et leur association à une société restent gérés séparément par l'administrateur.

Le fichier privé contenant les clients réels est fourni séparément des sources publiques. Un import dans le cloud ne remplit pas la base Docker du PC : après mise à jour, importer ce CSV dans l'instance Windows concernée. La limite est de **2 Mio et 5 000 lignes** par fichier.

Cet import d'annuaire ne reconstitue pas les anciens dossiers, identifiants et relations HFSQL ; [la reprise historique](EXPORT_HFSQL.md) reste une opération distincte.

## Retrouver les dossiers

Le suivi SAV utilise les dossiers enregistrés dans la base commune. Les vues par type d'opération et par état servent à retrouver les demandes à traiter, les échanges, les mises en service et les opérations préventives. Les compteurs sont calculés sur le serveur à partir des données accessibles au compte connecté.

Une vue vide n'est pas alimentée par un exemple pour remplir l'écran. Vérifier le filtre, le type d'opération et le compte utilisé si un dossier attendu n'apparaît pas. Le portail client reste limité aux équipements et dossiers de sa société.

Les catégories de demandes correspondent aux états suivants :

| Catégorie | Dossiers présentés |
|---|---|
| Non affecté | État `new`, sans technicien affecté ; choisir un autre état lors de l'affectation |
| En entretien | États `maintenance` et ancien `in_progress` |
| En test | État `testing` |
| Traité | État `resolved` |
| Devis | État `quotation` |
| En attente | États `pending` et ancien `scheduled` |
| Validé | État `approved` |
| Refusé | État `rejected` |
| Échange | État `exchange` |
| Prêt à être livré | État `ready_for_delivery` |
| À retourner au client | État `return_to_client`, après diagnostic non réparable |
| Clôturé | État `closed` |
| En dépassement délai | Chronomètre en cours dépassant 48 heures cumulées du lundi au vendredi, avec une arrivée connue |
| Tous | Tous les dossiers accessibles |

**En dépassement délai** est un indicateur calculé depuis l'arrivée, pas un état enregistré. Il peut recouper une autre catégorie : additionner tous les compteurs ne donne donc pas nécessairement le total des demandes. L'échéance manuelle et le technicien affecté sont des informations distinctes, renseignées par un administrateur ou responsable.

## Compter les jours depuis l'arrivée

La date et l'heure d'arrivée sont une donnée du formulaire. Lors d'une nouvelle saisie, l'interface propose l'heure courante ; il faut la vérifier, la corriger ou la laisser vide si elle est inconnue. Le serveur ne remplace pas une arrivée absente par la date de création de la fiche. Pour une ancienne demande sans arrivée connue, le compteur affiche **Durée inconnue / Dates à compléter** jusqu'à ce que la donnée soit complétée.

La règle confirmée est **deux jours ouvrés, samedi et dimanche exclus**, soit 48 heures cumulées du lundi au vendredi dans le fuseau de l'application. Un jour affiché correspond à 24 heures ainsi cumulées. Les jours fériés et les horaires de bureau ne sont pas exclus : aucun calendrier de cette nature n'est configuré.

Le compteur devient rouge lorsque la durée dépasse **strictement 48 heures**. Par exemple, une arrivée un vendredi à 10 h atteint 24 heures cumulées le lundi à 10 h, puis 48 heures le mardi à 10 h ; le seuil est dépassé après cet instant, pas à 48 heures exactement. Le samedi et le dimanche n'ajoutent aucune heure.

L'affichage utilise les valeurs du serveur et les actualise périodiquement, ainsi qu'au retour sur l'onglet. Il ne calcule pas une autre durée à partir de l'horloge du PC.

La liste présente **Date d'arrivée** et **Nbr de jours ouvrés**. Le libellé indique **Dans le délai de 2 jours ouvrés** ou **Délai de 2 jours ouvrés dépassé** ; un dossier clôturé précise **Durée figée à la clôture**.

Passer la demande à **Clôturé** enregistre sa clôture et fige le compteur. Une durée déjà supérieure au seuil peut rester rouge à titre historique, mais une demande dont le compteur est arrêté ne figure plus dans le dépassement en cours. Une réouverture autorisée enlève la clôture automatique ; un échange facturé et clôturé reste conservé et exige un nouveau dossier pour une nouvelle opération. L'échéance manuelle reste un autre indicateur ; elle ne remplace pas le calcul depuis l'arrivée.

Les états **Traité** et **Refusé** n'arrêtent pas ce compteur : il continue jusqu'à la clôture du dossier. Terminer une intervention ne clôture donc pas implicitement la demande.

Pour une ancienne fiche clôturée dont l'heure de clôture manque, un administrateur ou responsable peut compléter cette information connue, sans inventer une date passée. La date doit être passée et ne pas précéder l'arrivée. Modifier une autre information du dossier ne décale pas la clôture déjà enregistrée.

La mise à jour ne remplit ni l'arrivée ni la clôture des anciennes fiches. Il faut connaître ces deux dates réelles pour calculer une durée fiable d'un ancien dossier clôturé.

## Lire une fiche et sa chronologie

Depuis une liste, **Ouvrir REF** ouvre le dossier SAV. L'onglet **Suivi** s'ouvre par défaut ; les autres regroupent **Matériel**, **Contrat**, **Maintenance**, **Mise en service**, **Préventive**, **Échange**, **Livraison / Retour**, **Conclusion** et **Documents**. Un administrateur ou responsable dispose de **Modifier le dossier** pour régler notamment son état, son affectation et son échéance. L'état **Non affecté** n'accepte pas de technicien affecté : sélectionner l'état approprié lors de l'affectation.

La fiche d'une demande regroupe son équipement, le client, l'état du dossier et les informations de traitement. L'historique de l'onduleur permet de retrouver les demandes et interventions rattachées au même matériel. La fiche équipement propose les onglets **Matériel** et **Historique des opérations** ; le dossier distingue **Historique du dossier** et **Historique de l'onduleur**.

La chronologie distingue les changements réellement enregistrés, leurs dates et leur auteur, ainsi que les observations ajoutées au suivi. Un changement d'état indique l'état précédent et le nouvel état lorsqu'ils sont connus. Une entrée ne représente pas une étape effectuée simplement parce qu'elle figure dans un déroulé type.

Une observation ajoute un élément de suivi. Une **synthèse** est un texte ajouté à l'historique par un utilisateur ; elle ne simule pas un diagnostic ou un traitement par l'assistant IA. Chaque ajout est conservé comme un événement : ce n'est pas une zone de texte qui réécrit les anciennes synthèses. Pour apporter une correction, ajouter un nouvel élément explicite.

Les observations et les informations internes restent soumises aux droits du compte. La consultation d'un historique ne donne pas accès à un autre client ni aux notes qui ne sont pas destinées au portail.

Les notes sont internes par défaut. Une transition d'état destinée au suivi public ne rend pas automatiquement publiques les observations internes qui l'accompagnent. Les comptes clients consultent uniquement les événements publics de leurs propres dossiers et ne peuvent pas ajouter d'événement. Un technicien ajoute des notes ou un changement d'état uniquement dans son périmètre d'affectation ; l'affectation et l'échéance restent gérées par l'administrateur ou le responsable.

Dans **Historique des opérations**, cliquer sur **Ajouter une opération**, puis choisir **Ajouter une observation**, **Ajouter une synthèse** ou, depuis une demande, **Changer l'état du dossier**. Vérifier la case de visibilité interne avant **Enregistrer l'opération**. Le filtre **Afficher** permet de retrouver les observations, synthèses, changements d'état, interventions ou états repris ; le choix **Ordre** permet une lecture chronologique ou du plus récent au plus ancien.

## Comprendre le point de départ de l'historique

Les nouvelles opérations de l'application web alimentent son historique. Les fiches déjà présentes lors de la mise à jour peuvent disposer d'un **état de référence**, ou *baseline*. Cet état donne le point de départ du suivi ; il ne constitue pas la reconstitution des anciens changements.

Une baseline doit être distinguée d'un événement utilisateur : elle ne prouve pas qu'une intervention a eu lieu à la date de mise à jour, ni qu'un compte précis a effectué une ancienne opération. Une date, un auteur ou une observation qui n'est pas connu ne doit pas être inventé.

**L'ancien journal HFSQL n'est pas importé dans cette chronologie par la mise à jour.** La commande de reprise HFSQL disponible conserve les exports dans une zone de préparation. Elle ne transforme pas automatiquement les lignes anciennes de `journal` ou des autres tables en événements web. Une reprise de cet historique nécessite un export cohérent, un mapping validé et des contrôles spécifiques : voir [EXPORT_HFSQL.md](EXPORT_HFSQL.md).

## Fiches structurées et rapports

Les opérations de maintenance, d'échange, de mise en service et de prévention peuvent nécessiter des informations différentes. Les fiches structurées permettent d'enregistrer les contrôles et observations correspondant au type choisi, puis de les retrouver dans le dossier et son rapport.

Les menus **Mise en service** et **Préventive** filtrent les fiches du type correspondant et préparent ce type lors d'une création. Le menu **Échange** est une file de demandes : passer un dossier à l'état Échange l'y fait apparaître automatiquement, même sans fiche d'intervention de type échange déjà créée.

Le dossier conserve son état et son numéro TVM commun aux visites. L'affichage dans la file permet de préparer le remplacement ; les validations technique et financière sont des opérations explicites, décrites ci-dessous.

| Type de fiche | Informations principales |
|---|---|
| Maintenance | Défaillances constatées et actions réalisées : batteries, électronique, surcharge, surtension, surchauffe, paramétrage ou réparation ; nombre de batteries remplacées si concerné |
| Échange | Matériel d'origine, nouvel onduleur de remplacement et date de l'opération |
| Mise en service | Protection électrique, câbles, branchement, paramétrage, mise sous tension et essais de fonctionnement, autonomie, by-pass et alarmes |
| Préventive | Environnement, câbles, historique des alarmes, essais d'autonomie, by-pass, alarmes et dépoussiérage |

Renseigner le **Type de fiche** et la **Date de l'opération**, puis les champs utiles : site, client final, contact, série de l'armoire, nombre de batteries, contrat ou extension de garantie. La date planifiée sert à une visite future ; une date d'opération future n'est pas acceptée. Pour terminer une fiche d'échange, de mise en service ou préventive, la date réalisée est obligatoire.

Pour qu'un technicien crée sa première intervention sur un dossier, le responsable doit d'abord lui affecter ce dossier. Le technicien ne peut pas s'attribuer librement un dossier tiers en y créant une intervention. Il peut ensuite travailler dans son périmètre d'affectation et reste limité à ses propres interventions.

Pour un échange terminé, le nouvel équipement doit être différent de l'ancien et appartenir au même client. Le dossier SAV reste rattaché au matériel d'origine ; choisir un remplacement ne réécrit pas son numéro de série. Le contrat doit concerner ce client et l'équipement d'origine, ou l'ensemble du client ; une extension de garantie doit concerner le matériel d'origine.

Les cases enregistrent ce que l'utilisateur déclare. Elles ne déclenchent pas à elles seules un mouvement de stock, une modification des équipements, une nouvelle garantie ou une facturation. Si le remplacement des batteries est déclaré sur une intervention terminée, leur nombre doit être précisé.

Créer une intervention ou changer réellement son état peut actualiser l'état de suivi de la demande en tenant compte des autres interventions. Modifier uniquement le diagnostic ne change pas cet état. Les états de gestion Devis, En attente, Validé, Refusé, Échange, Prêt à être livré, À retourner au client et Clôturé sont conservés par cette synchronisation.

La fiche comporte une **Synthèse de l'opération** et une **Conclusion de la fiche** : à suivre, terminée ou non applicable / facturable. Ce dernier choix exige une justification ; il n'est jamais déduit automatiquement de la date de garantie. La synthèse de la fiche est son texte courant, distinct des événements de synthèse ajoutés à l'historique.

La synthèse et la conclusion de la fiche sont destinées au suivi et au rapport. Pour une information réservée à l'équipe interne, utiliser les **Notes internes** ou une observation explicitement interne dans l'historique.

Un contrôle non renseigné n'est pas présenté comme réalisé. L'absence d'une valeur reste distincte d'une case explicitement enregistrée comme non cochée ; les anciennes fiches ne reçoivent pas de résultats de contrôle inventés. Le rapport PDF reprend les données enregistrées au moment de sa génération ; il ne remplace pas une signature client et ne constitue pas une archive immuable des versions antérieures. Le téléchargement reste soumis aux droits d'accès au dossier.

Le PDF utilise les cadres et rubriques du modèle fourni, avec une identité typographique TVM neutre, sans reprendre les coordonnées privées d'un exemple. Il distingue les cases **[X]** cochées, **[ ]** non cochées et **[-]** non renseignées. Les visas et signatures non recueillis sont explicitement indiqués comme tels. Les textes longs peuvent se poursuivre en annexes pour éviter une perte de contenu. Les notes internes sont exclues du rapport.

### Prévoir et compter les visites préventives

L'administrateur ou le responsable peut fixer le **Nombre de visites préventives prévues** sur le dossier, de 1 à 1 000, ou le laisser non renseigné. Un objectif de trois visites ne crée pas trois interventions : chaque visite doit être enregistrée et suivie comme une fiche liée à ce dossier.

Le nombre réalisé est calculé depuis ses fiches **Préventive** au statut **Terminée**. Le total enregistré inclut ses fiches préventives non annulées ; le reste correspond à l'objectif moins les terminées, sans devenir négatif. Les autres dossiers du même onduleur et les fiches de maintenance ou de mise en service ne gonflent pas ce compteur. Une prévision absente reste inconnue ; les compteurs réellement enregistrés restent visibles.

Le PDF présente les **visites réalisées / prévues**, les **visites enregistrées** et les **visites restant à réaliser**. Une ancienne fiche déjà terminée peut être comptée, mais une date absente n'est pas inventée. Modifier l'objectif ne change ni les visites existantes, ni leur référence `INT-…`, ni le numéro d'appel TVM commun.

La fiche et le PDF de **Mise en service** présentent séparément le matériel, le site, le client final, le contact et la date de réalisation. Ils ne sont pas comptés comme une visite préventive ; une date manquante reste explicitement non renseignée.

## Prêt à être livré et retour d'un matériel non réparable

Le menu **Livraisons & retours** présente deux colonnes. **Prêts à être livrés** regroupe les onduleurs réparés dont les tests ont été explicitement validés et les échanges dont le remplacement a été validé et déclaré prêt. Une fiche simplement terminée, un test échoué ou un test non renseigné ne suffit pas à y placer le matériel.

Les anciens dossiers déjà classés prêts restent visibles avec leur état conservé ; la mise à jour ne leur invente aucune preuve de tests ou d'approbation. Les nouveaux passages à cet état utilisent les actions dédiées ci-dessous.

La colonne distincte **À retourner au client** sert aux matériels déclarés **Non réparables**, avec un diagnostic renseigné et le suivi de leurs frais de diagnostic. Déclarer un matériel non réparable n'est pas une validation de réparation réussie.

Le champ Retour renseigné à l'accueil ne qualifie pas à lui seul cette non-réparabilité : la décision technique doit être enregistrée dans ce parcours.

Dans un dossier **En test** ou **Traité**, l'onglet **Livraison / Retour** propose **Tests validés — Réparé** : saisir la synthèse technique et la date réelle des tests, confirmer qu'ils sont réussis, puis utiliser **Confirmer la réparation et mettre prêt à livrer**. Pour un matériel non réparable, choisir **Non réparable — Retour client**, renseigner le diagnostic et le mode de frais, puis **Enregistrer le retour client**. Ces opérations sont accessibles à l'administrateur, au responsable ou au technicien affecté. Les contrôles sont des déclarations enregistrées par l'équipe ; aucune lecture automatique des mesures de l'onduleur n'est effectuée.

### Devis de diagnostic créé dans TVM

TVM génère le PDF du devis. Saisir explicitement le **prix HT**, le **taux de TVA** et la devise : **TND avec trois décimales par défaut**, ou EUR / USD avec deux décimales. Le taux peut être de 0 à 100 %, avec deux décimales maximum ; aucune règle fiscale n'est déduite automatiquement du pays ou du matricule client. Une prestation facturable a un prix HT positif ; une gratuité proposée a un montant nul.

Utiliser **Renseigner les conditions du devis**, puis **Enregistrer les conditions du devis**. Après vérification, **Émettre le devis PDF** attribue le numéro et fige les données ; **Télécharger le devis PDF** ouvre le document émis. Les conditions du devis figurent dans ce PDF destiné au client ; conserver les informations privées dans les champs internes.

Le serveur calcule la TVA avec arrondi à la précision de la devise, puis le total TTC. Un devis **émis** conserve son numéro, sa date et son contenu : son PDF n'est pas réécrit après une modification du dossier. Vérifier les conditions avant l'émission. Cette version ne propose pas encore de révision d'un devis émis, d'avoir ou de devis de remplacement ; une observation peut préciser une correction dans l'historique sans modifier le document officiel. Émettre le devis ne signifie pas l'avoir envoyé, fait accepter ou signer par le client.

Les coordonnées légales de l'émetteur et les conditions commerciales complémentaires non fournies ne sont pas inventées ; le PDF signale qu'elles ne sont pas renseignées.

Dans **Diagnostics à facturer** ou le dossier, un compte autorisé utilise soit **Confirmer la facturation du diagnostic** avec référence et date de facture externe, soit **Approuver la gratuité du diagnostic** avec un motif. Cette étape est nécessaire avant **Clôturer le dossier**. Une gratuité seulement proposée sur le devis n'est pas encore l'approbation financière. Son état actuel se consulte dans le dossier ; le PDF historique conserve ce qui était connu à son émission.

Cette option de gratuité concerne **uniquement le diagnostic**. Elle ne remplace pas la facture exigée pour clôturer un échange. Ni le devis TVM ni une confirmation de facture ne prétendent à un encaissement ou à un envoi vers un ERP. La file prépare le suivi du retour ; elle n'enregistre pas une expédition physique automatique.

Avant émission du devis, le responsable ou l'administrateur peut reprendre la qualification avec un motif. Cette reprise conserve l'historique et le contrôle financier du diagnostic ; changer simplement de statut ne dispense pas de la décision requise. Après émission, le devis et les conditions qui l'ont produit restent figés.

## Enlèvement, réception atelier et remise au client

L'administrateur crée un compte **Livreur** dans **Comptes & accès**. Ce rôle ouvre un espace logistique adapté au téléphone : **Accueil**, **Tournées**, **Réception**, **Prêts** et **Retours**. Il ne donne accès ni à la finance, ni aux comptes, ni aux diagnostics techniques internes. Les clients proposés lors d'une réception servent à identifier le propriétaire ; le livreur ne peut pas créer une société ou modifier les données d'un équipement connu.

Depuis son portail, le client ouvre **Mes enlèvements → Demander un enlèvement** pour sa société : choisir son équipement ou renseigner sa série et son modèle, décrire le problème et préciser l'adresse, le contact et son téléphone. Cette demande de transport ne prouve pas encore l'arrivée physique et ne crée pas automatiquement une réception SAV. Le responsable retrouve ces demandes dans **Logistique** et leur affecte un livreur. Le livreur voit ses propres missions et enregistre leur prise en charge.

À l'arrivée à l'atelier, ouvrir **Réception** ou **Réception atelier** :

1. Saisir la série, utiliser la douchette USB, la caméra compatible ou une photo d'étiquette, puis **Rechercher le matériel**. Une photo peut proposer plusieurs numéros : choisir et vérifier le numéro avant de poursuivre.
2. Vérifier le client, le modèle et la série. Un équipement connu garde ses informations enregistrées. Pour un matériel nouveau, sélectionner explicitement le modèle proposé ; si nécessaire, saisir un modèle manuel et sa justification. Un résultat ambigu n'est pas choisi arbitrairement.
3. Si un dossier ouvert existe, le sélectionner. Confirmer **Je confirme avoir reçu physiquement cet onduleur**, puis **Confirmer la réception**. Le serveur enregistre la date réelle de réception et retrouve ou crée le dossier approprié. Une nouvelle demande est **Non affecté**, sans technicien attribué.
4. Contrôler le reçu affiché : numéros TVM/client, matériel, propriétaire et arrivée. Une confirmation déjà enregistrée est retrouvée sans recréer le dossier ou remplacer sa date d'arrivée. Une simple lecture de code ou de photo n'enregistre rien.

Si un ancien dossier déjà traité n'a pas de date d'arrivée, demander au responsable de vérifier cette information ; la réception ne remplit pas cette date historique par supposition.

Les photos JPEG/PNG/WEBP sont analysées localement sur le serveur, avec une limite de 8 Mio et 12 millions de pixels. La lecture de code-barres puis l'OCR peuvent échouer selon l'étiquette ; les fichiers temporaires sont supprimés et la photo n'est pas ajoutée au dossier. La saisie manuelle reste possible. La caméra d'un téléphone réel et les étiquettes de l'entreprise doivent encore être essayées dans leur environnement HTTPS.

Pour la sortie, le responsable utilise **Logistique → Livraisons et retours à affecter**, vérifie l'adresse et le contact de livraison, choisit le livreur puis **Affecter le transport**. La livraison d'un échange concerne le remplacement validé ; une réparation ou un retour concerne le matériel du dossier. Le livreur retrouve les missions affectées dans **Prêts** ou **Retours**, avec leur destination et leur contact. Avant une remise, le responsable peut annuler une affectation avec un motif puis la réaffecter si nécessaire, en conservant la trace de l'annulation. Une remise déjà enregistrée reste conservée et ne se réaffecte pas.

Après remise physique, ouvrir **Confirmer la remise au client**, saisir le nom du destinataire, cocher **Je confirme avoir remis physiquement cet onduleur au destinataire indiqué**, puis **Enregistrer la remise**. L'heure et l'auteur viennent du serveur. Cette saisie atteste ce que le livreur déclare ; elle n'est ni une signature électronique ni un accusé de réception envoyé par le client. Le client consulte la remise de son propre dossier et reçoit une notification interne.

Après une remise, le remplacement et la qualification technique ne sont plus réinitialisables pour ce dossier. Les opérations financières requises restent possibles : la preuve de remise ne remplace ni la facture d'échange, ni la facture ou gratuité approuvée du diagnostic avant clôture.

## Notifications et rappels du livreur

La rubrique **Notifications et rappels** affiche les messages du compte connecté. Le portail client reçoit les événements de réception et de remise enregistrés pour sa société ; **Marquer comme lue** concerne uniquement la lecture dans TVM, sans accusé externe ou accord du client.

Le livreur et l'administrateur disposent, pour leur propre compte, de **Rappel quotidien à 08:00**. Cocher **Activer le rappel quotidien dans l'application**, vérifier le **Fuseau horaire du rappel**, puis utiliser **Enregistrer les rappels**. Le réglage est désactivé au départ. Il utilise un fuseau IANA, par exemple `Africa/Tunis` ; l'heure reste 08:00 dans ce fuseau, chaque jour. Le rappel présente les enlèvements et livraisons encore affectés au compte, sans informations de facturation.

Le serveur contrôle les rappels chaque minute : la notification est créée au premier contrôle à partir de 08:00, même si le navigateur est fermé, et sera consultable à sa réouverture. Un arrêt du serveur peut retarder le rappel jusqu'à sa reprise le même jour ; il ne crée pas toute une série de rappels anciens. Une désactivation arrête les créations suivantes ; réactiver le même jour ne crée pas de doublon.

**WhatsApp à connecter** et **Aperçu du message prévu** préparent une intégration future. Aucun accès WhatsApp n'a été fourni et l'utilisateur a choisi de connecter ce canal plus tard : aucun message, aucun envoi programmé et aucun ancien rappel en attente d'envoi WhatsApp n'est créé. Les rappels opérationnels de cette version sont ceux de la boîte de réception TVM.

## Échange : remplacement et facturation

Passer une demande à **Échange** l'affiche dans la file correspondante, sans devoir créer d'abord une visite de type échange. Le classement permet de commencer le traitement ; il ne vaut pas validation technique. Le dossier reste suivi dans cette file au fil de ses étapes, y compris lorsqu'il devient prêt à être livré.

1. Dans **Échange**, ouvrir le dossier puis **Préparer l'échange**. Renseigner le numéro de série, le modèle et la marque du remplacement ; **Enregistrer la préparation** conserve un brouillon, sans créer d'équipement. La recherche catalogue reste une aide facultative avec choix explicite.
2. Un administrateur ou responsable vérifie le numéro de série et le modèle, confirme leur contrôle puis clique sur **Valider l'échange**. Cet acte technique est distinct du statut terminé d'une visite. Il enregistre le nouvel équipement si nécessaire et le réserve pour ce dossier, sans remplacer l'identité de l'ancien onduleur.
3. L'administrateur ou responsable utilise ensuite le bouton séparé **Prêt à être livré** lorsque le matériel est prêt. Le bouton combiné **Valider et mettre prêt à livrer** permet aussi d'enregistrer les deux étapes après leur vérification. Le matériel rejoint alors la file commune **Livraisons & retours** ; ce statut ne constitue pas une preuve de livraison physique.
4. Dans **Échanges à facturer**, un compte autorisé renseigne la référence et la date de la facture émise dans le système de l'entreprise, puis clique sur **Confirmer la facturation**.
5. Utiliser **Clôturer le dossier** lorsque les validations requises sont enregistrées. Une facture non confirmée bloque la clôture ; classer le dossier ou terminer une visite ne contourne pas ce contrôle.

La file **Échanges à facturer** est proposée à l'administrateur et aux comptes internes autorisés. Dans **Comptes**, l'administrateur règle **Peut valider la facturation** pour les personnes choisies. Un responsable ou technicien n'en dispose pas automatiquement ; les clients n'y ont jamais accès. Le numéro d'appel TVM reste celui du dossier pendant ces étapes, et les visites gardent leurs références secondaires.

Un technicien affecté peut préparer le remplacement ; les validations technique et de disponibilité restent au responsable ou à l'administrateur. Le matériel doit être distinct de l'ancien et appartenir au même client ; il ne peut pas être réservé pour deux échanges ouverts à la fois. Avant facturation, une reprise de préparation avec motif permet de retirer une validation et d'effectuer une nouvelle vérification, en conservant l'historique.

Cette confirmation enregistre **une facture externe**. TVM ne crée ni n'envoie la facture dans un ERP et ne déclare pas son paiement. Les commentaires internes de facturation ne sont pas imprimés. Les références et dates de facture sont réservées au PDF interne ; le portail reçoit une confirmation générique.

Un ancien dossier ou une ancienne visite terminée conserve ses données, avec **validation non enregistrée** si aucun acte de validation n'est connu. La mise à jour ne transforme pas ces états historiques en approbation technique ou financière.

## Fiche de suivi et documents du dossier

L'onglet **Suivi** rassemble aussi les informations d'accueil du dossier : **N° d'appel client**, client final, arrivée et clôture, retour, emballage, lieu Atelier / Dépôt / Sur site, livraison par Livreur / Client, nom du livreur, accessoires et contact. La référence client est le numéro du centre qui confie la réparation ; elle ne déclenche pas un appel téléphonique ou une notification.

L'appréciation Garantie / Devis / Contrat / Hors garantie est une information de suivi renseignée par l'équipe. Elle ne déclenche pas une décision automatique de prise en charge ou de facturation. Les données manquantes restent à compléter ; les informations d'un dossier ou d'un modèle privé ne sont pas recopiées comme valeurs par défaut.

Deux PDF ont des rôles distincts : le **rapport d'intervention** décrit l'opération choisie et ses contrôles, tandis que le bouton **PDF de suivi du dossier** récapitule la réception, le compteur, l'historique public, les synthèses et les références d'intervention autorisés. Ils sont générés depuis la base ; le document privé fourni sert de modèle de structure, pas de fond contenant un client réel ou des coordonnées figées.

Pour une demande déjà enregistrée, l'onglet **Documents** et sa zone **Documents du dossier** permettent d'ajouter les photos et justificatifs :

1. Cliquer sur **Ajouter un document**, sélectionner le fichier et, si utile, renseigner un libellé.
2. Laisser le document interne, ou cocher explicitement **Partager ce document avec le client du dossier**.
3. Cliquer sur **Enregistrer le fichier** et attendre la confirmation du serveur.
4. Utiliser **Télécharger** pour retrouver le fichier depuis les postes autorisés. La suppression, lorsqu'elle est permise au compte, demande une confirmation.

Formats acceptés : **PDF, JPEG, PNG, DOCX, XLSX et TXT**, avec une limite de **10 Mio par fichier**. Un fichier est envoyé à la fois. La taille et le format sont contrôlés ; ce contrôle n'est pas une analyse antivirus. Les fichiers restent privés côté serveur : un client ne voit que ceux qui ont été partagés explicitement dans ses propres dossiers.

Les pièces jointes ne sont pas intégrées automatiquement dans le PDF comme des pages supplémentaires. Leur conservation demande une sauvegarde des fichiers média **et** de la base qui les référence ; sauvegarder seulement les sources ne suffit pas.

## Conserver les dossiers historisés

Les événements ne se modifient ni ne se suppriment. En PostgreSQL, cette conservation est également protégée au niveau de la base. Les comptes auteurs, équipements et demandes liés à l'historique ne peuvent donc pas être supprimés comme des fiches sans dépendance : une tentative peut être refusée avec un conflit `409`.

Pour arrêter l'utilisation sans perdre le suivi, l'administrateur peut **désactiver le compte**, et un rôle de gestion peut passer un équipement **Hors service** ou une demande **Clôturé**. Ces états conservent les relations et la chronologie. Corriger une observation ou une synthèse d'historique consiste à ajouter un événement explicite ; cela ne réécrit pas l'ancien.

## Mettre à jour une installation Windows

Arrêter l'application avec `ARRETER_TVM.cmd`. Remplacer les sources dans le dossier TVM déjà utilisé, en conservant **`.env`, `.local` et les données Docker**, puis relancer `INSTALLER_TVM.cmd` pour reconstruire l'application et appliquer les migrations.

La nouvelle numérotation s'applique aux prochaines demandes. Les références déjà enregistrées, les numéros des centres et les visites existantes restent conservés ; la mise à jour ne doit pas les reformater pour leur donner l'apparence des nouveaux numéros.

Un nouveau dossier extrait n'est pas une nouvelle base indépendante. Si vous changez de dossier, récupérer d'abord la configuration de l'installation existante selon [le guide Windows](INSTALLATION_WINDOWS.md#mettre-à-jour-lapplication-sans-perdre-la-configuration). Ne pas supprimer les volumes Docker pour obtenir les nouvelles vues ou l'historique.

Les sources mises à jour ne copient pas la base du cloud sur le PC et ne reconstituent pas l'ancien historique HFSQL. Chaque instance affiche ses propres dossiers et événements enregistrés.

## Données privées et portée des vérifications

Les captures WINDEV reçues contiennent des clients réels et servent à comprendre le fonctionnement attendu. Elles ne sont pas incluses dans les sources publiques, les captures de démonstration ou l'archive de livraison. Le catalogue privé et les exports métier restent également hors du dépôt.

La présence d'une vue ou d'un rapport ne prouve pas que toutes les règles WINDEV binaires ont été converties. Les comportements reconstruits sont documentés et les résultats réellement vérifiés figurent dans [VALIDATION.md](VALIDATION.md).
