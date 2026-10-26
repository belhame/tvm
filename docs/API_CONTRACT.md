# Contrat de développement PowerCare / TVM

Application React TypeScript (frontend) + Django 5.2 / Django REST Framework (backend), PostgreSQL partagé. Authentification par sessions HttpOnly et protection CSRF. API sous `/api/`, même origine en production et proxy Vite en développement. Les listes métier de cette version ne sont pas paginées ; la liste des produits du catalogue Eaton est paginée.

## Session
- `GET /api/session/` → `{user: null | {id, username, first_name, last_name, email, role, client}, csrfToken}`.
- `POST /api/login/` avec `{username,password}` → `{user}` ; `POST /api/logout/`.
- Rôles : `admin`, `manager`, `technician`, `client`. Portail client : ses propres clients/équipements/dossiers/interventions/contrats/garanties/BL/rapports, lecture seule. Toutes les restrictions sont appliquées côté serveur. Aucun stock ni compte tiers ni note interne exposé au client.

## Ressources
Routes DRF avec slash final, listes JSON (tableaux), détail par ID, création POST, modification PATCH. Réponses d'erreur JSON, code HTTP conservé.
- `/api/clients/` : `id,name,contact_name,tax_id,email,phone,address,city,postal_code,country,notes,legacy_id,created_at,equipment_count,open_requests_count,portal_users_count`. `tax_id` est un texte de 80 caractères ; `notes` est un texte interne de 4 000 caractères, absent du portail client. La date de création et les trois compteurs sont en lecture seule ; `portal_users_count` reste réservé aux comptes internes. `q` recherche dans le nom, le contact, le matricule fiscal, l'email, le téléphone et la ville.
- `/api/equipment/` : `id,client,client_name,serial_number,brand,model,power_kva,location,commissioned_on,manufactured_on,catalogue_product,warranty_until,status,legacy_id`. Statuts `active,maintenance,inactive`. `manufactured_on` et `catalogue_product` sont en lecture seule dans ce CRUD ; leur création contrôlée passe par le parcours d'admission SAV. `catalogue_product` est absent des réponses du portail client.
- `/api/requests/` : `id,reference,call_number,equipment,equipment_serial,client_name,subject,description,priority,status,assigned_technician,assigned_technician_name,due_on,arrived_at,closed_at,timing,category,is_overdue,is_due_overdue,created_at,legacy_id,intake_key,intake_data`, complétés par les champs de suivi, dont `client_reference`, ci-dessous. Priorités `low,normal,high,urgent`. Statuts métier `new,maintenance,testing,resolved,quotation,pending,approved,rejected,exchange,closed` ; les anciennes valeurs `scheduled` et `in_progress` restent acceptées pour compatibilité et sont classées respectivement dans `pending` et `maintenance`. `call_number`, `assigned_technician_name`, `timing`, `category`, `is_overdue` et `is_due_overdue` sont calculés en lecture seule. Les métadonnées d'admission `intake_key` et `intake_data` sont en lecture seule et absentes du portail client.
- `/api/interventions/` : `id,reference,service_request,request_reference,call_number,client_reference,equipment_serial,equipment_model,client_name,technician,technician_name,scheduled_at,duration_minutes,status,diagnosis,work_done,recommendations,internal_notes,completed_at,created_at,legacy_id`, complétés par les champs de fiche structurée ci-dessous. `request_reference`, `call_number` et `client_reference` sont des valeurs liées en lecture seule. Statuts `scheduled,in_progress,testing,completed,cancelled`. Les notes internes sont absentes du portail client. PDF : `GET /api/interventions/{id}/report/`. Pièces utilisées : `POST /api/interventions/{id}/use-part/` avec `{part,quantity}`.
- `/api/users/` : admin CRUD `id,username,first_name,last_name,email,role,client,is_active,password` (password écriture seulement). Autres internes : lecture liste limitée aux employés actifs pour affectation, aucun compte client. Client : interdit.
- `/api/parts/` : `id,sku,name,category,unit_price,stock_quantity,min_stock,legacy_id`. Quantité initiale zéro ; le stock s'ajuste via mouvements. Catégories `battery,board,ventilation,other`.
- `/api/stock-movements/` : `id,part,part_name,quantity,kind,reference,intervention,created_at` ; POST atomique (quantité signée : entrée positive, sortie négative) sans stock négatif. Types `in,out,adjustment`.
- `/api/contracts/` : `id,number,client,client_name,equipment,starts_on,ends_on,coverage,visits_per_year,status,legacy_id`. Statuts `active,expired,draft`.
- `/api/warranties/` : `id,equipment,equipment_serial,client_name,provider,starts_on,ends_on,terms,legacy_id`.
- `/api/delivery-notes/` : `id,reference,client,client_name,intervention,delivered_at,status,notes,lines,legacy_id` ; lignes imbriquées `{part,description,quantity}`. Statuts `draft,ready,delivered`. Le BL documente une livraison ; le stock est débité une seule fois explicitement via les mouvements.
- `/api/audit/` : lecture admin/manager.
- `/api/integrations/` : état réel WhatsApp/IA, indisponibles sans accès ; aucune réponse simulée.
- `/api/search/?q=...` : recherche autorisée `{equipment,clients,requests,interventions}`.
- `POST /api/serial-analysis/` : analyse consultative du format Eaton décrit dans le classeur fourni, avec `{serial_number: string}` (1–120 caractères), session et CSRF obligatoires. Réponse `{status: "matches" | "not_applicable", normalized_serial_number, rule_id, source, segments: null | {manufacturing_location_code, product_identification_code, year_code, week_code, week_number, unit_order_code}, calendar_year: null, warnings: string[]}`. Aucune recherche d'équipement ni écriture ; un résultat compatible n'authentifie pas le matériel. Voir [les règles et leurs limites](NUMEROS_SERIE_EATON.md).
- `/api/dashboard/` : `{metrics:{active_interventions,open_requests,critical_stock,equipment_count,client_count,completed_interventions},recent_interventions:[],activity:[{label,interventions,requests}],status_distribution:[{name,value}],upcoming:[]}`. Données réellement en base et filtrées par utilisateur.

