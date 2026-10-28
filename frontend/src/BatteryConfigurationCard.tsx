import { useId, type ReactNode } from "react";
import { AlertTriangle, BatteryCharging, Info } from "lucide-react";
import type { RecordData } from "./api";
import type { BatteryConfiguration } from "./battery";
import "./BatteryConfiguration.css";

export default function BatteryConfigurationCard({
  record,
  children,
}: {
  record: RecordData;
  children?: ReactNode;
}) {
  const id = useId();
  const config = record.battery_configuration as
    | BatteryConfiguration
    | null
    | undefined;
  const actual =
    typeof record.battery_count === "number" ? record.battery_count : null;
  return (
    <section className="battery-configuration" aria-labelledby={`${id}-title`}>
      <header>
        <span className="battery-configuration-icon">
          <BatteryCharging size={22} />
        </span>
        <div>
          <h3 id={`${id}-title`}>Configuration des batteries</h3>
          <p>
            {config?.status === "matched"
              ? "Correspondance exacte de référence"
              : config?.status === "stale"
                ? "Référence enregistrée à revérifier"
                : config?.status === "ambiguous"
                  ? "Plusieurs configurations possibles"
                  : "Configuration à vérifier"}
          </p>
        </div>
      </header>
      <div className="battery-configuration-body">
        {config?.status !== "matched" && (
          <p className="battery-configuration-warning">
            <AlertTriangle size={17} />
            {config?.status === "stale"
              ? "Le modèle ou sa référence a changé depuis l’enregistrement. La configuration conservée ne doit pas être utilisée sans nouvelle vérification."
              : "Aucune quantité nominale ne peut être retenue automatiquement. Vérifiez le matériel et ses éventuelles armoires externes."}
          </p>
        )}
        <dl className="battery-configuration-facts">
          <div>
            <dt>Référence technique</dt>
            <dd>{config?.reference || "Non déterminée"}</dd>
          </div>
          <div>
            <dt>Configuration</dt>
            <dd>{config?.configuration || "Non déterminée"}</dd>
          </div>
          <div>
            <dt>
              {config?.external_battery_required
                ? "Nombre nominal de batteries internes"
                : "Nombre nominal de référence"}
            </dt>
            <dd>
              {config?.nominal_count === null ||
              config?.nominal_count === undefined
                ? "Non déterminé"
                : config.nominal_count}
            </dd>
          </div>
          <div>
            <dt>Tension unitaire</dt>
            <dd>
              {config?.voltage_v ? `${config.voltage_v} V` : "Non déterminée"}
            </dd>
          </div>
          <div>
            <dt>Capacité unitaire</dt>
            <dd>
              {config?.capacity_ah
                ? `${config.capacity_ah} Ah`
                : "Non déterminée"}
            </dd>
          </div>
          <div>
            <dt>Fournisseurs de référence</dt>
            <dd>
              {config?.suppliers?.length
                ? config.suppliers.join(" · ")
                : "Non renseignés"}
            </dd>
          </div>
        </dl>
        {config?.external_battery_required && (
          <p className="battery-configuration-warning">
            <AlertTriangle size={17} />
            Batteries externes requises : le nombre de batteries internes ne
            permet pas de déduire le total installé.
          </p>
        )}
        <div className="battery-configuration-actual">
          <span>Nombre enregistré dans ce dossier</span>
          <strong>
            {actual === null
              ? "Non renseigné"
              : `${actual} batterie${actual === 1 ? "" : "s"}`}
          </strong>
          <span>
            {record.battery_count_source === "manual"
              ? actual === null
                ? "Quantité laissée non renseignée par saisie manuelle"
                : "Comptage confirmé par saisie manuelle"
              : record.battery_count_source === "reference"
                ? "Prérempli depuis la référence — à vérifier sur le matériel"
                : "Origine non renseignée"}
          </span>
        </div>
        {children}
        {config?.warnings?.length ? (
          <ul className="battery-configuration-warnings">
            {[...new Set(config.warnings)].map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
        {config?.recorded_intervention_counts?.length ? (
          <details className="battery-configuration-history">
            <summary>Comptages des anciennes fiches de visite</summary>
            <ul>
              {config.recorded_intervention_counts.map((visit) => (
                <li key={visit.intervention_id}>
                  {visit.reference} : {visit.battery_count} batterie
                  {visit.battery_count === 1 ? "" : "s"}
                </li>
              ))}
            </ul>
            <p>
              Ces quantités historiques ne remplacent pas le comptage de ce
              dossier.
            </p>
          </details>
        ) : null}
        <p className="battery-configuration-source">
          <Info size={15} />
          <span>
            {config?.source
              ? `Source : ${config.source}. `
              : "Source de référence non disponible. "}
            Les valeurs nominales sont indicatives ; le nombre constaté se
            confirme dans le suivi SAV.
          </span>
        </p>
      </div>
    </section>
  );
}
