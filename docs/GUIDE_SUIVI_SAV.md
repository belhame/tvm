# Suivre les demandes et l'historique SAV

## Retrouver les dossiers

Le suivi SAV utilise les dossiers enregistrés dans la base commune. Les vues par type d'opération et par état servent à retrouver les demandes à traiter, les échanges, les mises en service et les opérations préventives. Les compteurs sont calculés sur le serveur à partir des données accessibles au compte connecté.

Une vue vide n'est pas alimentée par un exemple pour remplir l'écran. Vérifier le filtre, le type d'opération et le compte utilisé si un dossier attendu n'apparaît pas. Le portail client reste limité aux équipements et dossiers de sa société.

Les catégories de demandes correspondent aux états suivants :

| Catégorie | Dossiers présentés |
|---|---|
| Non affecté | État `new` ; le technicien affecté est une information distincte |
| En entretien | États `maintenance` et ancien `in_progress` |
| En test | État `testing` |
| Traité | État `resolved` |
| Devis | État `quotation` |
| En attente | États `pending` et ancien `scheduled` |
| Validé | État `approved` |
| Refusé | État `rejected` |
| Échange | État `exchange` |
| Clôturé | État `closed` |
| En dépassement délai | Échéance passée, sauf dossiers traités, rejetés ou clôturés |
| Tous | Tous les dossiers accessibles |

**En dépassement délai** est un indicateur calculé depuis l'échéance, pas un état enregistré. Il peut recouper une autre catégorie : additionner tous les compteurs ne donne donc pas nécessairement le total des demandes. Un administrateur ou responsable peut renseigner l'échéance et le technicien affecté dans la fiche.

## Lire une fiche et sa chronologie

La fiche d'une demande regroupe son équipement, le client, l'état du dossier et les informations de traitement. L'historique de l'onduleur permet de retrouver les demandes et interventions rattachées au même matériel.

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

La fiche comporte une **Synthèse de l'opération** et une **Conclusion de la fiche** : à suivre, terminée ou non applicable / facturable. Ce dernier choix exige une justification ; il n'est jamais déduit automatiquement de la date de garantie. La synthèse de la fiche est son texte courant, distinct des événements de synthèse ajoutés à l'historique.

La synthèse et la conclusion de la fiche sont destinées au suivi et au rapport. Pour une information réservée à l'équipe interne, utiliser les **Notes internes** ou une observation explicitement interne dans l'historique.

Un contrôle non renseigné n'est pas présenté comme réalisé. L'absence d'une valeur reste distincte d'une case explicitement enregistrée comme non cochée ; les anciennes fiches ne reçoivent pas de résultats de contrôle inventés. Le rapport PDF reprend les données enregistrées au moment de sa génération ; il ne remplace pas une signature client et ne constitue pas une archive immuable des versions antérieures. Le téléchargement reste soumis aux droits d'accès au dossier.

Le PDF inclut les champs connus de la fiche, les contrôles renseignés, la synthèse et la conclusion, ainsi que les références liées disponibles. Les notes internes sont exclues du rapport.

## Conserver les dossiers historisés

Les événements ne se modifient ni ne se suppriment. En PostgreSQL, cette conservation est également protégée au niveau de la base. Les comptes auteurs, équipements et demandes liés à l'historique ne peuvent donc pas être supprimés comme des fiches sans dépendance : une tentative peut être refusée avec un conflit `409`.

Pour arrêter l'utilisation sans perdre le suivi, l'administrateur peut **désactiver le compte**, et un rôle de gestion peut passer un équipement **Hors service** ou une demande **Clôturé**. Ces états conservent les relations et la chronologie. Corriger une observation ou une synthèse d'historique consiste à ajouter un événement explicite ; cela ne réécrit pas l'ancien.

## Mettre à jour une installation Windows

Arrêter l'application avec `ARRETER_TVM.cmd`. Remplacer les sources dans le dossier TVM déjà utilisé, en conservant **`.env`, `.local` et les données Docker**, puis relancer `INSTALLER_TVM.cmd` pour reconstruire l'application et appliquer les migrations.

Un nouveau dossier extrait n'est pas une nouvelle base indépendante. Si vous changez de dossier, récupérer d'abord la configuration de l'installation existante selon [le guide Windows](INSTALLATION_WINDOWS.md#mettre-à-jour-lapplication-sans-perdre-la-configuration). Ne pas supprimer les volumes Docker pour obtenir les nouvelles vues ou l'historique.

Les sources mises à jour ne copient pas la base du cloud sur le PC et ne reconstituent pas l'ancien historique HFSQL. Chaque instance affiche ses propres dossiers et événements enregistrés.

## Données privées et portée des vérifications

Les captures WINDEV reçues contiennent des clients réels et servent à comprendre le fonctionnement attendu. Elles ne sont pas incluses dans les sources publiques, les captures de démonstration ou l'archive de livraison. Le catalogue privé et les exports métier restent également hors du dépôt.

La présence d'une vue ou d'un rapport ne prouve pas que toutes les règles WINDEV binaires ont été converties. Les comportements reconstruits sont documentés et les résultats réellement vérifiés figurent dans [VALIDATION.md](VALIDATION.md).