## Import d'annuaire clients

`POST /api/clients/import/` est réservé aux administrateurs et responsables, avec session et CSRF. Formulaire multipart : `file` CSV et `mode: "preview" | "apply"` (`preview` par défaut). Le fichier est limité à **2 Mio et 5 000 lignes**, encodé en UTF-8 avec ou sans BOM, séparé par `;` ou `,`.

En-têtes autorisés : `name`, `contact_name`, `tax_id`, `email`, `phone`, `address`, `city`, `postal_code`, `country`, `notes`. Seul `name` est obligatoire. Un pays absent reste vide. Les colonnes inconnues, notamment d'anciens identifiants ou mots de passe, ne sont pas acceptées. Aucun compte ni accès portail n'est créé ou modifié.

La réponse HTTP `200` fournit notamment `sha256`, les `rows` avec `status: create | existing | duplicate | conflict | invalid` et une liste `errors`, ainsi qu'un `summary` contenant `total`, `create`, `existing`, `duplicate`, `conflict`, `invalid`, `created`, `skipped`. `preview` n'écrit rien. `apply` crée seulement les lignes saines et nouvelles ; les conflits et lignes invalides sont ignorés et signalés, sans bloquer à eux seuls toutes les autres lignes. Le formulaire peut transmettre le `sha256` de prévisualisation pour vérifier que le fichier n'a pas changé ; l'interface le fait.

L'idempotence repose sur les données : nom comparé après normalisation Unicode, espaces et casse, sans rapprochement approximatif. Un nom déjà présent n'est jamais écrasé ; des valeurs renseignées contradictoires sont des conflits, et une donnée nouvelle pour un champ existant vide entraîne un avertissement de complétion manuelle. Un même matricule fiscal sous un autre nom est un conflit ; l'email seul n'est pas une identité. Des lignes de même nom contradictoires dans le fichier sont toutes signalées en conflit.

