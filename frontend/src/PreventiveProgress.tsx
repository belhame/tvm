import { CalendarCheck2, Info } from "lucide-react";
import type { RecordData } from "./api";

/** Server counts belong to one dossier. A target never creates visits. */
export default function PreventiveProgress({
  record,
  compact = false,
}: {
  record: RecordData;
  compact?: boolean;
}) {
  const planned =
    Number.isInteger(record.planned_visit_count) &&
    record.planned_visit_count > 0
      ? (record.planned_visit_count as number)
      : null;
  const completed = Number.isInteger(record.preventive_completed_visit_count)
    ? (record.preventive_completed_visit_count as number)
    : null;
  const total = Number.isInteger(record.preventive_total_visit_count)
    ? (record.preventive_total_visit_count as number)
    : null;
  const remaining = Number.isInteger(record.preventive_remaining_visit_count)
    ? (record.preventive_remaining_visit_count as number)
    : null;
  const ratio =
    planned !== null && completed !== null
      ? Math.min(100, (completed / planned) * 100)
      : null;
  return (
    <section
      className={`preventive-progress ${compact ? "preventive-progress-compact" : ""}`}
      aria-label="Progression des visites préventives"
    >
      {!compact && (
        <span className="preventive-progress-icon">
          <CalendarCheck2 size={21} />
        </span>
      )}
      <div className="preventive-progress-content">
        {!compact && (
          <span className="preventive-progress-title">
            Campagne préventive du dossier
          </span>
        )}
        <strong>
          {planned !== null && completed !== null
            ? `${completed} / ${planned} visite${planned > 1 ? "s" : ""} réalisée${planned > 1 ? "s" : ""}`
            : "Prévision non renseignée"}
        </strong>
        {ratio !== null && (
          <div
            className="preventive-progress-track"
            role="progressbar"
            aria-label="Visites réalisées par rapport à l’objectif"
            aria-valuenow={Math.min(completed!, planned!)}
            aria-valuemin={0}
            aria-valuemax={planned!}
            aria-valuetext={`${completed} sur ${planned} visites réalisées`}
          >
            <span style={{ width: `${ratio}%` }} />
          </div>
        )}
        <div className="preventive-progress-meta">
          {remaining !== null && (
            <span>
              {remaining} visite{remaining > 1 ? "s" : ""} restante
              {remaining > 1 ? "s" : ""}
            </span>
          )}
          {total !== null && (
            <span>
              {total} fiche{total > 1 ? "s" : ""} préventive
              {total > 1 ? "s" : ""} enregistrée{total > 1 ? "s" : ""}
            </span>
          )}
          {planned === null && completed !== null && (
            <span>
              {completed} visite{completed > 1 ? "s" : ""} terminée
              {completed > 1 ? "s" : ""}
            </span>
          )}
        </div>
        {!compact && (
          <p>
            <Info size={13} />
            Objectif facultatif. Seules les fiches préventives terminées sont
            réalisées ; les fiches annulées sont exclues du total. Cet objectif
            ne crée aucune visite.
          </p>
        )}
      </div>
    </section>
  );
}
