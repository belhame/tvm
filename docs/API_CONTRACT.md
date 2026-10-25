# Contrat de développement PowerCare / TVM

Application React TypeScript (frontend) + Django 5.2 / Django REST Framework (backend), PostgreSQL partagé. Authentification par sessions HttpOnly et protection CSRF. API sous `/api/`, même origine en production et proxy Vite en développement. Les listes métier de cette version ne sont pas paginées ; la liste des produits du catalogue Eaton est paginée.

## Session
- `GET /api/session/` → `{user: null | {id, username, first_name, last_name, email, role, client}, csrfToken}`.
- `POST /api/login/` avec `{username,password}` → `{user}` ; `POST /api/logout/`.
- Rôles : `admin`, `manager`, `technician`, `client`. Portail client : ses propres clients/équipements/dossiers/interventions/contrats/garanties/BL/rapports, lecture seule. Toutes les restrictions sont appliquées côté serveur. Aucun stock ni compte tiers ni note interne exposé au client.

## Ressources
Routes DRF avec slash final, listes JSON (tableaux), détail par ID, création POST, modification PATCH. Réponses d'erreur JSON, code HTTP conservé.
- `/api/clients/` : `id,name,contact_name,email,phone,address,city,postal_code,country,legacy_id`.
- `/api/equipment/` : `id,client,client_name,serial_number,brand,model,power_kva,location,commissioned_on,warranty_until,status,legacy_id`. Statuts `active,maintenance,inactive`.
- `/api/requests/` : `id,reference,equipment,equipment_serial,client_name,subject,description,priority,status,created_at,legacy_id`. Priorités `low,normal,high,urgent`. Statuts `new,scheduled,in_progress,resolved,closed`.
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

## Exécution
Backend `backend/manage.py`, réglages `config.settings`, application `core`. Serveur 8000, Vite 5173. Fichiers compilés `frontend/dist`, servis par Django via WhiteNoise. Base depuis `DATABASE_URL`, SQLite seulement avec `TVM_ALLOW_SQLITE=1` explicite pour tests isolés. Démo activée explicitement par `python manage.py seed_demo`; identités fictives signalées dans l'interface via `GET /api/session/` champ `demo_mode` issu de `TVM_DEMO_MODE`. Aucun identifiant HFSQL réel n'est inventé.

## Modèles attendus pour l'import
`Client`, `Equipment`, `ServiceRequest`, `Intervention`, `Part`, `StockMovement`, `Contract`, `Warranty`, `DeliveryNote`, `User`. Entités métier possèdent `legacy_id` texte nullable/unique pour conserver les identifiants originaux à côté des clés internes stables. Import en tables de staging d'abord : les liaisons HFSQL absentes de l'XML doivent être confirmées, jamais déduites silencieusement.
