# Analyse consultative des numéros de série Eaton

## Source et périmètre

Le fichier fourni `eaton structure.xlsx` contient une feuille `Table 1` et neuf cellules renseignées. Il décrit une structure de sérialisation de produits et sous-ensembles. Il ne contient ni inventaire d'onduleurs, ni liste de clients, ni correspondance entre codes et usines ou modèles.

Cette information sert à proposer une lecture d'un numéro de série dans la fiche équipement et dans le scanner. L'analyse est **consultative** : elle ne modifie pas le numéro enregistré, le modèle, les dates ou la garantie de l'équipement. Un numéro d'un autre format reste autorisé dans l'application.

Le classeur joint n'est pas intégré aux sources ni importé comme un parc d'équipements. Cette évolution ne crée aucune table de base de données.

## Structure décrite

Le format décrit comporte dix caractères, répartis en cinq segments :

| Positions | Longueur | Segment | Interprétation disponible |
|---|---:|---|---|
| 1 | 1 | Code usine | Code conservé ; le nom de l'usine n'est pas fourni |
| 2–4 | 3 | Code produit | Code conservé ; aucune correspondance avec un modèle commercial n'est fournie |
| 5 | 1 | Code année | Référence de code uniquement ; l'année civile ne peut pas être calculée de façon fiable |
| 6–7 | 2 | Semaine | Valeur comprise entre `01` et `53`, conservée sur deux caractères |
| 8–10 | 3 | Ordre de fabrication | Séquence conservée telle quelle, sans conversion en entier ni compteur reconstitué |

Conserver les codes d'année, de semaine et de séquence comme du **texte** permet de garder les zéros initiaux et les lettres. Ces segments ne constituent pas à eux seuls une date complète de fabrication.

## Lettres exclues dans le document

| Segment | Lettres exclues |
|---|---|
| Usine | `I`, `O`, `Q`, `X` |
| Produit | `I`, `O`, `Q`, `S`, `U`, `X`, `Z` |
| Année | `I`, `O`, `Q`, `S`, `U`, `X`, `Z` |
| Ordre de fabrication | `I`, `O`, `Q`, `S`, `U`, `X`, `Z` |

Ces exclusions décrivent le format fourni. Un avertissement d'analyse ne prouve pas qu'un équipement est faux ou que son numéro doit être corrigé : d'autres générations et gammes peuvent utiliser d'autres formats.

Le code d'année reste alphanumérique dans cette aide : les exemples de lettres A et B ne suffisent pas à interdire les chiffres ni à définir un répertoire complet. Une compatibilité de structure ne valide donc pas la signification de ce code.

## Ambiguïtés à valider

Le document indique pour l'année « `A for201O,B for1011` ». La première valeur comporte un `O` ou un zéro ambigu, et la seconde est incohérente avec une progression annuelle attendue. L'application ne remplace donc pas ces mentions par une règle supposée telle que « A = 2010, B = 2011 ». Elle expose le code d'année sans calculer d'année civile.

La description de l'ordre de fabrication suit la forme « `000..999 puis A00..A99,B00..B99...Y99,AA0...` ». Elle laisse des ambiguïtés de lecture `O` / `0` et ne définit pas entièrement la progression, ses sauts ou ses limites. L'application ne calcule ni rang global de production ni prochain numéro à partir de cette description.

Il manque également les référentiels usine → nom d'usine et produit → modèle. Un code produit ne suffit pas à remplir automatiquement la marque ou le modèle de l'équipement. Une semaine de fabrication ne suffit pas à déterminer le début ou la fin d'une garantie.

## Utilisation dans l'application

Dans la fiche équipement ou le scanner, l'aide présente les cinq segments lorsque le numéro correspond à la structure décrite et signale les limites ou écarts rencontrés. Elle accompagne la saisie et la recherche sans les remplacer. La recherche d'un équipement continue d'appliquer les droits du compte connecté.

Le service d'analyse est disponible via `POST /api/serial-analysis/` après authentification. Il fournit une aide de lecture du texte transmis ; il n'importe pas d'équipement, ne met à jour aucun dossier et n'appelle aucune API Eaton. Les informations de la fiche restent sous le contrôle de l'utilisateur et des permissions métier habituelles.

L'utilisation de la caméra reste soumise aux conditions du [scanner sur téléphone](FONCTIONNALITES.md#scan-sur-téléphone) : navigateur compatible, autorisation caméra et HTTPS hors accès local. Une saisie manuelle permet aussi d'utiliser l'aide.

## Validation avant généralisation

Comparer cette lecture à des étiquettes réelles de plusieurs gammes et générations, puis faire confirmer par Eaton ou le référentiel technique autorisé :

- la portée exacte du format à dix caractères ;
- les tables de correspondance des usines et produits ;
- le codage de l'année, les cycles éventuels et les ambiguïtés du document ;
- la progression de l'ordre de fabrication et les lettres réellement exclues ;
- les éventuelles règles de date et de garantie, dans un référentiel distinct.

Ces confirmations permettront de faire évoluer l'aide avec des exemples vérifiés. Elles ne doivent pas entraîner de correction silencieuse des numéros existants.

## Mettre à jour une installation Windows existante

Arrêter l'application avec `ARRETER_TVM.cmd`. Extraire la nouvelle archive, puis copier son contenu dans le dossier TVM déjà utilisé, en acceptant le remplacement des fichiers. Conserver le fichier `.env`, le dossier `.local` et les données Docker de l'installation. Relancer `INSTALLER_TVM.cmd` depuis ce même dossier pour reconstruire et démarrer l'application. Le volume PostgreSQL existant est conservé ; cette mise à jour ne demande aucune réinitialisation de la base.

Voir le [guide Windows](INSTALLATION_WINDOWS.md) pour les lanceurs et les prérequis. Ne pas supprimer les volumes Docker pour appliquer cette évolution.