Erreurs principales : `400` pour un fichier ou une empreinte invalide, `413` pour la taille, `403` pour le rôle. Commande serveur : `python manage.py import_clients FILE --actor USER` simule ; ajouter `--apply` active les créations. L'acteur actif administrateur ou responsable est obligatoire dans les deux modes. Voir [le guide d'import](GUIDE_SUIVI_SAV.md#annuaire-clients-et-import-csv).

## Numéro TVM, référence du centre client et visites

Le numéro métier du dossier est `ServiceRequest.reference`, également exposé en lecture seule sous `call_number`. Il correspond au libellé **N° d'intervention / appel TVM** et reste commun aux visites liées par `Intervention.service_request`. `Intervention.reference` demeure la **Réf. de visite** secondaire `INT-…` ; aucune fusion des visites n'est effectuée. Sur une visite, `request_reference` et `call_number` reflètent le numéro du dossier, et `client_reference` reflète sa référence centre.

Les nouvelles demandes reçoivent un numéro `YY-NNNNN`, année locale selon `TVM_TIMEZONE`, séquence annuelle sur cinq chiffres. L'allocation est transactionnelle, avec verrouillage de la séquence en PostgreSQL. Le plus grand numéro déjà stocké au format exact du même préfixe annuel est réservé pour éviter une collision. Les anciennes références ne sont pas modifiées. La séquence ne prend aucune valeur depuis une capture d'écran ou un exemple documentaire.

Après `99999`, la création est refusée avec HTTP `400` pour intervention administrative ; il n'y a ni bouclage ni passage implicite à six chiffres. Le client API ne choisit pas ce numéro serveur. Un rejeu idempotent de l'admission conserve le même dossier et le même numéro.

`client_reference` est une chaîne de 120 caractères maximum représentant le numéro du centre SAV ou de l'organisation cliente. Zéros initiaux, lettres, `/` et `-` sont conservés comme texte. Ce champ n'est pas unique globalement : une même référence peut appartenir à plusieurs centres. Il ne remplace ni la clé primaire, ni le numéro TVM, ni la relation client qui définit les droits.

`GET /api/requests/` et `GET /api/interventions/` acceptent les filtres `call_number` et `client_reference`, ainsi que `q`, limités à 200 caractères. Ces filtres recherchent des fragments sans distinction de casse, dans le périmètre autorisé. La recherche globale `GET /api/search/?q=...` inclut les deux numéros ; avec un seul caractère, seuls les numéros exactement correspondants sont recherchés, sans recherche générale par fragment. À partir de deux caractères, les recherches générales par fragment restent disponibles.

Les relations client sont appliquées avant la recherche : un compte de centre ne découvre pas le dossier d'un autre centre possédant le même numéro. Aucun client n'est déduit du préfixe ou du contenu d'une référence. Voir [le guide des deux numéros](GUIDE_SUIVI_SAV.md#identifier-un-dossier-avec-les-deux-numéros).

## Catalogue Eaton BN

Session obligatoire sur toutes les routes. Administrateur et responsable SAV : lecture et import ; technicien : lecture seule ; client : accès refusé. Le catalogue reste interne et distinct du portail client.

- `GET /api/catalogue/` : résumé de la version active `{available,active_import,counts,structures,year_tables,warnings}`. `active_import` est `null` si aucun catalogue n'est actif, sinon contient notamment `{id,filename,sha256,imported_at,imported_by,imported_by_name,product_count,warranty_count,is_active,metadata}`. `counts` contient `{products,warranties,year_mappings,na_codes,duplicate_code_groups}`. Les correspondances d'années indiquent leur structure et leur provenance source ; elles ne modifient pas les équipements.
- `GET /api/catalogue/products/` : liste de la version active, réponse `{count,next,previous,results,page,page_size}`. Paramètres `page`, `page_size` (50 par défaut, 100 maximum), `q` et `structure`. `next` et `previous` sont des URL ou `null`. Les lignes conservent leur provenance et les indicateurs `code_is_usable` / `code_is_ambiguous` ; une entrée `NA` n'est pas un code exploitable et une collision n'est pas résolue arbitrairement.
- `GET /api/catalogue/warranties/` : tableau non paginé distinct des produits, avec `{scope,category,product_name,brand_group,duration_text,duration_months,conditions,source_sheet,source_row,source_column,raw_data}`. Ces références de garantie ne mettent pas à jour les garanties métier.
- `POST /api/catalogue/import/` : téléversement multipart avec un champ `file`, fichier XLS limité à **8 Mio** ; session et CSRF obligatoires. Réservé aux administrateurs et responsables SAV. Nouveau SHA-256 : HTTP `201`, `created: true`. Fichier connu : HTTP `200`, `created: false`, `already_imported: true` ; `activated: true` lorsqu'une ancienne version est réactivée, sans duplication. Réimporter le fichier déjà actif ne change pas la version active.

Les métadonnées de version comprennent notamment la révision et sa date lues dans le classeur, les feuilles, le format source, l'empreinte et les contrôles de contenu. Sans catalogue actif, le résumé renvoie HTTP `200`, `available: false`, `active_import: null`, des compteurs à zéro et des listes vides.

Une seule version est active. L'import valide le classeur et conserve la provenance des lignes, puis active l'ensemble dans une transaction ; les entrées `NA` et les collisions restent distinctes. Aucune création ou modification de client, d'équipement, de date ou de garantie n'est déclenchée. L'ancien `POST /api/serial-analysis/` garde son périmètre consultatif et ne devient pas un décodeur universel des quatre profils.

Commande d'administration : `python manage.py import_eaton_catalogue FILE --validate-only` valide sans acteur ni écriture ; `python manage.py import_eaton_catalogue FILE --actor admin` importe, avec un acteur actif administrateur ou responsable obligatoire. Voir [l'import sur chaque instance et les contrôles attendus](IMPORT_CATALOGUE_EATON.md).

## Demande SAV à partir d'une série

