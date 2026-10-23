# Validation de la version livrée

Contrôles exécutés le **22 octobre 2026** dans l'environnement cloud, sur PostgreSQL 16 et Chromium 154. Les données utilisées sont fictives. Le serveur et les données de démonstration sont distincts de la base réservée aux essais navigateur.

| Contrôle exécuté | Résultat |
|---|---|
| `bash scripts/setup.sh --demo` | Installation puis répétition réussies ; `.env` strictement conservé, démo et données préservées, migrations et compilation réussies |
| `bash scripts/test.sh` | **52 tests réussis, 0 échec, 0 ignoré**, base PostgreSQL de test supprimée ; TypeScript et compilation Vite réussis |
| `bash scripts/e2e.sh` | **5 scénarios navigateur réussis**, base séparée `tvm_e2e` |
| `npm audit --json` dans `frontend/` | Aucun avis de vulnérabilité signalé par le registre lors du contrôle |
| Sauvegarde / restauration | Dump PostgreSQL restauré dans une base distincte ; volumes, connexion, tableau de bord et PDF vérifiés ; base temporaire supprimée |
| Image Docker | Construction complète, exécution non privilégiée, connexion PostgreSQL, SPA et assets, session/CSRF, tableau de bord et PDF vérifiés |
| Distribution statique | Fichiers compilés hôte / image comparés par SHA-256 et identiques ; HTML sans cache durable, API privées `no-store` |

## Ce que couvrent les tests

Les 52 tests serveur comprennent 21 contrôles d'import HFSQL, 21 contrôles métier et de permissions, 5 contrôles d'authentification/CSRF, 3 contrôles d'initialisation démo et 2 contrôles de concurrence PostgreSQL. Ils exercent notamment :

- le parcours client → équipement → demande → intervention terminée → PDF ;
- les listes, détails, recherches, tableaux de bord et rapports du portail client, avec refus des identifiants d'une autre société ;
- l'exclusion des notes internes, la gestion des comptes et les droits des techniciens ;
- les séries uniques, les dates, les relations client/contrat/livraison et la clôture avec plusieurs interventions ;
- le refus du stock négatif et deux sorties concurrentes sur la dernière pièce disponible ;
- deux créations simultanées d'interventions pour un même dossier ;
- les identifiants HFSQL longs, SHA-256, chemins, doublons, secrets exclus, transaction et répétition du staging.

Les 5 scénarios Chromium exercent les formulaires du parcours complet, la persistance dans une seconde session, l'isolation client y compris les PDF, l'affichage mobile avec données chargées, et un changement administrateur → client pendant qu'une ancienne réponse est retardée.

La restauration a conservé **5 clients, 8 équipements, 12 demandes, 12 interventions et 6 comptes fictifs**. Le catalogue et les contraintes PostgreSQL ont été restaurés ; une authentification et un téléchargement PDF ont été exécutés sur cette copie avant sa suppression.

La recherche manuelle d'une série a aussi été exécutée dans l'écran scanner et a retrouvé l'équipement autorisé. Les captures dans `docs/screenshots/` présentent les données de démonstration de l'instance principale, sans les enregistrements ajoutés par les tests navigateur.

## Limites de ces résultats

- Aucun export des données SAV HFSQL réelles n'a été fourni. L'import est testé sur des fixtures ; les données réelles ne sont ni migrées ni promues vers les tables métier. Voir [l'export à demander](EXPORT_HFSQL.md).
- Les traitements WLangage binaires ne sont pas convertis. Les règles reconstruites doivent être confrontées à des dossiers de l'entreprise.
- La lecture d'une vraie étiquette par la caméra d'un téléphone physique reste à essayer en HTTPS. La compatibilité dépend du navigateur et de `BarcodeDetector`.
- Aucun message WhatsApp ni appel à un fournisseur IA n'a été effectué. Les écrans indiquent leur état non connecté ; les adaptateurs restent à développer et tester avec les accès retenus.
- Le déploiement sur un domaine de production et un test de charge de 15 utilisateurs simultanés n'ont pas été réalisés. Le serveur partagé est préparé pour cette petite équipe, avec les réglages décrits dans [DEPLOIEMENT.md](DEPLOIEMENT.md).
- La configuration cloud a été enregistrée en brouillon. Sa publication et la restauration dans une nouvelle tâche relèvent de l'interface de l'environnement et n'ont pas été prétendues validées.

## Particularité de la construction Docker dans ce cloud

Le builder a nécessité le proxy existant, une résolution explicite de son nom, le réseau hôte et le certificat CA fourni par la plateforme. Les vérifications TLS ont été maintenues. Le Dockerfile accepte un secret BuildKit optionnel `build_ca` ; ce certificat n'est pas incorporé à l'image. La construction standard décrite dans le guide reste adaptée à un serveur disposant d'un accès réseau normal. Aucun identifiant de proxy n'est enregistré dans les sources.
