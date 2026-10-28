import {
  AlertTriangle,
  CalendarDays,
  Info,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { useId } from "react";
import { warrantyScopeLabel, type WarrantyCheck } from "./warranty";
import "./WarrantyCheck.css";

export function warrantyDate(value: string | null | undefined) {
  if (!value) return "À déterminer";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "Date non exploitable";
}

const labels: Record<WarrantyCheck["status"], string> = {
  active: "Garantie en cours",
  expired: "Garantie expirée",
  not_started: "Garantie à venir",
  no_coverage: "Aucune couverture retenue",
  unknown: "Garantie à vérifier",
};

function Fact({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value === null || value === undefined || value === ""
          ? "À déterminer"
          : value}
      </dd>
    </div>
  );
}

/** Read-only presentation: all dates and coverage decisions are calculated by the server. */
export default function WarrantyCheckCard({ check }: { check: WarrantyCheck }) {
  const id = useId();
  const tone =
    check.status === "active"
      ? "green"
      : ["expired", "no_coverage"].includes(check.status)
        ? "red"
        : "amber";
  const Icon =
    tone === "green" ? ShieldCheck : tone === "red" ? ShieldX : AlertTriangle;
  const source = check.source;
  const manufactureBasis = check.manufacture_date_basis;
  const manufactureLabel =
    manufactureBasis?.precision === "week"
      ? "Fabrication · lundi de référence"
      : manufactureBasis?.precision === "month"
        ? "Fabrication · précision au mois"
        : manufactureBasis?.type === "recorded"
          ? "Fabrication enregistrée"
          : "Date de fabrication";
  return (
    <section
      className={`warranty-check warranty-check-${tone}`}
      aria-labelledby={`${id}-title`}
    >
      <header className="warranty-check-heading">
        <span className="warranty-check-icon">
          <Icon size={24} />
        </span>
        <div>
          <span className="warranty-check-eyebrow">
            Vérification de garantie
          </span>
          <h3 id={`${id}-title`}>{labels[check.status]}</h3>
        </div>
        <span className="warranty-check-origin">
          {check.basis === "recorded"
            ? "Garantie enregistrée"
            : check.basis === "catalogue"
              ? "Calcul catalogue"
              : "Origine à déterminer"}
        </span>
      </header>
      {check.provisional && (
        <p className="warranty-check-provisional">
          <AlertTriangle size={16} />
          Indication provisoire — couverture à confirmer.
        </p>
      )}
      <dl className="warranty-check-product">
        <Fact label="Marque retenue" value={check.manufacturer} />
        <Fact label="Structure de série" value={check.profile} />
        <Fact label="Gamme exacte" value={check.family} />
        <Fact label="Génération" value={check.generation} />
        <Fact label="Modèle identifié" value={check.model_name} />
        <Fact
          label="Référence industrielle · Industrial P/N"
          value={check.industrial_part_number}
        />
        <Fact
          label="Référence commerciale · Catalogue Number"
          value={check.commercial_part_number}
        />
      </dl>
      <dl className="warranty-check-dates">
        <Fact
          label={manufactureLabel}
          value={warrantyDate(check.manufactured_on)}
        />
        <Fact label="Début de garantie" value={warrantyDate(check.starts_on)} />
        <Fact label="Fin de garantie" value={warrantyDate(check.ends_on)} />
        <Fact
          label="Durée de garantie"
          value={
            check.duration_months === null
              ? null
              : `${check.duration_months} mois`
          }
        />
      </dl>
      {(manufactureBasis?.precision === "week" ||
        manufactureBasis?.precision === "month" ||
        manufactureBasis?.reconstructed) && (
        <p className="warranty-check-rule">
          <CalendarDays size={16} />
          <span>
            {manufactureBasis.precision === "week"
              ? "Date indicative : lundi de la semaine ISO décodée, et non jour de fabrication certifié."
              : manufactureBasis.precision === "month"
                ? "Le numéro de série indique uniquement le mois ; aucun jour de fabrication n’est certifié."
                : "La date de référence est reconstruite et doit être vérifiée."}
            {manufactureBasis.reconstructed
              ? " Date reconstruite à partir du profil de série."
              : ""}
          </span>
        </p>
      )}
      {manufactureBasis?.source && (
        <p className="warranty-check-rule">
          <Info size={15} />
          <span>
            Origine de la date de fabrication : {manufactureBasis.source}
          </span>
        </p>
      )}
      <p className="warranty-check-scope">
        <ShieldCheck size={15} />
        Couverture : {warrantyScopeLabel(check.scope)}
      </p>
      <p className="warranty-check-rule">
        <Info size={16} />
        <span>
          {check.basis === "recorded"
            ? "Les dates enregistrées restent prioritaires. La règle TVM de fabrication + 6 mois calendaires concerne le calcul indicatif du catalogue."
            : "Règle TVM : début de garantie = date de fabrication + 6 mois calendaires. La durée provient de la référence de garantie retenue."}{" "}
          Cette consultation ne modifie aucune date.
        </span>
      </p>
      {check.warnings.length > 0 && (
        <ul className="warranty-check-warnings">
          {[...new Set(check.warnings)].map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      <footer className="warranty-check-source">
        <span>
          <CalendarDays size={14} />
          Vérifiée le {warrantyDate(check.checked_on)}
        </span>
        {source?.catalogue_import_id != null && (
          <span>
            Catalogue importé n° {source.catalogue_import_id}
            {source.revision ? ` · Révision ${source.revision}` : ""}
          </span>
        )}
        {source?.product_sheet && (
          <span>
            Produit : {source.product_sheet}
            {source.product_row != null ? ` · ligne ${source.product_row}` : ""}
          </span>
        )}
        {source?.warranty_sheet && (
          <span>
            Garantie : {source.warranty_sheet}
            {source.warranty_row != null
              ? ` · ligne ${source.warranty_row}`
              : ""}
          </span>
        )}
      </footer>
    </section>
  );
}