Ces deux routes utilisent la session et le jeton CSRF. Elles sont internes : les comptes clients reçoivent un refus d'accès. L'import du catalogue, la recherche et l'enregistrement sont des opérations distinctes.

### Recherche sans écriture

`POST /api/serial-lookup/` est accessible aux administrateurs, responsables SAV et techniciens. Corps JSON :

| Champ | Usage |
|---|---|
| `serial_number` | Chaîne obligatoire, au plus 120 caractères |
| `profile` | Profil facultatif pour préciser le format |
| `catalogue_import_id` | Version du catalogue à utiliser |
| `product_id` | Choix explicite d'un produit parmi les candidats |
| `warranty_reference_id` | Choix explicite d'une référence de garantie |

La réponse fournit notamment `{catalogue_import_id,catalogue_import,existing_equipment,history,product_candidates,selected_product,detection,manufactured_on,manufacture_date_basis,warranty_options,selected_warranty,default_warranty_id,computed_warranty,recorded_warranties,active_contracts,warnings}`. `history` regroupe les demandes et interventions ; la base existante reste prioritaire. Les options de garantie indiquent leur portée, durée, provenance, type de correspondance et calcul éventuel.

`computed_warranty` indique notamment `{status,starts_on,ends_on,duration_months,warranty_id,coverage_status,rule}`. `status` vaut selon le cas `estimated`, `recorded_priority`, `needs_choice`, `manufacture_unknown` ou `unavailable` ; `coverage_status` vaut `active`, `expired`, `not_started` ou `unknown`. Les dates sont ISO ou absentes lorsque le calcul n'est pas possible. La règle retournée par le calcul de référence est `{code: "manufacture_monday_plus_6_calendar_months", start_offset_months: 6}` : **fabrication + six mois calendaires**, puis la durée retenue pour la fin ; les jours inexistants sont ramenés à la fin du mois.

`manufacture_date_basis` fournit `{source,type,precision,reconstructed,blocked_reason}`. Cette base et les avertissements signalent notamment le lundi ISO lorsqu'une année/semaine permet cette convention. Une date NV limitée au mois, une année DX dont le cycle est ambigu ou une référence reconditionnée non établie ne génèrent pas de fausse date exacte. Une garantie estimée n'est pas présentée comme une garantie enregistrée ou certifiée par Eaton.

Le modèle peut être sélectionné automatiquement si le produit est unique pour le profil et le code. Une référence de garantie n'est proposée automatiquement que si sa correspondance de gamme est exacte et unique après le seul retrait du suffixe de lancement prévu. Il n'y a ni rapprochement approximatif, ni choix automatique de la durée la plus longue. L'équipement existant, ses garanties et ses contrats ne sont pas modifiés. Aucun appel à une API Eaton n'est effectué.

### Enregistrement transactionnel

`POST /api/requests/intake/` crée le dossier. Administrateur ou responsable : nouvel équipement autorisé ; technicien : demande liée à un équipement existant uniquement.

| Champ JSON | Règle |
|---|---|
| `request_key` | UUID obligatoire identifiant la soumission |
| `serial_number` | Chaîne obligatoire, au plus 120 caractères |
| `subject` | Objet obligatoire, au plus 200 caractères |
| `description` | Texte facultatif |
| `priority` | `low`, `normal`, `high` ou `urgent` ; `normal` par défaut |
| `arrived_at` | Horodatage d'arrivée ISO ou `null`, renseigné explicitement ; aucune déduction depuis la création de la fiche |
| `equipment` | Identifiant facultatif d'un équipement existant ; doit correspondre à la série |
| `client` | Identifiant client obligatoire pour un nouvel équipement ; doit correspondre au client d'un équipement existant s'il est fourni |
| `profile`, `catalogue_import_id`, `product_id`, `warranty_reference_id` | Contexte et choix de catalogue contrôlés à nouveau côté serveur |
| `manual_model` | Modèle manuel, au plus 120 caractères, avec justification |
| `manufactured_on_override` | Date de fabrication manuelle ISO `YYYY-MM-DD`, avec justification |
| `duration_months_override` | Durée manuelle entière de 0 à 1 200 mois, avec justification |
| `manual_reason` | Raison nécessaire pour les valeurs manuelles |
| `warranty_start_override` | Date ISO facultative ; acceptée uniquement si elle égale fabrication + six mois calendaires, sans autre décalage autorisé |

Le serveur recalcule la recherche ; une sélection ambiguë n'est jamais remplacée par le premier candidat. Pour un nouvel équipement, sa création, celle de la demande et celle d'une garantie calculable sont atomiques. Une garantie n'est créée par cette route que pour un nouvel équipement avec une date et une durée retenues. Pour un équipement existant, modèle, garanties et contrats restent inchangés.

