import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Clock3,
  FileText,
  History,
  Info,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { dateFR } from "./api";
import { requestStatusLabels } from "./resources";
import type { SimpleSAVLookupResult } from "./simpleSAV";
import "./SimpleSAVLookup.css";

type Props = {
  result: SimpleSAVLookupResult;
  onOpenRequest?: (id: number) => void;
};

function reference(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function recordedDate(value: string | null | undefined) {
  return value && Number.isFinite(Date.parse(value))
    ? dateFR(value, true)
    : "Non renseignée";
}

const fallbackCoverageLabels = {
  active: "Garantie active",
  expired: "Devis / facturable",
  no_coverage: "Devis / facturable",
  unknown: "Garantie à vérifier",
  not_started: "Garantie à vérifier",
};

export default function SimpleSAVLookup({ result, onOpenRequest }: Props) {
  const {
    equipment,
    coverage,
    return_history: history,
    open_request: open,
  } = result;
  const provisionalQuotation =
    coverage.warranty_status === "quotation" && coverage.provisional;
  const warnings = [...new Set([...coverage.warnings, ...result.warnings])];
  const model =
    equipment.identification === "unknown" ? null : reference(equipment.model);
  const brand = reference(equipment.brand);
  const serial = reference(equipment.serial_number) || result.serial_number;

  return (
    <div
      className="simple-sav-lookup"
      aria-label="Résultat de la recherche SAV"
    >
      <section
        className={`simple-sav-coverage simple-sav-coverage-${coverage.status}`}
        aria-label="Garantie et orientation du dossier"
      >
        <div className="simple-sav-coverage-heading">
          <span className="simple-sav-lookup-icon">
            {coverage.status === "active" ? (
              <ShieldCheck size={23} />
            ) : coverage.warranty_status === "quotation" ? (
              <FileText size={23} />
            ) : (
              <Info size={23} />
            )}
          </span>
          <div>
            <span className="simple-sav-section-label">
              Garantie et orientation SAV
            </span>
            <h3 role="status" aria-live="polite">
              {coverage.label || fallbackCoverageLabels[coverage.status]}
            </h3>
          </div>
          {coverage.provisional && (
            <span className="simple-sav-provisional-badge">À confirmer</span>
          )}
        </div>
        <div className="simple-sav-coverage-detail">
          {provisionalQuotation && (
            <strong className="simple-sav-financial-orientation">
              <Clock3 size={16} />
              Devis / facturable provisoire
            </strong>
          )}
          {coverage.provisional && (
            <p>
              Cette indication est provisoire. Vérifiez la couverture avant de
              confirmer la situation de garantie.
            </p>
          )}
          <p className="simple-sav-financial-note">
            <Info size={15} />
            Cette orientation ne crée aucun devis PDF ni aucune facture.
          </p>
        </div>
      </section>

      {history.is_return && (
        <section
          className="simple-sav-return-alert"
          aria-label="Retour SAV identifié"
        >
          <span className="simple-sav-return-icon">
            <History size={25} />
          </span>
          <div>
            <strong>RETOUR — historique SAV retrouvé</strong>
            <p>
              Des dossiers antérieurs sont liés à cet onduleur ou à son
              remplacement. Consultez les références ci-dessous pour préparer
              son suivi.
            </p>
          </div>
        </section>
      )}

      <section className="simple-sav-identity" aria-label="Équipement retrouvé">
        <div className="simple-sav-identity-heading">
          <span className="simple-sav-lookup-icon">
            <Zap size={20} />
          </span>
          <div>
            <h3>{model || "Modèle non identifié"}</h3>
            <p>
              {equipment.identification === "recorded"
                ? "Équipement enregistré"
                : equipment.identification === "catalogue"
                  ? "Modèle retrouvé dans le catalogue"
                  : "Identification à compléter"}
            </p>
          </div>
        </div>
        <dl className="simple-sav-identity-facts">
          <div>
            <dt>Client</dt>
            <dd>{result.client.name}</dd>
          </div>
          <div>
            <dt>Numéro de série</dt>
            <dd className="simple-sav-serial">{serial}</dd>
          </div>
          <div>
            <dt>Marque</dt>
            <dd>{brand || "Non renseignée"}</dd>
          </div>
          <div>
            <dt>Modèle</dt>
            <dd>{model || "Modèle non identifié"}</dd>
          </div>
        </dl>
        {!model && (
          <p className="simple-sav-model-note">
            <Info size={15} />
            L’identification du modèle pourra être complétée ultérieurement.
          </p>
        )}
      </section>

      {open && (
        <section
          className="simple-sav-existing-request"
          aria-label="Demande SAV déjà ouverte"
        >
          <div className="simple-sav-existing-heading">
            <AlertCircle size={20} />
            <h3>Demande SAV déjà ouverte</h3>
          </div>
          <p>Une demande ouverte est déjà rattachée à cette série.</p>
          <div className="simple-sav-reference-block">
            <span>N° d’appel TVM</span>
            <strong>{reference(open.call_number) || "Non renseigné"}</strong>
            {reference(open.client_reference) !== null && (
              <>
                <span>N° d’appel client</span>
                <strong>{open.client_reference}</strong>
              </>
            )}
          </div>
          <dl className="simple-sav-existing-facts">
            <div>
              <dt>État</dt>
              <dd>{requestStatusLabels[open.status] || open.status}</dd>
            </div>
            <div>
              <dt>Arrivée enregistrée</dt>
              <dd>{recordedDate(open.arrived_at)}</dd>
            </div>
            {open.arrival_courier?.name && (
              <div>
                <dt>Livreur d’arrivée</dt>
                <dd>{open.arrival_courier.name}</dd>
              </div>
            )}
          </dl>
          {onOpenRequest && (
            <button
              type="button"
              className="button secondary"
              onClick={() => onOpenRequest(open.id)}
            >
              <ClipboardList size={16} />
              Ouvrir la demande <ArrowRight size={15} />
            </button>
          )}
        </section>
      )}

      {history.matches.length > 0 && (
        <section
          className="simple-sav-history"
          aria-label="Dossiers SAV antérieurs"
        >
          <div className="simple-sav-history-heading">
            <History size={18} />
            <h3>Dossiers SAV antérieurs</h3>
            <span>
              {history.matches.length} référence
              {history.matches.length > 1 ? "s" : ""}
            </span>
          </div>
          <div className="simple-sav-history-list">
            {history.matches.map((entry) => (
              <article className="simple-sav-history-card" key={entry.id}>
                <div className="simple-sav-history-card-heading">
                  <div>
                    <span>N° d’appel TVM</span>
                    <strong>
                      {reference(entry.call_number) || "Non renseigné"}
                    </strong>
                  </div>
                  <span className="simple-sav-relation">
                    {entry.relation === "replacement"
                      ? "Équipement de remplacement"
                      : "Même équipement"}
                  </span>
                </div>
                {reference(entry.client_reference) !== null && (
                  <div className="simple-sav-history-client-reference">
                    <span>N° d’appel client</span>
                    <strong>{entry.client_reference}</strong>
                  </div>
                )}
                <dl>
                  <div>
                    <dt>Création du dossier</dt>
                    <dd>{recordedDate(entry.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Arrivée enregistrée</dt>
                    <dd>{recordedDate(entry.arrived_at)}</dd>
                  </div>
                  <div>
                    <dt>Numéro de série</dt>
                    <dd className="simple-sav-serial">{entry.serial_number}</dd>
                  </div>
                </dl>
                {onOpenRequest && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => onOpenRequest(entry.id)}
                  >
                    Ouvrir la demande {entry.call_number}{" "}
                    <ArrowRight size={14} />
                  </button>
                )}
              </article>
            ))}
          </div>
          {history.truncated && (
            <p className="simple-sav-history-truncated">
              <Info size={15} />
              Historique partiel : d’autres dossiers liés ne sont pas affichés.
            </p>
          )}
        </section>
      )}
      {!history.is_return && history.matches.length === 0 && (
        <p className="simple-sav-no-return">
          <CheckCircle2 size={15} />
          Aucun retour identifié dans les dossiers autorisés.
        </p>
      )}
      {warnings.length > 0 && (
        <section
          className="simple-sav-lookup-warnings"
          aria-label="Points à vérifier"
        >
          <div>
            <AlertCircle size={17} />
            <strong>Points à vérifier</strong>
          </div>
          <ul>
            {warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
