import type { RecordData } from "./api";

export type Field = {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  resource?: string;
  options?: [string, string][];
  placeholder?: string;
  wide?: boolean;
  help?: string;
  default?: any;
};
export type Column = {
  key: string;
  label: string;
  type?:
    | "date"
    | "datetime"
    | "status"
    | "money"
    | "number"
    | "client"
    | "serial"
    | "user";
  secondary?: string;
};
export type Resource = {
  title: string;
  singular: string;
  description: string;
  button: string;
  fields: Field[];
  columns: Column[];
};
export const statuses: Record<string, string> = {
  active: "Actif",
  maintenance: "En maintenance",
  inactive: "Inactif",
  new: "Nouvelle",
  scheduled: "Planifiée",
  in_progress: "En cours",
  resolved: "Résolue",
  closed: "Clôturée",
  testing: "En test",
  completed: "Terminée",
  cancelled: "Annulée",
  low: "Basse",
  normal: "Normale",
  high: "Haute",
  urgent: "Urgente",
  draft: "Brouillon",
  expired: "Expiré",
  ready: "Prêt à livrer",
  delivered: "Livré",
  battery: "Batteries",
  board: "Cartes électroniques",
  ventilation: "Ventilation",
  other: "Divers",
  in: "Entrée",
  out: "Sortie",
  adjustment: "Ajustement",
  admin: "Administrateur",
  manager: "Responsable SAV",
  technician: "Technicien",
  client: "Client",
  true: "Actif",
  false: "Désactivé",
};
const choice = (...keys: string[]): [string, string][] =>
  keys.map((x) => [x, statuses[x] || x]);