Réponse HTTP `201` lors d'une création, HTTP `200` lors du rejeu identique : `{created,request,equipment,created_equipment,warranty,intake}`. Le même UUID, pour le même acteur et le même contenu normalisé, retourne la même demande. Réutiliser cette clé avec un autre contenu ou un autre acteur entraîne un conflit générique sans révéler le dossier concerné. Erreurs principales : `400` pour une validation, `403` pour un rôle interdit et `409` pour un conflit de clé ou de série concurrente.

Voir [le parcours utilisateur, la règle des six mois et les limites par profil](PARCOURS_DEMANDE_SERIE.md). Les noms de procédures retrouvés dans les fichiers WINDEV ne constituent pas une conversion des corps WLangage binaires.

## Classement des demandes et historique métier

### Catégories et filtres

`GET /api/requests/?category=...` accepte `unassigned`, `maintenance`, `testing`, `overdue`, `processed`, `quotation`, `pending`, `approved`, `rejected`, `exchange`, `closed` ou `all`. Les catégories principales suivent les états du dossier : `unassigned` correspond à `new`, `processed` à `resolved`, `pending` inclut aussi l'ancien `scheduled` et `maintenance` inclut l'ancien `in_progress`. Le paramètre `status` filtre un état exact. `q` recherche dans les deux numéros de dossier, le sujet, la série et le client.

`GET /api/requests/categories/` retourne `{categories: [{key,label,count}], total, as_of}` dans le périmètre autorisé. `overdue` et `is_overdue` correspondent au chronomètre en cours dépassant strictement 48 heures cumulées du lundi au vendredi ; ce n'est pas une valeur de `status`. Ce compteur peut recouper d'autres catégories. `is_due_overdue` décrit séparément le dépassement d'une échéance `due_on` manuelle. `assigned_technician` et `due_on` sont modifiables par administrateur ou responsable via le CRUD des demandes.

La combinaison `status: "new"` et `assigned_technician` non nul est refusée, y compris lors d'une transition d'état par la chronologie : une demande affectée ne peut pas rester classée Non affecté.

Le parcours `POST /api/requests/intake/` conserve son contrat de création par série ; les nouveaux états, l'affectation et l'échéance se règlent ensuite via la modification du dossier par un rôle autorisé. Ces nouveaux champs ne sont pas ajoutés implicitement au contenu idempotent de l'admission.

### Arrivée, clôture et durée

`arrived_at` est un horodatage ISO explicite ou `null`, accepté lors de l'admission et du POST/PATCH des demandes. Il n'est jamais rempli avec `created_at` par défaut. Les anciennes fiches sans arrivée restent inconnues pour le calcul.

La réponse des listes et détails comporte `timing: {timer_state,elapsed_hours,elapsed_days,is_overdue_48h,threshold_hours,clock_basis,timezone,as_of,warning}`. `timer_state` vaut `unknown`, `running` ou `closed` ; les durées sont `null` si elles ne sont pas connues. `elapsed_days` compte les blocs complets de 24 heures cumulées. `threshold_hours` vaut `48` et `clock_basis` vaut `business_hours_excluding_weekends`.

Le calcul utilise le fuseau `TVM_TIMEZONE` et exclut samedi/dimanche. Les jours fériés et les plages d'heures de bureau ne sont pas retirés. Le seuil est strict : 48 heures exactes ne constituent pas un dépassement. Une arrivée vendredi 10 h atteint 24 heures lundi 10 h, 48 heures mardi 10 h, puis dépasse le seuil après mardi 10 h.

`closed_at` est automatiquement enregistré lors du passage à `closed`, conservé lors d'une simple édition et effacé en cas de réouverture. Un administrateur ou responsable peut compléter une ancienne clôture manquante avec une date passée, postérieure ou égale à l'arrivée. Le compteur s'arrête à la clôture ; son indicateur rouge historique peut rester vrai, sans inclure cette demande dans le dépassement en cours.

Seul `closed` arrête le chronomètre. Les demandes `resolved` ou `rejected` restent en cours pour ce calcul jusqu'à leur clôture. Après une clôture tardive, `timing.is_overdue_48h` peut rester `true` tandis que `is_overdue` est `false`. La migration ne renseigne aucune arrivée ni clôture historique supposée.

### Champs de la fiche de suivi

Les demandes et leur admission acceptent les champs de suivi ci-dessous, en plus de `arrived_at` :

