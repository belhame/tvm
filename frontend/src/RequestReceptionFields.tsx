import { useId } from "react";
import type { RecordData } from "./api";

const textFields = [
  ["client_reference", "N° d’appel client / référence client"],
  ["end_customer", "Client final"],
  ["contact_name", "Nom du contact"],
  ["contact_phone", "Téléphone du contact"],
  ["contact_email", "E-mail du contact"],
  ["packaging", "Emballage reçu"],
  ["courier_name", "Nom du livreur"],
] as const;
const choices = [
  {
    name: "service_location",
    label: "Lieu de prise en charge",
    options: [
      ["", "Non renseigné"],
      ["workshop", "Atelier"],
      ["depot", "Dépôt"],
      ["onsite", "Sur site"],
    ],
  },
  {
    name: "delivered_by",
    label: "Matériel livré par",
    options: [
      ["", "Non renseigné"],
      ["courier", "Livreur"],
      ["client", "Client"],
    ],
  },
  {
    name: "warranty_status",
    label: "Situation de garantie du dossier",
    options: [
      ["unspecified", "Non précisée"],
      ["warranty", "Garantie"],
      ["quotation", "Devis"],
      ["contract", "Contrat"],
      ["billable", "Facturable"],
    ],
  },
];

export function defaultArrivalLocal() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

export default function RequestReceptionFields({
  value,
  onChange,
  readonly = false,
  includeClosure = false,
  canBackfillClosure = false,
}: {
  value: RecordData;
  onChange: (name: string, entry: string | boolean) => void;
  readonly?: boolean;
  includeClosure?: boolean;
  canBackfillClosure?: boolean;
}) {
  const id = useId();
  return (
    <section
      className="request-reception"
      aria-label="Réception et suivi du dossier"
    >
      <div className="request-reception-heading">
        <h3>Réception et suivi du dossier</h3>
        <p>
          Le compteur part de la date d’arrivée renseignée, selon les heures
          ouvrées calculées par le serveur.
        </p>
      </div>
      <div className="form-grid">
        <div className="form-field">
          <label htmlFor={`${id}-arrived_at`}>Date d’arrivée</label>
          <input
            id={`${id}-arrived_at`}
            className="input"
            type="datetime-local"
            disabled={readonly}
            value={value.arrived_at || ""}
            onChange={(event) => onChange("arrived_at", event.target.value)}
            aria-describedby={`${id}-arrival-help`}
          />
          <small id={`${id}-arrival-help`}>
            Date de réception réelle de l’onduleur. Laissez vide s’il n’est pas
            encore arrivé ou si la date est inconnue. La date de création du
            dossier n’est pas utilisée à sa place.
          </small>
        </div>
        {includeClosure && (
          <div className="form-field">
            <label htmlFor={`${id}-closed_at`}>Date de clôture</label>
            <input
              id={`${id}-closed_at`}
              className="input"
              type="datetime-local"
              readOnly={!canBackfillClosure || readonly}
              value={value.closed_at || ""}
              onChange={(event) => {
                if (canBackfillClosure && !readonly)
                  onChange("closed_at", event.target.value);
              }}
              aria-describedby={`${id}-closure-help`}
            />
            <small id={`${id}-closure-help`}>
              {canBackfillClosure
                ? "Complétez uniquement une clôture historique inconnue : date passée, postérieure ou égale à l’arrivée."
                : value.closed_at
                  ? "Date enregistrée et conservée. La réouverture du dossier relance le compteur."
                  : "Renseignée par le serveur lorsque le dossier passe à Clôturé."}
            </small>
          </div>
        )}
        {textFields.map(([name, label]) => (
          <div className="form-field" key={name}>
            <label htmlFor={`${id}-${name}`}>{label}</label>
            <input
              id={`${id}-${name}`}
              className="input"
              type={
                name === "contact_email"
                  ? "email"
                  : name === "contact_phone"
                    ? "tel"
                    : "text"
              }
              disabled={readonly}
              value={value[name] || ""}
              onChange={(event) => onChange(name, event.target.value)}
            />
          </div>
        ))}
        {choices.map((field) => (
          <div className="form-field" key={field.name}>
            <label htmlFor={`${id}-${field.name}`}>{field.label}</label>
            <select
              id={`${id}-${field.name}`}
              className="input"
              disabled={readonly}
              value={
                value[field.name] ||
                (field.name === "warranty_status" ? "unspecified" : "")
              }
              onChange={(event) => onChange(field.name, event.target.value)}
            >
              {field.options.map(([key, label]) => (
                <option value={key} key={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        ))}
        <div className="form-field request-reception-return">
          <label htmlFor={`${id}-return_flag`}>
            <input
              id={`${id}-return_flag`}
              type="checkbox"
              disabled={readonly}
              checked={
                value.return_flag === true || value.return_flag === "true"
              }
              onChange={(event) =>
                onChange("return_flag", event.target.checked)
              }
            />
            Retour de matériel
          </label>
        </div>
        <div className="form-field span-2">
          <label htmlFor={`${id}-accessories`}>Accessoires reçus</label>
          <textarea
            id={`${id}-accessories`}
            className="input"
            rows={3}
            disabled={readonly}
            value={value.accessories || ""}
            onChange={(event) => onChange("accessories", event.target.value)}
          />
        </div>
      </div>
    </section>
  );
}
