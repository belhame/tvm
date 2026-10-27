# Assistant diagnostic : documents, retours et aide IA

L’assistant aide l’équipe interne à retrouver des références techniques et à préparer des pistes de diagnostic. Il ne certifie ni une panne, ni une réparation. Le technicien vérifie les sources, réalise les contrôles adaptés à son habilitation et valide toute décision. Une réponse ne modifie automatiquement aucun dossier, intervention, statut, devis ou facturation.

La bibliothèque et la recherche locale s’utilisent **sans clé IA**. L’analyse OpenAI est une fonction distincte, désactivée tant que sa configuration serveur n’est pas fournie. Aucun diagnostic de démonstration ne remplace une réponse absente du fournisseur.

## Accès et périmètre

Ouvrir **Assistant diagnostic** depuis un compte interne habilité. Les clients et les deux types de livreurs n’ont pas accès à cette bibliothèque ni aux analyses. Les autorisations s’appliquent aussi aux API et aux téléchargements privés.

Les administrateurs, responsables SAV et techniciens actifs peuvent consulter, rechercher et déposer des documents. L’approbation et l’archivage sont réservés aux administrateurs et responsables SAV. Un technicien propose des retours uniquement à partir de ses propres interventions terminées.

Choisir la **marque et le modèle exacts** de l’onduleur. Une documentation d’un modèle voisin peut être pertinente à lire, mais elle ne devient pas automatiquement une source de diagnostic pour le modèle sélectionné. Seules les sources approuvées correspondant à ce périmètre sont utilisables par la recherche de référence et l’analyse.

Les dossiers SAV, les notes internes et les pièces jointes déjà stockées dans TVM ne sont pas tous envoyés à l’IA. Préparer une description technique utile, sans nom, téléphone, adresse, identifiant de compte ou autre information client inutile au diagnostic. Vérifier le contenu des documents avant de les intégrer à la bibliothèque.

## Ajouter un manuel constructeur

1. Dans **Bibliothèque**, choisir **Ajouter un document**.
2. Choisir le type **Manuel technique**, donner un titre permettant d’identifier sa provenance et sa version, puis renseigner la marque et le modèle exacts concernés. Ajouter la référence de carte et la révision si elles sont connues. Par exemple, utiliser des références fictives `MARQUE-LAB / MODELE-LAB-1500` pour un essai.
3. Charger le **PDF ou TXT UTF-8**, limité à **10 Mio**. Pour alimenter la recherche, un PDF doit contenir du texte exploitable : une page scannée sans couche texte ne constitue pas une extraction lisible. Un fichier chiffré ou endommagé doit être remplacé par une version lisible.
4. Ouvrir la fiche du document pour relire **Texte extrait**, ses pages et repères ; utiliser **Télécharger le document** pour contrôler l’original. Vérifier la correspondance du modèle, les unités, les codes d’erreur et les éventuelles consignes de sécurité. Une extraction réussie n’approuve pas le document.
5. Faire examiner le contenu par une personne habilitée, puis utiliser **Approuver la source**. Une source en attente ou archivée ne doit pas servir de référence approuvée. **Archiver la source** permet d’écarter une référence devenue inadaptée.