| Champ | Type et limite |
|---|---|
| `client_reference` | N° d'appel du centre client, texte conservé, 120 caractères, sans unicité globale |
| `end_customer` | Texte, 200 caractères |
| `return_flag` | Booléen JSON strict |
| `packaging` | Texte, 250 caractères |
| `service_location` | Vide, `workshop`, `depot` ou `onsite` |
| `delivered_by` | Vide, `courier` ou `client` |
| `courier_name` | Texte, 150 caractères |
| `accessories` | Texte, 4 000 caractères |
| `warranty_status` | `unspecified`, `warranty`, `quotation`, `contract` ou `billable` |
| `contact_name` | Texte, 150 caractères |
| `contact_phone` | Texte, 40 caractères |
| `contact_email` | Adresse email valide, 254 caractères maximum |

Ces données sont saisies pour le dossier ; `warranty_status` n'est pas une décision automatique de garantie ou une facturation. Une arrivée future est refusée. Une arrivée ou clôture absente reste inconnue pour le compteur.

`GET /api/requests/{id}/report/` génère la fiche de suivi PDF du dossier autorisé, avec réception, arrivée/clôture, durée calculée, historique public, synthèses et références d'intervention. Cette route est distincte du rapport d'intervention `GET /api/interventions/{id}/report/` ; les informations internes ne sont pas imprimées dans le document partagé. Les deux PDF sont privés et servis avec `Cache-Control: private, no-store`.

Les deux en-têtes affichent **N° d'intervention / appel TVM** (`ServiceRequest.reference`) et **N° d'appel client** (`client_reference`). Les références `INT-…` sont identifiées comme **Réf. de visite**. Une référence client vide est imprimée « Non renseigné » ; les valeurs non vides restent textuelles.

### Chronologies

`GET /api/requests/{id}/timeline/` et `GET /api/equipment/{id}/timeline/` retournent directement un tableau d'événements : `{id,equipment,equipment_serial,related_equipment,related_equipment_serial,service_request,request_reference,intervention,intervention_reference,kind,actor_name,created_at,recorded_created_at,status_before,status_after,observation,summary,is_internal,source}`. L'historique équipement couvre les événements qui lui sont rattachés, y compris comme matériel lié d'un échange. Les clients sont limités à leur société et aux événements publics ; leur réponse présente l'auteur sous le libellé « Équipe SAV ».

Les événements sont immuables par ces API. Une synthèse est un événement `kind: "summary"`, pas un champ mutable qui remplacerait les synthèses passées. Les notes sont internes par défaut ; une transition d'état publique ne doit pas exposer une note interne. Un technicien ajoute des notes uniquement sur les dossiers de son périmètre d'affectation. Les comptes clients n'ont aucun droit de publication d'événement.

PostgreSQL bloque également les mises à jour et suppressions d'événements par un trigger. Les relations protégées vers les comptes auteurs, équipements et dossiers peuvent faire refuser leur suppression avec HTTP `409`. Utiliser la désactivation d'un compte ou les états métier de fin d'utilisation pour conserver les références.

`POST /api/requests/{id}/timeline/` accepte une note `kind: "observation"` ou `kind: "summary"`, avec au moins un texte non vide `observation` / `summary` limité à 10 000 caractères, ou une transition `kind: "status_changed"` avec `status_after` et une note facultative. Répéter l'état courant est refusé. `is_internal` est un booléen strict, interne par défaut pour les notes. Administrateurs, responsables et techniciens dans leur périmètre d'affectation peuvent publier ; les techniciens ne gagnent pas pour autant le droit de modifier l'affectation ou l'échéance du dossier. La transition reste publique ; une note interne qui l'accompagne est enregistrée comme événement privé distinct. Une création d'événement retourne HTTP `201`.

`POST /api/equipment/{id}/timeline/` permet les observations et synthèses sur l'équipement, même sans dossier, mais refuse `status_changed`. Ce point d'entrée n'accepte pas de référence arbitraire à un autre dossier. L'auteur et la date proviennent du serveur ; le libellé de l'auteur est conservé pour éviter de réécrire l'historique lors d'un renommage de compte.

Les événements d'état de référence utilisent `source: "baseline"`. Leur `created_at` correspond à l'enregistrement de la baseline lors de la migration, et non à une ancienne action métier. L'état courant repris et une éventuelle ancienne date de création ont une valeur de contexte ; ils ne prouvent pas un changement ou une intervention à cette date. Les anciens journaux HFSQL restent en dehors de cette chronologie tant qu'une reprise spécifique n'a pas été réalisée.

Voir [le guide de suivi et ses limites](GUIDE_SUIVI_SAV.md). L'accès au journal technique `/api/audit/` demeure une fonction distincte pour administrateurs et responsables.

### Fiches d'intervention structurées