export const resources: Record<string, Resource> = {
  clients: {
    title: "Clients",
    singular: "client",
    description:
      "Un seul espace pour vos clients, leurs sites et leurs contacts.",
    button: "Nouveau client",
    columns: [
      {
        key: "name",
        label: "Client",
        type: "client",
        secondary: "contact_name",
      },
      { key: "email", label: "E-mail" },
      { key: "phone", label: "Téléphone" },
      { key: "city", label: "Ville" },
    ],
    fields: [
      {
        name: "name",
        label: "Raison sociale",
        required: true,
        placeholder: "Ex. Centre Hospitalier Lyon",
      },
      { name: "contact_name", label: "Contact principal" },
      { name: "email", label: "Adresse e-mail", type: "email" },
      { name: "phone", label: "Téléphone", type: "tel" },
      { name: "address", label: "Adresse", wide: true },
      { name: "city", label: "Ville" },
      { name: "postal_code", label: "Code postal" },
      { name: "country", label: "Pays", default: "France" },
    ],
  },
  equipment: {
    title: "Équipements",
    singular: "équipement",
    description:
      "Le parc d’onduleurs, chaque numéro de série et son historique SAV.",
    button: "Nouvel équipement",
    columns: [
      {
        key: "serial_number",
        label: "N° de série",
        type: "serial",
        secondary: "brand",
      },
      { key: "model", label: "Modèle" },
      { key: "client_name", label: "Client" },
      { key: "power_kva", label: "Puissance (kVA)", type: "number" },
      { key: "location", label: "Site / emplacement" },
      { key: "status", label: "Statut", type: "status" },
      { key: "warranty_until", label: "Garantie", type: "date" },
    ],
    fields: [
      {
        name: "client",
        label: "Client",
        type: "select",
        resource: "clients",
        required: true,
      },
      {
        name: "serial_number",
        label: "Numéro de série",
        required: true,
        placeholder: "Ex. 93PM2408F00123",
      },
      {
        name: "brand",
        label: "Marque",
        required: true,
        default: "Eaton",
        placeholder: "Eaton, Schneider, Vertiv…",
      },
      { name: "model", label: "Modèle", required: true },
      {
        name: "power_kva",
        label: "Puissance (kVA)",
        type: "number",
        default: 0,
      },
      { name: "location", label: "Site / emplacement" },
      { name: "commissioned_on", label: "Mise en service", type: "date" },
      { name: "warranty_until", label: "Fin de garantie", type: "date" },
      {
        name: "status",
        label: "Statut",
        type: "select",
        options: choice("active", "maintenance", "inactive"),
        default: "active",
      },
    ],
  },
  requests: {
    title: "Demandes SAV",
    singular: "demande SAV",
    description:
      "Du premier signalement à la résolution : aucun dossier ne se perd.",
    button: "Nouvelle demande",
    columns: [
      { key: "reference", label: "N° de dossier", secondary: "subject" },
      { key: "client_name", label: "Client" },
      { key: "equipment_serial", label: "N° de série", type: "serial" },
      { key: "priority", label: "Priorité", type: "status" },
      { key: "status", label: "Statut", type: "status" },
      { key: "created_at", label: "Création", type: "date" },
    ],
    fields: [
      {
        name: "equipment",
        label: "Équipement concerné",
        type: "select",
        resource: "equipment",
        required: true,
      },
      { name: "subject", label: "Objet du signalement", required: true },
      {
        name: "description",
        label: "Description de la panne",
        type: "textarea",
        wide: true,
        required: true,
      },
      {
        name: "priority",
        label: "Priorité",
        type: "select",
        options: choice("low", "normal", "high", "urgent"),
        default: "normal",
      },
      {
        name: "status",
        label: "Statut",
        type: "select",
        options: choice(
          "new",
          "scheduled",
          "in_progress",
          "resolved",
          "closed",
        ),
        default: "new",
      },
    ],
  },
  interventions: {
    title: "Interventions",
    singular: "intervention",
    description:
      "Planifiez, diagnostiquez et suivez les interventions de votre équipe.",
    button: "Nouvelle intervention",
    columns: [
      { key: "reference", label: "N°", secondary: "request_reference" },
      { key: "client_name", label: "Client / site" },
      {
        key: "equipment_model",
        label: "Équipement",
        secondary: "equipment_serial",
      },
      { key: "status", label: "Statut", type: "status" },
      { key: "technician_name", label: "Technicien", type: "user" },
      { key: "scheduled_at", label: "Planification", type: "datetime" },
    ],
    fields: [
      {
        name: "service_request",
        label: "Demande SAV",
        type: "select",
        resource: "requests",
        required: true,
      },
      {
        name: "technician",
        label: "Technicien assigné",
        type: "select",
        resource: "users",
      },
      { name: "scheduled_at", label: "Date et heure", type: "datetime-local" },
      {
        name: "duration_minutes",
        label: "Durée prévue (minutes)",
        type: "number",
        default: 120,
      },
      {
        name: "status",
        label: "Statut",
        type: "select",
        options: choice(
          "scheduled",
          "in_progress",
          "testing",
          "completed",
          "cancelled",
        ),
        default: "scheduled",
      },
      {
        name: "diagnosis",
        label: "Diagnostic et observations",
        type: "textarea",
        wide: true,
      },
      {
        name: "work_done",
        label: "Travaux réalisés",
        type: "textarea",
        wide: true,
      },
      {
        name: "recommendations",
        label: "Recommandations client",
        type: "textarea",
        wide: true,
      },
      {
        name: "internal_notes",
        label: "Notes internes",
        type: "textarea",
        wide: true,
        help: "Visibles uniquement par votre équipe. Jamais dans le portail client ni le rapport PDF.",
      },
    ],
  },
  parts: {
    title: "Pièces détachées",
    singular: "pièce",
    description: "Références, seuils et disponibilité du stock partagé.",
    button: "Nouvelle pièce",
    columns: [
      { key: "sku", label: "Référence", type: "serial" },
      { key: "name", label: "Désignation" },
      { key: "category", label: "Catégorie", type: "status" },
      { key: "stock_quantity", label: "Stock", type: "number" },
      { key: "min_stock", label: "Seuil", type: "number" },
      { key: "unit_price", label: "Prix unitaire", type: "money" },
    ],
    fields: [
      { name: "sku", label: "Référence", required: true },
      { name: "name", label: "Désignation", required: true },
      {
        name: "category",
        label: "Catégorie",
        type: "select",
        options: choice("battery", "board", "ventilation", "other"),
        default: "other",
      },
      {
        name: "unit_price",
        label: "Prix unitaire (€)",
        type: "number",
        default: 0,
      },
      {
        name: "min_stock",
        label: "Seuil d’alerte",
        type: "number",
        default: 5,
      },
    ],
  },
  "stock-movements": {
    title: "Mouvements de stock",
    singular: "mouvement",
    description:
      "Chaque entrée et sortie est tracée. Le stock ne peut pas devenir négatif.",
    button: "Enregistrer un mouvement",
    columns: [
      { key: "created_at", label: "Date", type: "datetime" },
      { key: "part_name", label: "Pièce" },
      { key: "kind", label: "Mouvement", type: "status" },
      { key: "quantity", label: "Quantité", type: "number" },
      { key: "reference", label: "Référence / motif" },
    ],
    fields: [
      {
        name: "part",
        label: "Pièce",
        type: "select",
        resource: "parts",
        required: true,
      },
      {
        name: "kind",
        label: "Type de mouvement",
        type: "select",
        options: choice("in", "out", "adjustment"),
        default: "in",
      },
      {
        name: "quantity",
        label: "Quantité",
        type: "number",
        required: true,
        default: 1,
        help: "Saisir une quantité positive pour une entrée ou sortie. Un ajustement peut être signé.",
      },
      { name: "reference", label: "Référence ou motif", required: true },
      {
        name: "intervention",
        label: "Intervention liée (facultative)",
        type: "select",
        resource: "interventions",
      },
    ],
  },
  contracts: {
    title: "Contrats",
    singular: "contrat",
    description: "Les engagements de maintenance et les équipements couverts.",
    button: "Nouveau contrat",
    columns: [
      { key: "number", label: "N° de contrat" },
      { key: "client_name", label: "Client" },
      { key: "coverage", label: "Couverture" },
      { key: "starts_on", label: "Début", type: "date" },
      { key: "ends_on", label: "Échéance", type: "date" },
      { key: "status", label: "Statut", type: "status" },
    ],
    fields: [
      { name: "number", label: "Numéro de contrat", required: true },
      {
        name: "client",
        label: "Client",
        type: "select",
        resource: "clients",
        required: true,
      },
      {
        name: "equipment",
        label: "Équipement (facultatif)",
        type: "select",
        resource: "equipment",
      },
      {
        name: "starts_on",
        label: "Début de couverture",
        type: "date",
        required: true,
      },
      {
        name: "ends_on",
        label: "Fin de couverture",
        type: "date",
        required: true,
      },
      {
        name: "coverage",
        label: "Conditions de couverture",
        type: "textarea",
        wide: true,
        required: true,
      },
      {
        name: "visits_per_year",
        label: "Visites par an",
        type: "number",
        default: 1,
      },
      {
        name: "status",
        label: "Statut",
        type: "select",
        options: choice("draft", "active", "expired"),
        default: "active",
      },
    ],
  },
  warranties: {
    title: "Garanties",
    singular: "garantie",
    description: "La couverture et les dates de garantie de chaque onduleur.",
    button: "Nouvelle garantie",
    columns: [
      { key: "equipment_serial", label: "Équipement", type: "serial" },
      { key: "client_name", label: "Client" },
      { key: "provider", label: "Garant" },
      { key: "starts_on", label: "Début", type: "date" },
      { key: "ends_on", label: "Fin", type: "date" },
      { key: "terms", label: "Conditions" },
    ],
    fields: [
      {
        name: "equipment",
        label: "Équipement",
        type: "select",
        resource: "equipment",
        required: true,
      },
      { name: "provider", label: "Fabricant / garant", required: true },
      {
        name: "starts_on",
        label: "Début de garantie",
        type: "date",
        required: true,
      },
      {
        name: "ends_on",
        label: "Fin de garantie",
        type: "date",
        required: true,
      },
      { name: "terms", label: "Conditions", type: "textarea", wide: true },
    ],
  },
  "delivery-notes": {
    title: "Bons de livraison",
    singular: "bon de livraison",
    description: "Préparez et conservez les livraisons liées à vos dossiers.",
    button: "Nouveau bon",
    columns: [
      { key: "reference", label: "N° de bon" },
      { key: "client_name", label: "Client" },
      { key: "delivered_at", label: "Date de livraison", type: "date" },
      { key: "status", label: "Statut", type: "status" },
      { key: "notes", label: "Observations" },
    ],
    fields: [
      {
        name: "client",
        label: "Client",
        type: "select",
        resource: "clients",
        required: true,
      },
      {
        name: "intervention",
        label: "Intervention liée",
        type: "select",
        resource: "interventions",
      },
      {
        name: "delivered_at",
        label: "Date de livraison",
        type: "datetime-local",
      },
      {
        name: "status",
        label: "Statut",
        type: "select",
        options: choice("draft", "ready", "delivered"),
        default: "draft",
      },
      { name: "notes", label: "Observations", type: "textarea", wide: true },
    ],
  },
  users: {
    title: "Comptes & accès",
    singular: "compte",
    description:
      "Des droits adaptés à chaque utilisateur, appliqués sur le serveur.",
    button: "Créer un compte",
    columns: [
      { key: "username", label: "Identifiant", secondary: "email" },
      { key: "first_name", label: "Prénom" },
      { key: "last_name", label: "Nom" },
      { key: "role", label: "Rôle", type: "status" },
      { key: "is_active", label: "Compte actif", type: "status" },
    ],
    fields: [
      { name: "username", label: "Identifiant", required: true },
      { name: "email", label: "E-mail", type: "email" },
      { name: "first_name", label: "Prénom" },
      { name: "last_name", label: "Nom" },
      {
        name: "role",
        label: "Rôle",
        type: "select",
        options: choice("admin", "manager", "technician", "client"),
        default: "technician",
      },
      {
        name: "client",
        label: "Client du portail",
        type: "select",
        resource: "clients",
        help: "Obligatoire pour le rôle Client, vide pour un compte interne.",
      },
      {
        name: "password",
        label: "Mot de passe",
        type: "password",
        help: "Au moins 10 caractères. Laisser vide en modification pour conserver le mot de passe.",
      },
      {
        name: "is_active",
        label: "Compte actif",
        type: "select",
        options: [
          ["true", "Actif"],
          ["false", "Désactivé"],
        ],
        default: "true",
      },
    ],
  },
};

export function optionLabel(resource: string, item: RecordData) {
  if (resource === "clients") return item.name;
  if (resource === "equipment")
    return `${item.serial_number} · ${item.model} · ${item.client_name || ""}`;
  if (resource === "requests")
    return `${item.reference} · ${item.subject} · ${item.client_name || ""}`;
  if (resource === "interventions")
    return `${item.reference} · ${item.client_name || ""}`;
  if (resource === "users")
    return (
      `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.username
    );
  if (resource === "parts")
    return `${item.sku} · ${item.name} (${item.stock_quantity} en stock)`;
  return item.name || item.reference || String(item.id);
}
