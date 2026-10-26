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

Passer la demande à **Clôturé** enregistre sa clôture et fige le compteur. Une durée déjà supérieure au seuil peut rester rouge à titre historique, mais une demande dont le compteur est arrêté ne figure plus dans le dépassement en cours. Réouvrir la demande enlève la clôture automatique. L'échéance manuelle reste un autre indicateur ; elle ne remplace pas le calcul depuis l'arrivée.

Les états **Traité** et **Refusé** n'arrêtent pas ce compteur : il continue jusqu'à la clôture du dossier. Terminer une intervention ne clôture donc pas implicitement la demande.

Pour une ancienne fiche clôturée dont l'heure de clôture manque, un administrateur ou responsable peut compléter cette information connue, sans inventer une date passée. La date doit être passée et ne pas précéder l'arrivée. Modifier une autre information du dossier ne décale pas la clôture déjà enregistrée.

La mise à jour ne remplit ni l'arrivée ni la clôture des anciennes fiches. Il faut connaître ces deux dates réelles pour calculer une durée fiable d'un ancien dossier clôturé.

## Lire une fiche et sa chronologie

Depuis une liste, **Ouvrir REF** ouvre le dossier SAV. L'onglet **Suivi** s'ouvre par défaut ; les autres regroupent **Matériel**, **Contrat**, **Maintenance**, **Mise en service**, **Préventive**, **Échange**, **Conclusion** et **Documents**. Un administrateur ou responsable dispose de **Modifier le dossier** pour régler notamment son état, son affectation et son échéance. L'état **Non affecté** n'accepte pas de technicien affecté : sélectionner l'état approprié lors de l'affectation.

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

Les menus **Échange**, **Mise en service** et **Préventive** filtrent les fiches du type correspondant et préparent ce type lors d'une création. Le dossier SAV conserve son propre état, distinct du type de fiche.

L'état d'une demande et le type d'une fiche d'intervention sont deux informations distinctes. Classer une demande dans **Échange** ne crée pas automatiquement une fiche d'échange remplie. Une demande peut être liée à plusieurs interventions ; ouvrir ou créer la fiche correspondant à l'opération réellement effectuée.

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

Créer une intervention ou changer réellement son état peut actualiser l'état de suivi de la demande en tenant compte des autres interventions. Modifier uniquement le diagnostic ne change pas cet état. Les états de gestion Devis, En attente, Validé, Refusé, Échange et Clôturé sont conservés par cette synchronisation.

La fiche comporte une **Synthèse de l'opération** et une **Conclusion de la fiche** : à suivre, terminée ou non applicable / facturable. Ce dernier choix exige une justification ; il n'est jamais déduit automatiquement de la date de garantie. La synthèse de la fiche est son texte courant, distinct des événements de synthèse ajoutés à l'historique.

La synthèse et la conclusion de la fiche sont destinées au suivi et au rapport. Pour une information réservée à l'équipe interne, utiliser les **Notes internes** ou une observation explicitement interne dans l'historique.

Un contrôle non renseigné n'est pas présenté comme réalisé. L'absence d'une valeur reste distincte d'une case explicitement enregistrée comme non cochée ; les anciennes fiches ne reçoivent pas de résultats de contrôle inventés. Le rapport PDF reprend les données enregistrées au moment de sa génération ; il ne remplace pas une signature client et ne constitue pas une archive immuable des versions antérieures. Le téléchargement reste soumis aux droits d'accès au dossier.

Le PDF utilise les cadres et rubriques du modèle fourni, avec une identité typographique TVM neutre, sans reprendre les coordonnées privées d'un exemple. Il distingue les cases **[X]** cochées, **[ ]** non cochées et **[-]** non renseignées. Les visas et signatures non recueillis sont explicitement indiqués comme tels. Les textes longs peuvent se poursuivre en annexes pour éviter une perte de contenu. Les notes internes sont exclues du rapport.

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