Les routes CRUD existantes `/api/interventions/` et `/api/interventions/{id}/` portent les fiches. Elles ajoutent `kind`, `performed_on`, `replacement_equipment`, `contract`, `extension_warranty`, `cabinet_serial`, `battery_count`, `site`, `end_customer`, `contact_name`, `contact_phone`, `summary`, `conclusion`, `conclusion_notes` et `structured_data`.

Les valeurs liées sont également exposées en lecture seule : `replacement_equipment_serial`, `contract_number`, `contract_starts_on`, `contract_ends_on`, `extension_starts_on`, `extension_ends_on` et `extension_scope`.

`GET /api/interventions/?kind=maintenance|exchange|commissioning|preventive` filtre le type de fiche dans le périmètre autorisé ; une valeur inconnue est refusée. Ce type est distinct du statut `exchange` d'une demande.

Un technicien ne crée une intervention que dans son périmètre d'affectation au dossier et ne l'affecte qu'à lui-même. Une première intervention exige donc l'affectation préalable du dossier par le responsable ; la création n'accorde pas automatiquement des droits sur un dossier tiers.

La création d'une intervention ou un changement réel de son `status` peut recalculer l'état agrégé de la demande. Une simple modification de diagnostic ne le fait pas. Les états de gestion `quotation`, `pending`, `approved`, `rejected`, `exchange` et `closed` sont conservés. La compatibilité des anciens états `new`, `scheduled`, `in_progress` et `resolved` reste distincte des demandes passées explicitement dans les états canoniques `maintenance` ou `testing`.

`kind` vaut `maintenance`, `exchange`, `commissioning` ou `preventive`. `performed_on` est une date réelle, jamais future ; la planification demeure `scheduled_at`. Une fiche non maintenance terminée exige `performed_on`. Un échange terminé exige aussi un `replacement_equipment` différent du matériel d'origine et rattaché au même client. Ce champ est interdit pour les autres types. Le dossier reste lié à l'équipement d'origine.

`contract` doit concerner le client et l'équipement d'origine, ou être global à ce client. `extension_warranty` doit concerner l'équipement d'origine. `battery_count` est un entier de 0 à 100 000. `summary` est limité à 10 000 caractères ; `conclusion_notes` à 4 000. La conclusion est vide ou vaut `follow_up`, `completed`, `not_applicable_billable` ; ce dernier choix impose une justification dans `conclusion_notes`. Il n'entraîne pas de facturation automatique.

`structured_data` est un objet validé strictement. **Lors d'un PATCH, la valeur fournie remplace l'objet entier** ; le client API doit conserver les sections voulues, pas envoyer une sous-clé en supposant une fusion serveur. Sections autorisées :

| Section | Cases booléennes JSON autorisées |
|---|---|
| `maintenance` | `battery_failure`, `electronics_failure`, `overload`, `overvoltage`, `overheating`, `replace_batteries`, `configure`, `replace_board`, `replace_ups`, `recover_ups`, `repair_board` |
| `commissioning` | `electrical_protection`, `cable_section`, `configure`, `connection`, `power_on`, `normal_operation_test`, `runtime_test`, `bypass_test`, `alarm_test` |
| `preventive` | `environment`, `power_cables`, `alarm_history`, `runtime_test`, `bypass_test`, `alarm_test`, `dusting` |

Chaque section accepte aussi un `comment` texte de 4 000 caractères maximum. `maintenance` accepte `battery_replaced_count`, entier de 0 à 100 000 ; un nombre positif exige `replace_batteries: true`, et un remplacement déclaré sur une intervention terminée exige un nombre positif. Les clés inconnues, nombres à la place de booléens et sections non prises en charge sont refusés. La fiche d'échange utilise ses champs dédiés, pas une section libre `exchange` dans cet objet.

Une case absente signifie « non renseignée » ; une valeur booléenne `false` signifie « explicitement non cochée ». Les fiches existantes ne sont pas remplies avec des contrôles ou conclusions supposés.

`GET /api/interventions/{id}/report/` reprend les champs structurés connus, les références liées, les séries ancien/nouveau matériel, la synthèse et la conclusion. Les cases connues distinguent `[X]` / `[ ]` / `[-]` pour cochée / non cochée / non renseignée. Les visas ou signatures non recueillis ne sont pas présentés comme acquis. Les textes longs sont conservés dans le document, au besoin en annexes. Les notes internes et les clés JSON inconnues ne sont pas imprimées. Une case ne modifie pas automatiquement le stock, les contrats, les garanties ou les fiches équipements.

### Objectif et réalisation des visites préventives

`ServiceRequest.planned_visit_count` est un entier nullable de 1 à 1 000. Administrateurs et responsables peuvent le définir par POST/PATCH de demande ou lors de l'admission. Sur une intervention, ce champ est un alias lié en lecture seule.

