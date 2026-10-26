import type { RecordData } from "./api";

const checklists: Record<
  string,
  { title: string; fields: [string, string][] }
> = {
  maintenance: {
    title: "Fiche de maintenance",
    fields: [
      ["battery_failure", "Défaillance des batteries"],
      ["electronics_failure", "Défaillance électronique"],
      ["overload", "Surcharge"],
      ["overvoltage", "Surtension"],
      ["overheating", "Surchauffe"],
      ["replace_batteries", "Remplacement des batteries"],
      ["configure", "Configuration de l’onduleur"],
      ["replace_board", "Remplacement d’une carte"],
      ["replace_ups", "Remplacement de l’onduleur"],
      ["recover_ups", "Récupération de l’onduleur"],
      ["repair_board", "Réparation d’une carte"],
    ],
  },
  commissioning: {
    title: "Fiche de mise en service",
    fields: [
      ["electrical_protection", "Protections électriques vérifiées"],
      ["cable_section", "Sections des câbles vérifiées"],
      ["configure", "Configuration réalisée"],
      ["connection", "Raccordement réalisé"],
      ["power_on", "Mise sous tension"],
      ["normal_operation_test", "Essai en fonctionnement normal"],
      ["runtime_test", "Test d’autonomie"],
      ["bypass_test", "Test du bypass"],
      ["alarm_test", "Test des alarmes"],
    ],
  },
  preventive: {
    title: "Fiche de maintenance préventive",
    fields: [
      ["environment", "Environnement vérifié"],
      ["power_cables", "Câbles de puissance vérifiés"],
      ["alarm_history", "Historique des alarmes consulté"],
      ["runtime_test", "Test d’autonomie"],
      ["bypass_test", "Test du bypass"],
      ["alarm_test", "Test des alarmes"],
      ["dusting", "Dépoussiérage réalisé"],
    ],
  },
};

export default function InterventionWorksheet({
  kind,
  value,
  onChange,
  readonly = false,
}: {
  kind: string;
  value: RecordData;
  onChange: (value: RecordData) => void;
  readonly?: boolean;
}) {
  const checklist = checklists[kind];
  if (!checklist) return null;
  const section = value[kind] || {};
  const update = (name: string, entry: unknown) =>
    onChange({ ...value, [kind]: { ...section, [name]: entry } });
  return (
    <section className="intervention-worksheet" aria-label={checklist.title}>
      <div className="intervention-worksheet-heading">
        <h3>{checklist.title}</h3>
        <p>
          Les contrôles et opérations de cette fiche sont enregistrés avec
          l’intervention.
        </p>
      </div>
      <div className="intervention-checklist">
        {checklist.fields.map(([key, label]) => (
          <label className="intervention-checklist-item" key={key}>
            <input
              type="checkbox"
              disabled={readonly}
              checked={section[key] === true}
              onChange={(event) => update(key, event.target.checked)}
            />
            <span>{label}</span>
            {readonly && section[key] === undefined && (
              <small>Non renseigné</small>
            )}
          </label>
        ))}
      </div>
      {kind === "maintenance" && (
        <label className="form-field">
          Nombre de batteries remplacées
          <input
            className="input"
            type="number"
            min="0"
            step="1"
            disabled={readonly}
            value={section.battery_replaced_count ?? ""}
            onChange={(event) => {
              if (event.target.value === "") {
                const next = { ...section };
                delete next.battery_replaced_count;
                onChange({ ...value, [kind]: next });
              } else
                update("battery_replaced_count", Number(event.target.value));
            }}
          />
          <small>
            Un remplacement terminé demande au moins une batterie remplacée.
          </small>
        </label>
      )}
      <label className="form-field intervention-checklist-note">
        Commentaire de la fiche
        <textarea
          className="input"
          rows={3}
          disabled={readonly}
          value={section.comment || ""}
          onChange={(event) => update("comment", event.target.value)}
        />
      </label>
    </section>
  );
}
