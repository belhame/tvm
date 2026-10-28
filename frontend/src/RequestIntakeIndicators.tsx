import { History, ShieldCheck, FileText } from "lucide-react";
import { dateFR, type RecordData } from "./api";
import "./RequestIntakeIndicators.css";

export default function RequestIntakeIndicators({
  record,
  detailed = false,
}: {
  record: RecordData;
  detailed?: boolean;
}) {
  const summary = record.intake_data?.summary;
  const coverage = summary?.coverage;
  const provisional =
    coverage?.warranty_status === record.warranty_status &&
    coverage?.provisional === true;
  const history = summary?.return_history;
  const matches: RecordData[] = Array.isArray(history?.matches)
    ? history.matches.slice(0, 20)
    : [];
  const labels: Record<string, string> = {
    warranty: "Garantie",
    quotation: "Devis / facturable",
    billable: "Hors garantie / facturable",
    contract: "Contrat",
  };
  const label = labels[record.warranty_status];
  if (!record.return_flag && !label) return null;
  return (
    <div className={`request-intake-indicators${detailed ? " is-detailed" : ""}`}>
      <div className="request-intake-indicator-badges">
        {record.return_flag && (
          <span className="request-intake-return">
            <History size={14} aria-hidden="true" /> Retour SAV
          </span>
        )}
        {label && (
          <span className={`request-intake-coverage is-${record.warranty_status}`}>
            {record.warranty_status === "warranty" ? (
              <ShieldCheck size={14} aria-hidden="true" />
            ) : (
              <FileText size={14} aria-hidden="true" />
            )}
            {label}{provisional ? " — à vérifier" : ""}
          </span>
        )}
      </div>
      {detailed && record.return_flag && matches.length > 0 && (
        <details className="request-intake-prior-calls" open>
          <summary>Anciens dossiers retrouvés pour cet onduleur</summary>
          <ul>
            {matches.map((previous) => (
              <li key={`${previous.id}:${previous.relation}`}>
                <strong>Appel TVM {previous.call_number}</strong>
                {previous.client_reference && <span>Appel client : {previous.client_reference}</span>}
                <span>
                  {previous.arrived_at
                    ? `Arrivé le ${dateFR(previous.arrived_at, true)}`
                    : `Dossier créé le ${dateFR(previous.created_at, true)} — arrivée non renseignée`}
                </span>
                {previous.relation === "replacement" && (
                  <span>Ancien S/N lié au remplacement : {previous.serial_number}</span>
                )}
              </li>
            ))}
          </ul>
          {(history?.truncated || history?.matches?.length > 20) && <p>D’autres dossiers figurent dans l’historique de l’onduleur.</p>}
        </details>
      )}
    </div>
  );
}