Demandes et interventions exposent en lecture seule `preventive_completed_visit_count`, `preventive_total_visit_count` et `preventive_remaining_visit_count`. Le calcul porte uniquement sur les interventions du **même dossier** : `kind=preventive` et `status=completed` pour les terminées ; `kind=preventive` hors `cancelled` pour le total enregistré ; reste = `max(prévues - terminées, 0)`. Sans objectif, `planned_visit_count` et le reste sont `null`, tandis que les compteurs réels restent des entiers. Les autres types d'intervention et les autres dossiers du même équipement ne sont pas inclus.

Renseigner un objectif ne crée aucune visite, planification, garantie ou contrat. Les anciens objectifs restent inconnus ; les visites déjà déclarées terminées peuvent compter sans leur inventer une date de réalisation. Les numéros TVM et références de visite restent inchangés. Le PDF préventif affiche cette progression ; la mise en service conserve son récapitulatif dédié de matériel, lieu, contact et date connue.

### Pièces jointes privées des demandes

`GET /api/requests/{id}/documents/` retourne `{results,can_upload,max_file_size,allowed_extensions,virus_scanned}`. Chaque document contient `{id,service_request,label,original_name,mime_type,size_bytes,sha256,client_visible,uploaded_by_name,created_at,can_delete,download_url}`. Les clients ne reçoivent que les documents partagés de leurs propres dossiers ; leur libellé d'auteur est « Équipe SAV ». Les chemins de stockage privés ne sont pas exposés.

`POST /api/requests/{id}/documents/` accepte un formulaire multipart avec exactement un champ `file`, `label` facultatif de 200 caractères maximum et `client_visible` valant exactement la chaîne `true` ou `false` (`false` par défaut). Administrateurs, responsables et techniciens affectés au dossier ou à l'une de ses interventions peuvent ajouter un document. Les comptes clients n'ont pas ce droit.

Le fichier doit être non vide, limité à **10 Mio**, dans les formats PDF, JPEG, PNG, DOCX, XLSX ou TXT. Le serveur contrôle la taille et le format ; `virus_scanned` reste `false`, sans garantie antivirus. La réponse est HTTP `201` avec les métadonnées du document. Un dépassement renvoie `413`, une validation de contenu `400`, un rôle interdit `403` et une ressource inaccessible `404`.

Des bornes de contenu complètent la limite d'octets : PDF de 1 à 500 pages, images de 25 millions de pixels au plus, fichiers Office sans macros avec au plus 2 000 entrées ZIP et 40 Mio de contenu décompressé. La validation Office n'extrait pas les documents sur le serveur.

`GET /api/documents/{id}/download/` vérifie à nouveau les droits et transmet le fichier en téléchargement, avec les protections de cache privé et `nosniff`. Aucun accès direct public à `MEDIA_ROOT` n'est fourni. Les fichiers sont nommés par UUID côté stockage, distinctement de leur nom original.

`DELETE /api/documents/{id}/` est réservé aux mêmes rôles d'écriture sur le dossier. Le document est retiré immédiatement de la consultation et la suppression est tracée. HTTP `204` confirme également la suppression physique ; HTTP `202` indique que cette dernière est en attente de reprise. La commande d'administration `python manage.py purge_request_documents` reprend les suppressions physiques déjà demandées. Les événements historiques de ces opérations restent conservés.

Les fichiers sont conservés dans `MEDIA_ROOT` (`backend/media` par défaut, volume Docker `tvm_media` dans l'installation conteneurisée). Sauvegarder et restaurer la base et les fichiers ensemble : voir [le déploiement](DEPLOIEMENT.md#sauvegarder).

## Exécution
Backend `backend/manage.py`, réglages `config.settings`, application `core`. Serveur 8000, Vite 5173. Fichiers compilés `frontend/dist`, servis par Django via WhiteNoise. Base depuis `DATABASE_URL`, SQLite seulement avec `TVM_ALLOW_SQLITE=1` explicite pour tests isolés. Démo activée explicitement par `python manage.py seed_demo`; identités fictives signalées dans l'interface via `GET /api/session/` champ `demo_mode` issu de `TVM_DEMO_MODE`. Aucun identifiant HFSQL réel n'est inventé.

## Modèles attendus pour l'import
`Client`, `Equipment`, `ServiceRequest`, `Intervention`, `Part`, `StockMovement`, `Contract`, `Warranty`, `DeliveryNote`, `User`. Entités métier possèdent `legacy_id` texte nullable/unique pour conserver les identifiants originaux à côté des clés internes stables. Import en tables de staging d'abord : les liaisons HFSQL absentes de l'XML doivent être confirmées, jamais déduites silencieusement.
