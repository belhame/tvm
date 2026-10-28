import {
  AlertCircle,
  CalendarDays,
  ClipboardList,
  FileText,
  History,
  Info,
  PackageCheck,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { dateFR, type User } from "./api";
import CallReference from "./CallReference";
import WarrantyCheckCard from "./WarrantyCheckCard";
import { warrantyScopeLabel, type WarrantyCheck } from "./warranty";

export type SerialLookupProduct = {
  id: number;
  import_id: number;
  range_name: string;
  product_name: string;
  product_code: string;
  structure: string;
  launch_year: string;
  manufacturing_part_number: string;
  catalogue_number: string;
  market_status: string;
  replacement_product: string;
  replacement_part_number: string;
  version: string;
  return_text: string;
  source_sheet: string;
  source_row: number;
  raw_data: Record<string, unknown>;
  code_is_usable: boolean;
  code_is_ambiguous: boolean;
  equipment_model_suggestion: string | null;
};

export type SerialLookupCandidate = SerialLookupProduct;

export type SerialLookupEquipment = {
  id: number;
  client: number;
  client_name: string;
  serial_number: string;
  brand: string;
  model: string;
  power_kva: string | number;
  location: string;
  commissioned_on: string | null;
  manufactured_on: string | null;
  catalogue_product: number | null;
  warranty_until: string | null;
  status: string;
  legacy_id?: string | null;
  [key: string]: unknown;
};

export type SerialLookupComputedWarranty = {
  status:
    | "estimated"
    | "recorded_priority"
    | "no_coverage"
    | "needs_choice"
    | "manufacture_unknown"
    | "unavailable";
  starts_on: string | null;
  ends_on: string | null;
  duration_months: number | null;
  warranty_id: number | null;
  coverage_status:
    | "active"
    | "expired"
    | "not_started"
    | "not_covered"
    | "unknown";
  rule: {
    code: string;
    start_offset_months: number;
  };
};

export type SerialLookupWarrantyOption = {
  id: number;
  import_id: number;
  scope: string;
  category: string;
  product_name: string;
  brand_group: string;
  duration_text: string;
  duration_months: number | null;
  conditions: string;
  source_sheet: string;
  source_row: number;
  source_column: string | number;
  raw_data: Record<string, unknown>;
  match_type: "exact_range" | "related_manual";
  computed_warranty: SerialLookupComputedWarranty;
};

export type SerialLookupRecordedWarranty = {
  id: number;
  equipment: number;
  equipment_serial: string;
  client_name: string;
  provider: string;
  starts_on: string;
  ends_on: string;
  terms: string;
  legacy_id?: string | null;
  [key: string]: unknown;
};

export type SerialLookupRequest = {
  id: number;
  reference: string;
  subject: string;
  status: string;
  created_at: string;
  priority?: string;
  [key: string]: unknown;
};

export type SerialLookupIntervention = {
  id: number;
  reference: string;
  request_reference: string;
  technician_name: string;
  status: string;
  scheduled_at: string | null;
  created_at: string;
  [key: string]: unknown;
};

export type SerialLookupContract = {
  id: number;
  number: string;
  client: number;
  client_name: string;
  equipment: number | null;
  starts_on: string;
  ends_on: string;
  coverage: string;
  visits_per_year: number;
  status: string;
  legacy_id?: string | null;
  [key: string]: unknown;
};

export type SerialLookupResult = {
  warranty_check?: WarrantyCheck;
  catalogue_computed_warranty?: SerialLookupComputedWarranty;
  serial_number: string;
  normalized_serial_number: string;
  catalogue_import_id: number | null;
  catalogue_import: {
    id: number;
    filename: string;
    sha256: string;
    metadata: Record<string, unknown>;
  } | null;
  existing_equipment: SerialLookupEquipment | null;
  history: {
    requests: SerialLookupRequest[];
    interventions: SerialLookupIntervention[];
  };
  product_candidates: SerialLookupProduct[];
  selected_product_id: number | null;
  selected_product?: SerialLookupProduct | null;
  detection: {
    status:
      | "matched"
      | "ambiguous"
      | "not_applicable"
      | "catalogue_unavailable";
    profile: string | null;
    profile_options: string[];
    format: string | null;
    segments: Record<string, unknown> | null;
    year: number | null;
    week: number | null;
    requires_product_choice: boolean;
    requires_profile_choice: boolean;
  };
  manufactured_on: string | null;
  manufacture_date_basis: {
    type:
      | "iso_week"
      | "reconstructed_iso_week"
      | "month_only"
      | "unproven"
      | "recorded"
      | null;
    reconstructed: boolean;
    source: string;
    precision: "day" | "week" | "month" | "unknown";
    blocked_reason: string | null;
  };
  warranty_options: SerialLookupWarrantyOption[];
  default_warranty_id: number | null;
  selected_warranty?: SerialLookupWarrantyOption | null;
  computed_warranty: SerialLookupComputedWarranty;
  recorded_warranties: SerialLookupRecordedWarranty[];
  active_contracts: SerialLookupContract[];
  warnings: string[];
};

const requestStatuses: Record<string, string> = {
  new: "Nouvelle",
  scheduled: "Planifiée",
  in_progress: "En cours",
  resolved: "Résolue",
  closed: "Clôturée",
};

const interventionStatuses: Record<string, string> = {
  scheduled: "Planifiée",
  in_progress: "En cours",
  testing: "En test",
  completed: "Terminée",
  cancelled: "Annulée",
};

const detectionLabels: Record<
  SerialLookupResult["detection"]["status"],
  string
> = {
  matched: "Correspondance trouvée",
  ambiguous: "Correspondance à préciser",
  not_applicable: "Série hors format catalogue",
  catalogue_unavailable: "Catalogue indisponible",
};

const coverageLabels: Record<
  SerialLookupComputedWarranty["coverage_status"],
  string
> = {
  active: "En cours",
  expired: "Expirée",
  not_started: "À venir",
  not_covered: "Aucune couverture",
  unknown: "À vérifier",
};

const computedLabels: Record<SerialLookupComputedWarranty["status"], string> = {
  estimated: "Garantie calculée selon la règle TVM",
  recorded_priority: "Garantie enregistrée prioritaire",
  no_coverage: "Aucune garantie applicable selon la référence retenue",
  needs_choice: "Choix de garantie requis",
  manufacture_unknown: "Fabrication à déterminer",
  unavailable: "Garantie non déterminée",
};

const precisionLabels: Record<
  SerialLookupResult["manufacture_date_basis"]["precision"],
  string
> = {
  day: "Précision : jour",
  week: "Date de référence : lundi de la semaine ISO",
  month: "Précision : mois uniquement",
  unknown: "Précision non déterminée",
};

function text(
  value: string | number | null | undefined,
  fallback = "Non déterminé",
) {
  return value === null || value === undefined || value === ""
    ? fallback
    : String(value);
}

function date(value: string | null | undefined, withTime = false) {
  if (!value) return "Non déterminée";
  if (Number.isNaN(new Date(value).getTime())) return "Date non exploitable";
  if (!withTime && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-");
    return `${day}/${month}/${year}`;
  }
  return dateFR(value, withTime);
}

function duration(value: number | null) {
  return value === null ? "Non précisée" : `${value} mois`;
}

function Fact({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`serial-lookup-fact ${className}`}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** Display only: every date, status and history entry comes from the lookup API. */
export default function SerialLookupSummary({
  result,
  candidate,
  role = "manager",
}: {
  result: SerialLookupResult;
  candidate?: SerialLookupCandidate | null;
  role?: User["role"];
}) {
  const product =
    candidate ??
    result.selected_product ??
    (result.selected_product_id === null
      ? undefined
      : result.product_candidates.find(
          (item) => item.id === result.selected_product_id,
        ));
  const computed = result.computed_warranty;
  const selectedWarranty =
    result.selected_warranty ??
    (computed.warranty_id === null
      ? undefined
      : result.warranty_options.find(
          (item) => item.id === computed.warranty_id,
        ));
  const equipment = result.existing_equipment;
  const hasRecordedWarranty =
    result.recorded_warranties.length > 0 || !!equipment?.warranty_until;
  const coverageClass =
    computed.coverage_status === "active"
      ? "green"
      : computed.coverage_status === "expired"
        ? "red"
        : computed.coverage_status === "not_covered"
          ? "gray"
          : "amber";

  return (
    <section
      className="serial-lookup-summary"
      aria-label="Identification et couverture de l’équipement"
    >
      <div className="serial-lookup-summary-heading">
        <div className="serial-lookup-summary-title">
          <PackageCheck size={19} />
          <div>
            <h3>Identification & couverture</h3>
            <p>{result.normalized_serial_number || result.serial_number}</p>
          </div>
        </div>
        <span
          className={`badge ${result.detection.status === "matched" ? "blue" : "amber"}`}
        >
          {detectionLabels[result.detection.status]}
        </span>
      </div>

      {equipment && (
        <div className="serial-lookup-existing">
          <CheckEquipmentIcon />
          <div>
            <strong>Équipement déjà enregistré</strong>
            <p>
              {equipment.model} · {equipment.client_name}
              {equipment.location ? ` · ${equipment.location}` : ""}
            </p>
          </div>
        </div>
      )}

      <div className="serial-lookup-grid">
        <section
          className="serial-lookup-card serial-lookup-product"
          aria-label="Identification du produit"
        >
          <div className="serial-lookup-card-heading">
            <PackageCheck size={17} />
            <h4>Produit identifié</h4>
          </div>
          <dl className="serial-lookup-facts">
            <Fact
              label="Structure de série"
              value={text(result.detection.profile || product?.structure)}
            />
            <Fact
              label="Modèle court · Catalogue Number"
              value={text(product?.catalogue_number)}
            />
            <Fact
              label="Nom complet du produit"
              value={text(product?.product_name)}
              className="serial-lookup-fact-wide"
            />
            <Fact
              label="Version"
              value={text(product?.version, "Non fournie")}
            />
            <Fact
              label="Industrial P/N"
              value={text(product?.manufacturing_part_number, "Non fourni")}
            />
            <Fact
              label="Code produit"
              value={text(product?.product_code, "Non fourni")}
            />
            <Fact
              label="Gamme"
              value={text(product?.range_name, "Non fournie")}
            />
          </dl>
          {!product && (
            <p className="serial-lookup-note">
              <Info size={14} />
              {result.product_candidates.length > 1
                ? "Plusieurs produits sont proposés. Sélectionnez explicitement le candidat correspondant avant de retenir ses références."
                : "Aucun produit n’est sélectionné. Les références ne sont pas déduites automatiquement."}
            </p>
          )}
          {product?.code_is_ambiguous && (
            <p className="serial-lookup-note">
              <AlertCircle size={14} />
              Ce code est partagé par plusieurs références. Le produit présenté
              correspond au candidat sélectionné explicitement.
            </p>
          )}
        </section>

        <section
          className="serial-lookup-card serial-lookup-manufacture"
          aria-label="Date de fabrication"
        >
          <div className="serial-lookup-card-heading">
            <CalendarDays size={17} />
            <h4>Fabrication</h4>
          </div>
          <dl className="serial-lookup-facts">
            <Fact
              label="Date de référence de fabrication"
              value={date(result.manufactured_on)}
              className="serial-lookup-fact-wide"
            />
            <Fact label="Année décodée" value={text(result.detection.year)} />
            <Fact label="Semaine décodée" value={text(result.detection.week)} />
          </dl>
          <p className="serial-lookup-precision">
            {precisionLabels[result.manufacture_date_basis.precision]}
            {result.manufacture_date_basis.reconstructed
              ? " · Date reconstruite"
              : ""}
          </p>
          {result.manufacture_date_basis.source && (
            <p className="serial-lookup-source">
              Source : {result.manufacture_date_basis.source}
            </p>
          )}
          {result.manufacture_date_basis.blocked_reason && (
            <p className="serial-lookup-note">
              <AlertCircle size={14} />
              {result.manufacture_date_basis.blocked_reason}
            </p>
          )}
        </section>
      </div>

      {result.warranty_check && (
        <WarrantyCheckCard check={result.warranty_check} />
      )}
      {result.warranty_check && hasRecordedWarranty && (
        <section
          className="serial-lookup-card serial-lookup-recorded-warranties"
          aria-label="Garanties déjà enregistrées"
        >
          <h4>Garanties enregistrées prioritaires</h4>
          {result.recorded_warranties.length > 0 ? (
            <ul>
              {result.recorded_warranties.map((warranty) => (
                <li key={warranty.id}>
                  <div>
                    <strong>
                      {warranty.provider || "Garantie enregistrée"}
                    </strong>
                    <span>
                      {date(warranty.starts_on)} → {date(warranty.ends_on)}
                    </span>
                  </div>
                  {warranty.terms && <p>{warranty.terms}</p>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="serial-lookup-note">
              Fin de garantie enregistrée dans la fiche équipement :{" "}
              <strong>{date(equipment?.warranty_until)}</strong>. Le début et la
              durée ne sont pas déduits de cette seule date.
            </p>
          )}
        </section>
      )}

      {!result.warranty_check && (
        <section
          className="serial-lookup-card serial-lookup-warranty"
          aria-label="Couverture de garantie"
        >
          <div className="serial-lookup-card-heading">
            <ShieldCheck size={17} />
            <h4>Garantie</h4>
            <span className={`badge ${coverageClass}`}>
              {coverageLabels[computed.coverage_status]}
            </span>
          </div>
          <p
            className={`serial-lookup-warranty-basis ${computed.status === "recorded_priority" ? "recorded" : ""}`}
          >
            <ShieldCheck size={15} />
            {computedLabels[computed.status]}
          </p>
          <dl className="serial-lookup-facts serial-lookup-warranty-dates">
            <Fact label="Début de garantie" value={date(computed.starts_on)} />
            <Fact label="Fin de garantie" value={date(computed.ends_on)} />
            <Fact
              label="Durée retenue"
              value={duration(computed.duration_months)}
            />
          </dl>
          {selectedWarranty && (
            <div className="serial-lookup-warranty-option">
              <strong>
                {selectedWarranty.category ||
                  selectedWarranty.product_name ||
                  "Garantie catalogue sélectionnée"}
              </strong>
              <p>
                {warrantyScopeLabel(selectedWarranty.scope)}
                {selectedWarranty.duration_text
                  ? ` · Durée source : ${selectedWarranty.duration_text}`
                  : ""}
              </p>
              {selectedWarranty.conditions && (
                <p>{selectedWarranty.conditions}</p>
              )}
            </div>
          )}
          <p className="serial-lookup-rule">
            <Info size={15} />
            <span>
              <strong>Règle TVM :</strong> début estimé = date de fabrication +
              6 mois calendaires. La fin dépend de la durée de garantie retenue.
              Une date de fabrication limitée au mois ou non justifiée ne permet
              pas ce calcul.
            </span>
          </p>
          {hasRecordedWarranty && (
            <div className="serial-lookup-recorded-warranties">
              <p className="serial-lookup-recorded-priority">
                <ShieldCheck size={15} />
                Les garanties enregistrées sont prioritaires sur le calcul
                indicatif.
              </p>
              {result.recorded_warranties.length > 0 ? (
                <ul>
                  {result.recorded_warranties.map((warranty) => (
                    <li key={warranty.id}>
                      <div>
                        <strong>
                          {warranty.provider || "Garantie enregistrée"}
                        </strong>
                        <span>
                          {date(warranty.starts_on)} → {date(warranty.ends_on)}
                        </span>
                      </div>
                      {warranty.terms && <p>{warranty.terms}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="serial-lookup-note">
                  Fin de garantie enregistrée dans la fiche équipement :{" "}
                  <strong>{date(equipment?.warranty_until)}</strong>. Le début
                  et la durée ne sont pas déduits de cette seule date.
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <section
        className="serial-lookup-card serial-lookup-contracts"
        aria-label="Contrats de maintenance en cours"
      >
        <div className="serial-lookup-card-heading">
          <FileText size={17} />
          <h4>Contrats de maintenance en cours</h4>
          <span className="badge blue">{result.active_contracts.length}</span>
        </div>
        <p className="serial-lookup-section-note">
          Les contrats de maintenance sont distincts de la garantie
          constructeur.
        </p>
        {result.active_contracts.length === 0 ? (
          <p className="serial-lookup-empty">
            Aucun contrat actif n’a été retourné pour ce périmètre.
          </p>
        ) : (
          <ul className="serial-lookup-contract-list">
            {result.active_contracts.map((contract) => (
              <li key={contract.id}>
                <div>
                  <strong>{contract.number}</strong>
                  <span className="badge green">
                    {contract.status === "active"
                      ? "Actif"
                      : contract.status === "expired"
                        ? "Expiré"
                        : contract.status === "draft"
                          ? "Brouillon"
                          : contract.status}
                  </span>
                </div>
                <p>
                  {date(contract.starts_on)} → {date(contract.ends_on)} ·{" "}
                  {contract.equipment === null
                    ? "Contrat client"
                    : "Contrat équipement"}
                </p>
                {contract.coverage && <p>{contract.coverage}</p>}
                <span>
                  {contract.visits_per_year} visite
                  {contract.visits_per_year > 1 ? "s" : ""} prévue
                  {contract.visits_per_year > 1 ? "s" : ""} par an
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        className="serial-lookup-card serial-lookup-history"
        aria-label="Historique SAV"
      >
        <div className="serial-lookup-card-heading">
          <History size={17} />
          <h4>Historique SAV de cet équipement</h4>
        </div>
        {!equipment && (
          <p className="serial-lookup-section-note">
            Aucun équipement déjà enregistré n’a été retrouvé pour cette série.
          </p>
        )}
        <div className="serial-lookup-history-grid">
          <div className="serial-lookup-history-group">
            <h5>
              <ClipboardList size={15} />
              Demandes SAV <span>{result.history.requests.length}</span>
            </h5>
            {result.history.requests.length === 0 ? (
              <p className="serial-lookup-empty">
                Aucune demande SAV retrouvée.
              </p>
            ) : (
              <ul>
                {result.history.requests.map((request) => (
                  <li key={request.id}>
                    <div>
                      <CallReference record={request} role={role} compact />
                      <span className="badge">
                        {requestStatuses[request.status] || request.status}
                      </span>
                    </div>
                    <p>{request.subject}</p>
                    <span>Créée le {date(request.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="serial-lookup-history-group">
            <h5>
              <Wrench size={15} />
              Interventions <span>{result.history.interventions.length}</span>
            </h5>
            {result.history.interventions.length === 0 ? (
              <p className="serial-lookup-empty">
                Aucune intervention retrouvée.
              </p>
            ) : (
              <ul>
                {result.history.interventions.map((intervention) => (
                  <li key={intervention.id}>
                    <div>
                      <CallReference
                        record={intervention}
                        role={role}
                        visit
                        compact
                      />
                      <span className="badge">
                        {interventionStatuses[intervention.status] ||
                          intervention.status}
                      </span>
                    </div>
                    <p>
                      {intervention.technician_name
                        ? intervention.technician_name
                        : ""}
                    </p>
                    <span>
                      {intervention.scheduled_at
                        ? `Planifiée le ${date(intervention.scheduled_at, true)}`
                        : "Date d’intervention non planifiée"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      {result.warnings.length > 0 && (
        <div className="serial-lookup-warnings">
          <AlertCircle size={17} />
          <div>
            <strong>Points à vérifier</strong>
            <ul>
              {result.warnings.map((warning, index) => (
                <li key={`${index}-${warning}`}>{warning}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {result.catalogue_import && (
        <p className="serial-lookup-source">
          Catalogue : {result.catalogue_import.filename} · Version importée n°{" "}
          {result.catalogue_import.id}. La consultation ne modifie aucune
          donnée.
        </p>
      )}
    </section>
  );
}

function CheckEquipmentIcon() {
  return <PackageCheck size={18} />;
}