Les documents sont conservés dans le stockage privé du serveur. Ils doivent être sauvegardés avec la base et les autres fichiers média ; copier uniquement les sources de l’application ne suffit pas. Voir [les sauvegardes](DEPLOIEMENT.md#sauvegarder).

L’extraction accepte au plus **500 pages PDF**, **100 000 caractères par page** et **1 000 000 de caractères au total** ; le TXT est également limité à 1 000 000 de caractères. Un document dépassant ces limites est refusé plutôt que tronqué silencieusement : le découper en parties identifiables. Le traitement est borné en temps et en ressources.

Le statut distingue **Texte extrait**, **Extraction partielle** et **Sans texte indexable**. Un PDF scanné peut rester consultable et être approuvé dans la bibliothèque, mais il n’alimente pas la recherche s’il ne fournit aucun extrait. Un document partiel n’apporte que le texte effectivement extrait. Une source approuvée devient immuable : pour la corriger, l’archiver et déposer une nouvelle version.

## Conserver un schéma ou une image

Un schéma ou une image **contenu dans un PDF** reste consultable dans le fichier original privé. La bibliothèque n’accepte pas l’import autonome de PNG ou JPEG. **L’assistant n’interprète pas les pixels, les composants ni les connexions du schéma** : aucun OCR ni aucune inférence visuelle n’est fourni. Le fichier consultable ne constitue pas à lui seul une preuve technique extraite pour une réponse.

Si une information du schéma doit devenir une référence textuelle, un professionnel doit la vérifier et la décrire dans une source textuelle appropriée, avec sa provenance. La lecture locale de photos d’étiquettes dans l’espace logistique est une autre fonction ; elle ne donne pas une capacité d’analyse de schémas à l’assistant.

## Proposer un retour d’expérience

1. Terminer réellement la fiche d’intervention dans TVM : son état doit être **Terminée** (`completed`). Un dossier simplement clôturé, une mission livrée ou un diagnostic en cours ne suffit pas.
2. Dans **Retours validés**, utiliser **Proposer un retour** et sélectionner cette intervention. Décrire le symptôme observé, les codes de panne et mesures utiles, la cause confirmée, la réparation et le résultat vérifié, en distinguant faits et hypothèses.
3. Retirer les informations client inutiles et vérifier la marque et le modèle, repris du matériel de l’intervention. Les contrôles automatiques peuvent refuser des identifiants ou coordonnées connus, mais ne garantissent pas une anonymisation complète.
4. Soumettre le retour à validation humaine. La fin de l’intervention ne transforme pas automatiquement ses notes en connaissance approuvée.
5. Après approbation, retrouver ce retour parmi les références du modèle exact. Un retour non validé ou archivé ne doit pas être présenté comme une solution confirmée.

Un cas résolu constitue un exemple documenté ; il ne prouve pas qu’un autre appareil présentant le même symptôme a la même panne.

Le retour n’est plus utilisable par la recherche si son intervention source n’est plus `completed` ou si le modèle source ne correspond plus. La validation humaine ne remplace pas ce contrôle lors de son utilisation.

## Rechercher sans connecter de fournisseur

Dans **Diagnostic**, renseigner la marque, le modèle exact et les symptômes, le code défaut ou les mesures, puis choisir **Rechercher les sources**. Lire les extraits et ouvrir leurs documents pour contrôler le contexte. Ce parcours utilise les références locales approuvées et ne nécessite aucune clé OpenAI.

Le champ **Dossier SAV lié (facultatif)** fixe la marque et le modèle depuis le matériel du dossier autorisé. Sa description, ses coordonnées et son numéro de série ne sont pas recopiés dans les champs techniques ; la description utile doit être saisie explicitement.

Si aucune source n’est trouvée, vérifier le modèle et les termes recherchés, puis ajouter une documentation appropriée ou faire approuver une source en attente. L’analyse s’abstient alors sans appeler le fournisseur ; l’absence de résultat ne doit pas être remplacée par une panne inventée. Une recherche locale réussie ne valide pas la connexion IA.

Les références proposées renvoient aux pages et extraits documentaires, ou au retour de réparation approuvé. Vérifier leur contenu et leur version plutôt que le seul titre. Une référence de carte ou une révision connue permet de préciser le périmètre de recherche.

Pour essayer le parcours sans documentation réelle, utiliser le [texte entièrement fictif](exemples/diagnostic_fictif.txt), avec la marque `TVM-LAB`, le modèle `MODELE-LAB-1500` et la recherche `autonomie batterie`. Ce fichier ne décrit aucun matériel réel. Il n’est pas importé automatiquement dans la base métier.

## Activer l’analyse OpenAI sur le serveur

L’administrateur de l’installation configure l’accès dans le **`.env` privé du serveur**, à côté de `compose.yaml`. Ne jamais saisir la clé dans le navigateur, un fichier `VITE_*`, les sources versionnées, un ticket ou une conversation. Le fichier `.env.example` décrit les variables, sans contenir la vraie clé.

Configurer ces noms dans le `.env` existant, en conservant les autres réglages de l’installation :

| Variable | Utilisation |
|---|---|
| `TVM_AI_ENABLED` | `0` garde l’analyse désactivée ; `1` autorise son utilisation après configuration. |
| `TVM_AI_API_KEY` | Clé OpenAI privée, ajoutée directement sur le serveur par l’administrateur. |
| `TVM_AI_MODEL` | Modèle retenu pour l’installation ; valeur prévue : `gpt-4.1-mini`. |
| `TVM_AI_TIMEOUT` | Délai maximal en secondes : `20` par défaut, borné de `5` à `30`. |

Après modification, **recréer le service web** pour lui transmettre la nouvelle configuration. Depuis le dossier du projet en mode Docker :

```bash
docker compose --profile container up -d --no-build --force-recreate --wait web
```

Ce redémarrage conserve les volumes de données. Ne pas supprimer les volumes pour changer une clé. Sous Windows, exécuter cette commande dans un terminal ouvert dans le dossier de l’installation ; le lanceur **DEMARRER_TVM.cmd** permet ensuite les démarrages habituels.

En développement Python local, arrêter Gunicorn avec `Ctrl+C`, puis relancer `bash scripts/start.sh` depuis la racine : le script recharge `.env`. Il n’est pas nécessaire de placer la clé dans le frontend ni de recompiler React pour un changement de clé.

Revenir dans **Assistant diagnostic** et vérifier l’état affiché. Une clé présente ou un modèle renseigné ne démontre pas qu’un appel fournisseur a réussi. Une installation sans clé doit rester utilisable pour la bibliothèque et la recherche locale, avec un état IA non connecté ou désactivé.

Une fois l’activation autorisée, un essai sur des données fictives et une source approuvée permet de vérifier l’accès réel. Un refus d’accès, un quota, un délai dépassé ou une réponse inexploitable doit rester visible ; aucun faux diagnostic ne doit être affiché comme résultat connecté.

## Données transmises, rétention et coût

L’analyse utilise les éléments techniques et extraits sélectionnés côté serveur. Les documents importés doivent être contrôlés avant approbation : ils peuvent contenir des informations confidentielles, des erreurs ou des instructions étrangères à la tâche. Leur présence dans la bibliothèque ne dispense pas de vérifier la réponse et ses références.

TVM conserve une trace interne des analyses et des sources utilisées. Cette traçabilité locale est distincte du paramètre de stockage demandé au fournisseur ; une réponse enregistrée ne devient pas un retour d’expérience approuvé.

L’appel OpenAI est demandé avec **`store: false`**. Ce paramètre ne constitue **pas une garantie de rétention nulle** : les conditions du fournisseur, les journaux de sécurité et les options du compte restent à examiner avant d’envoyer des informations réelles. La localisation et la politique de traitement ne sont pas établies par la simple présence d’une clé.

L’API peut entraîner des **coûts selon le modèle et le volume traité**. Prévoir un budget et les limites du compte fournisseur avant l’activation. Les tests avec un fournisseur simulé ou une clé absente ne mesurent ni ces coûts ni la disponibilité d’OpenAI.

Le serveur limite les demandes à dix analyses par compte et par heure, une analyse simultanée par compte et deux pour l’ensemble de l’installation. Les doubles requêtes portant la même clé ne déclenchent pas une seconde analyse. Ces limites ne remplacent pas le plafond de dépenses à régler chez le fournisseur. Une nouvelle tentative après une erreur nécessite une action explicite de l’utilisateur.

Après avoir vérifié la description et les références retenues, cocher l’autorisation de partager cette saisie technique et les extraits approuvés, puis utiliser **Analyser avec IA**. La réponse est une aide à examiner : ses hypothèses, contrôles proposés et citations demandent une validation humaine. Toute action métier reste une saisie explicite dans le parcours TVM habituel.

**Préparer une nouvelle analyse** réinitialise la demande et son consentement, sans appeler le fournisseur. Un nouvel envoi exige de nouveau cette autorisation et peut entraîner un coût. L’onglet **Historique** permet au technicien de relire ses propres analyses ; les administrateurs et responsables SAV peuvent consulter l’ensemble. Les sources archivées restent signalées dans cette trace et ne redeviennent pas des références approuvées pour une nouvelle recherche.

## Vérifier une installation

- Sans clé : ajout et consultation privés, approbation humaine, recherche du modèle exact et refus des comptes clients/livreurs.
- Avec des fichiers fictifs : PDF/TXT acceptés dans la limite, traitement explicite des documents illisibles, image consultable sans prétention d’analyse visuelle.
- Pour les retours : intervention `completed` obligatoire et validation humaine avant utilisation comme référence.
- Pour l’IA : absence de réponse simulée en mode désactivé ; erreurs et délais signalés ; références contrôlables et aucun changement automatique de dossier.
- Pour une connexion réelle : essai fournisseur distinct, seulement après fourniture sécurisée de la clé et autorisation de l’envoi. Les tests locaux ne prouvent pas cette connexion.

Le compte rendu de [validation](VALIDATION.md) doit distinguer les parcours effectivement exécutés, les tests simulés et les vérifications fournisseur restant à effectuer.
