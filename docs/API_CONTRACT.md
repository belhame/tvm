# Contrat de développement PowerCare / TVM

Application React TypeScript (frontend) + Django 5.2 / Django REST Framework (backend), PostgreSQL partagé. Authentification par sessions HttpOnly et protection CSRF. API sous `/api/`, même origine en production et proxy Vite en développement. Les listes métier de cette version ne sont pas paginées ; la liste des produits du catalogue Eaton est paginée.

## Session
- `GET /api/session/` → `{user: null | {id, username, first_name, last_name, email, role, client}, csrfToken}`.
- `POST /api/login/` avec `{username,password}` → `{user}` ; `POST /api/logout/`.
- Rôles : `admin`, `manager`, `technician`, `client`. Portail client : ses propres clients/équipements/dossiers/interventions/contrats/garanties/BL/rapports, lecture seule. Toutes les restrictions sont appliquées côté serveur. Aucun stock ni compte tiers ni note interne exposé au client.

## Ressources
Routes DRF avec slash final, listes JSON (tableaux), détail par ID, création POST, modification PATCH. Réponses d'erreur JSON, code HTTP conservé.
- `/api/clients/` : `id,name,contact_name,email,phone,address,city,postal_code,country,legacy_id`.
- `/api/equipment/` : `id,client,client_name,serial_number,brand,model,power_kva,location,commissioned_on,manufactured_on,catalogue_product,warranty_until,status,legacy_id`. Statuts `active,maintenance,inactive`. `manufactured_on` et `catalogue_product` sont en lecture seule dans ce CRUD ; leur création contrôlée passe par le parcours d'admission SAV. `catalogue_product` est absent des réponses du portail client.
- `/api/requests/` : `id,reference,equipment,equipment_serial,client_name,subject,description,priority,status,created_at,legacy_id,intake_key,intake_data`. Priorités `low,normal,high,urgent`. Statuts `new,scheduled,in_progress,resolved,closed`. Les métadonnées d'admission `intake_key` et `intake_data` sont en lecture seule et absentes du portail client.
- `/api/interventions/` : `id,reference,service_request,request_reference,equipment_serial,equipment_model,client_name,technician,technician_name,scheduled_at,duration_minutes,status,diagnosis,work_done,recommendations,internal_notes,completed_at,created_at,legacy_id`. Statuts `scheduled,in_progress,testing,completed,cancelled`. Les notes internes sont absentes du portail client. PDF : `GET /api/interventions/{id}/report/`. Pièces utilisées : `POST /api/interventions/{id}/use-part/` avec `{part,quantity}`.
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

## Exécution
Backend `backend/manage.py`, réglages `config.settings`, application `core`. Serveur 8000, Vite 5173. Fichiers compilés `frontend/dist`, servis par Django via WhiteNoise. Base depuis `DATABASE_URL`, SQLite seulement avec `TVM_ALLOW_SQLITE=1` explicite pour tests isolés. Démo activée explicitement par `python manage.py seed_demo`; identités fictives signalées dans l'interface via `GET /api/session/` champ `demo_mode` issu de `TVM_DEMO_MODE`. Aucun identifiant HFSQL réel n'est inventé.

## Modèles attendus pour l'import
`Client`, `Equipment`, `ServiceRequest`, `Intervention`, `Part`, `StockMovement`, `Contract`, `Warranty`, `DeliveryNote`, `User`. Entités métier possèdent `legacy_id` texte nullable/unique pour conserver les identifiants originaux à côté des clés internes stables. Import en tables de staging d'abord : les liaisons HFSQL absentes de l'XML doivent être confirmées, jamais déduites silencieusement.
