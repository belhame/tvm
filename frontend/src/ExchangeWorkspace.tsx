import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  History,
  Info,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Search,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { api, dateFR, listResult, type RecordData, type User } from "./api";
import CallReference, { callPrimary } from "./CallReference";
import { statuses } from "./resources";
import { useServerTimingRefresh } from "./RequestTimer";
import type {
  SerialLookupProduct,
  SerialLookupResult,
} from "./SerialLookupSummary";

type ExchangeState =
  | "awaiting_preparation"
  | "pending_validation"
  | "validated"
  | "ready_for_delivery"
  | "invoiced"
  | "closed";
export type ExchangeProcess = {
  state: ExchangeState;
  replacement_serial_number?: string;
  replacement_model?: string;
  replacement_brand?: string;
  replacement_equipment?: number | null;
  validated_at?: string | null;
  validated_by_name?: string;
  ready_at?: string | null;
  ready_by_name?: string;
  invoice_reference?: string;
  invoiced_on?: string | null;
  billing_validated_at?: string | null;
  billing_validated_by_name?: string;
  billing_notes?: string;
  can_prepare?: boolean;
  can_validate?: boolean;
  can_mark_ready?: boolean;
  can_validate_billing?: boolean;
  can_close?: boolean;
  can_reset?: boolean;
};
type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
const exchangeLabels: Record<ExchangeState, string> = {
  awaiting_preparation: "À préparer / vérifier",
  pending_validation: "Validation technique en attente",
  validated: "Échange validé",
  ready_for_delivery: "Prêt à être livré",
  invoiced: "Facturation confirmée",
  closed: "Clôturé",
};
const approvedStates: ExchangeState[] = [
  "validated",
  "ready_for_delivery",
  "invoiced",
  "closed",
];
const text = (entry: unknown) =>
  typeof entry === "string" && entry.trim() ? entry : "Non renseigné";
const date = (entry?: string | null, withTime = false) =>
  entry ? dateFR(entry, withTime) : "Non renseignée";
function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{children}</span>
    </div>
  );
}

export function ExchangeBadge({
  exchange,
}: {
  exchange?: ExchangeProcess | null;
}) {
  const state = exchange?.state || "awaiting_preparation";
  return (
    <span className={`exchange-state exchange-state-${state}`}>
      {approvedStates.includes(state) ? (
        <CheckCircle2 size={13} />
      ) : (
        <Info size={13} />
      )}
      {exchangeLabels[state] || "Validation à vérifier"}
    </span>
  );
}

export default function ExchangeWorkspace({
  user,
  equipment,
  interventions,
  refreshKey,
  onChanged,
  onOpenRequest,
  onIntervention,
  Dialog,
  billing = false,
  initialSearch = "",
}: {
  user: User;
  equipment: RecordData[];
  interventions: RecordData[];
  refreshKey: unknown;
  onChanged: () => Promise<void>;
  onOpenRequest: (record: RecordData) => void;
  onIntervention: (record: RecordData) => void;
  Dialog: ComponentType<DialogProps>;
  billing?: boolean;
  initialSearch?: string;
}) {
  const [query, setQuery] = useState(initialSearch);
  const [rows, setRows] = useState<RecordData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<RecordData | null>(null);
  const [filter, setFilter] = useState("all");
  const [historyOpen, setHistoryOpen] = useState(false);
  useEffect(() => setQuery(initialSearch), [initialSearch]);
  useServerTimingRefresh(() => setRevision((value) => value + 1));
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setRows([]);
    const timer = window.setTimeout(
      () => {
        api(
          `${billing ? "exchanges/billing/" : "exchanges/"}?q=${encodeURIComponent(query.trim())}`,
          { signal: controller.signal },
        )
          .then((result) => {
            if (!controller.signal.aborted) setRows(listResult(result));
          })
          .catch((failure: Error) => {
            if (!controller.signal.aborted) setError(failure.message);
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, refreshKey, revision, billing]);
  const visible = rows.filter(
    (row) =>
      filter === "all" ||
      (row.exchange?.state || "awaiting_preparation") === filter,
  );
  const history = interventions.filter(
    (row) =>
      row.kind === "exchange" &&
      JSON.stringify(row)
        .toLocaleLowerCase("fr")
        .includes(query.toLocaleLowerCase("fr")),
  );
  const client = user.role === "client";
  return (
    <div className="exchange-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {billing ? "FACTURATION & CLÔTURE" : "REMPLACEMENT & LIVRAISON"}
          </div>
          <h1>{billing ? "Échanges à facturer" : "Échanges d’onduleurs"}</h1>
          <p>
            {billing
              ? "Vérifiez les échanges, confirmez les références des factures émises puis clôturez les dossiers."
              : client
                ? "Consultez le remplacement validé et l’avancement de la livraison de vos équipements."
                : "Les demandes placées en Échange apparaissent ici, avec ou sans fiche de visite."}
          </p>
        </div>
        <span className="heading-chip">
          {billing ? <FileText size={18} /> : <Truck size={18} />}
          {loading
            ? "Actualisation…"
            : `${rows.length} dossier${rows.length > 1 ? "s" : ""}`}
        </span>
      </div>
      {!client && (
        <div className="exchange-workflow-guide">
          <span>
            <ClipboardCheck size={17} />
            1. Préparer le remplacement
          </span>
          <ArrowRight size={15} />
          <span>
            <ShieldCheck size={17} />
            2. Valider l’échange
          </span>
          <ArrowRight size={15} />
          <span>
            <Truck size={17} />
            3. Prêt à être livré
          </span>
          <ArrowRight size={15} />
          <span>
            <FileText size={17} />
            4. Confirmer la facturation
          </span>
        </div>
      )}
      <section
        className="card exchange-queue"
        aria-label={
          billing ? "File de facturation des échanges" : "Demandes d’échange"
        }
      >
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label={
                billing
                  ? "Rechercher un échange à facturer"
                  : "Rechercher un échange"
              }
              placeholder={
                client
                  ? "Votre n° d’appel client, n° TVM ou numéro de série…"
                  : "N° TVM, n° d’appel client, client, série d’origine ou de remplacement…"
              }
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="filter-select">
            <select
              aria-label="Filtrer l’étape de l’échange"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">Toutes les étapes</option>
              {Object.entries(exchangeLabels).map(([key, label]) => (
                <option value={key} key={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {error && (
          <ErrorMessage>
            {error}
            <button
              type="button"
              className="button secondary small"
              onClick={() => setRevision((value) => value + 1)}
            >
              Réessayer
            </button>
          </ErrorMessage>
        )}
        {loading ? (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            Chargement des échanges…
          </div>
        ) : visible.length ? (
          <div className="table-scroll">
            <table
              className={
                billing ? "exchange-billing-table" : "exchange-requests-table"
              }
            >
              <thead>
                <tr>
                  <th>
                    {client
                      ? "Votre n° d’appel client / TVM"
                      : "N° d’appel TVM / client"}
                  </th>
                  <th>Client</th>
                  <th>Onduleur d’origine</th>
                  <th>Matériel de remplacement</th>
                  <th>Étape</th>
                  <th>Validation technique</th>
                  {billing && <th>Facturation</th>}
                  <th>
                    <span className="sr-only">Actions échange</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => {
                  const exchange = row.exchange as ExchangeProcess | undefined;
                  const publicApproved =
                    exchange &&
                    approvedStates.includes(exchange.state) &&
                    !!exchange.validated_at;
                  return (
                    <tr key={row.id}>
                      <td>
                        <CallReference record={row} role={user.role} compact />
                        <small className="exchange-subject">
                          {row.subject}
                        </small>
                      </td>
                      <td>{row.client_name}</td>
                      <td>
                        <div className="primary-cell">
                          <span className="serial-text">
                            {row.equipment_serial ||
                              equipment.find(
                                (entry) => entry.id === row.equipment,
                              )?.serial_number}
                          </span>
                          <small>
                            {row.equipment_model ||
                              equipment.find(
                                (entry) => entry.id === row.equipment,
                              )?.model ||
                              "Modèle non renseigné"}
                          </small>
                        </div>
                      </td>
                      <td>
                        <div className="primary-cell">
                          <span className="serial-text">
                            {!client || publicApproved
                              ? exchange?.replacement_serial_number ||
                                "À renseigner"
                              : "Remplacement en préparation"}
                          </span>
                          <small>
                            {!client || publicApproved
                              ? exchange?.replacement_model ||
                                "Modèle à confirmer"
                              : ""}
                          </small>
                        </div>
                      </td>
                      <td>
                        <ExchangeBadge exchange={exchange} />
                      </td>
                      <td>
                        {exchange?.validated_at ? (
                          <div className="primary-cell">
                            <span>{date(exchange.validated_at, true)}</span>
                            {!client && (
                              <small>{exchange.validated_by_name}</small>
                            )}
                          </div>
                        ) : (
                          "À valider explicitement"
                        )}
                      </td>
                      {billing && (
                        <td>
                          <div className="primary-cell">
                            <span>
                              {exchange?.billing_validated_at
                                ? "Facturation confirmée"
                                : "Facturation en attente"}
                            </span>
                            <small>
                              {exchange?.invoice_reference ||
                                (publicApproved
                                  ? "Référence non renseignée"
                                  : "Validation technique requise")}
                            </small>
                          </div>
                        </td>
                      )}
                      <td className="action-cell">
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={() => setSelected(row)}
                          aria-label={
                            !billing &&
                            exchange?.can_prepare &&
                            exchange.state === "awaiting_preparation"
                              ? `Préparer ${row.reference}`
                              : `Ouvrir l’échange ${row.reference}`
                          }
                        >
                          {!billing &&
                          exchange?.can_prepare &&
                          exchange.state === "awaiting_preparation" ? (
                            <Pencil size={14} />
                          ) : (
                            <ArrowRight size={14} />
                          )}
                          {!billing &&
                          exchange?.can_prepare &&
                          exchange.state === "awaiting_preparation"
                            ? "Préparer"
                            : "Ouvrir"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          !error && (
            <div className="empty-state">
              <Truck size={30} />
              <h3>Aucun échange dans cette vue</h3>
              <p>
                {query || filter !== "all"
                  ? "Essayez un autre numéro ou une autre étape."
                  : billing
                    ? "Les échanges nécessitant une vérification ou une confirmation de facturation apparaîtront ici."
                    : "Passez une demande SAV à l’état Échange pour préparer son remplacement."}
              </p>
            </div>
          )
        )}
        <div className="table-footer">
          <span>
            <ShieldCheck size={13} />
            Étapes validées séparément sur le serveur
          </span>
          <span>
            {visible.length} résultat{visible.length > 1 ? "s" : ""}
          </span>
        </div>
      </section>
      {!billing && (
        <section className="card exchange-legacy-history">
          <button
            type="button"
            className="exchange-history-toggle"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((open) => !open)}
          >
            <History size={18} />
            <span>Historique des fiches d’échange</span>
            <span>{history.length}</span>
          </button>
          {historyOpen && (
            <>
              <p>
                Une fiche de visite conserve l’historique de l’intervention. La
                validation technique du remplacement se vérifie séparément dans
                le dossier.
              </p>
              {history.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>N° d’appel / référence de visite</th>
                        <th>Client</th>
                        <th>Onduleur d’origine</th>
                        <th>État de la visite</th>
                        <th>Validation de l’échange</th>
                        <th>
                          <span className="sr-only">Consulter la visite</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((visit) => (
                        <tr key={visit.id}>
                          <td>
                            <CallReference
                              record={visit}
                              role={user.role}
                              visit
                              compact
                            />
                          </td>
                          <td>{visit.client_name}</td>
                          <td>{visit.equipment_serial}</td>
                          <td>{statuses[visit.status] || visit.status}</td>
                          <td>
                            {rows.find(
                              (row) => row.id === visit.service_request,
                            )?.exchange?.validated_at
                              ? "Validation enregistrée"
                              : "Validation à vérifier"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="icon-button"
                              aria-label={`Voir ${visit.reference}`}
                              onClick={() => onIntervention(visit)}
                            >
                              <ArrowRight size={17} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>Aucune fiche de visite d’échange enregistrée.</p>
              )}
            </>
          )}
        </section>
      )}
      {selected && (
        <Dialog
          title="Préparer et suivre l’échange"
          subtitle={callPrimary(selected, user.role)}
          onClose={() => setSelected(null)}
          wide
        >
          <div className="modal-content">
            <ExchangePanel
              key={`${selected.id}:${user.id}`}
              record={selected}
              equipment={equipment}
              user={user}
              billing={billing}
              onChanged={async (record) => {
                setSelected(record);
                await onChanged();
              }}
            />
            <button
              type="button"
              className="button secondary small exchange-open-dossier"
              onClick={() => {
                setSelected(null);
                onOpenRequest(selected);
              }}
            >
              <FileText size={16} />
              Ouvrir le dossier SAV
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

export function ExchangePanel({
  record: initialRecord,
  equipment,
  user,
  onChanged,
  billing = false,
}: {
  record: RecordData;
  equipment: RecordData[];
  user: User;
  onChanged: (record: RecordData) => Promise<void>;
  billing?: boolean;
}) {
  const id = useId();
  const [record, setRecord] = useState(initialRecord);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [serial, setSerial] = useState("");
  const [model, setModel] = useState("");
  const [brand, setBrand] = useState("Eaton");
  const [replacementId, setReplacementId] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [invoiceReference, setInvoiceReference] = useState("");
  const [invoicedOn, setInvoicedOn] = useState("");
  const [billingNotes, setBillingNotes] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [resetReason, setResetReason] = useState("");
  const [lookup, setLookup] = useState<SerialLookupResult | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);
  const mounted = useRef(true);
  const loadController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);
  const lookupController = useRef<AbortController | null>(null);
  const mutationPending = useRef(false);
  const generation = useRef(0);
  const lookupGeneration = useRef(0);
  const original = equipment.find((row) => row.id === record.equipment);
  const exchange = record.exchange as ExchangeProcess | undefined;
  const isClient = user.role === "client";
  const state = exchange?.state || "awaiting_preparation";
  const approved = !!exchange?.validated_at && approvedStates.includes(state);
  const finance =
    !isClient && (user.role === "admin" || user.can_validate_billing === true);
  useEffect(() => {
    setRecord(initialRecord);
  }, [initialRecord]);
  async function refresh() {
    loadController.current?.abort();
    const request = new AbortController();
    loadController.current = request;
    setLoading(true);
    setLoadError("");
    try {
      const fresh = await api<RecordData>(
        `requests/${initialRecord.id}/exchange/`,
        { signal: request.signal },
      );
      if (mounted.current && !request.signal.aborted) setRecord(fresh);
    } catch (failure) {
      if (mounted.current && !request.signal.aborted)
        setLoadError(
          failure instanceof Error
            ? failure.message
            : "L’échange n’a pas pu être actualisé.",
        );
    } finally {
      if (mounted.current && !request.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      generation.current += 1;
      lookupGeneration.current += 1;
      loadController.current?.abort();
      mutationController.current?.abort();
      lookupController.current?.abort();
    };
  }, [initialRecord.id]);
  function prepare() {
    lookupController.current?.abort();
    lookupGeneration.current += 1;
    setLookupBusy(false);
    setSerial(exchange?.replacement_serial_number || "");
    setModel(exchange?.replacement_model || "");
    setBrand(exchange?.replacement_brand || "Eaton");
    setReplacementId(exchange?.replacement_equipment || null);
    setConfirmed(false);
    setLookup(null);
    setLookupError("");
    setError("");
    setFormOpen(true);
  }
  function changeSerial(value: string) {
    lookupController.current?.abort();
    lookupGeneration.current += 1;
    setSerial(value);
    setReplacementId(null);
    setModel("");
    setBrand("Eaton");
    setLookup(null);
    setLookupError("");
    setLookupBusy(false);
    setConfirmed(false);
    setError("");
  }
  async function findReplacement() {
    if (!serial.trim() || lookupBusy) return;
    lookupController.current?.abort();
    const pending = new AbortController();
    lookupController.current = pending;
    const current = ++lookupGeneration.current;
    setLookupBusy(true);
    setLookup(null);
    setLookupError("");
    try {
      const result = await api<SerialLookupResult>("serial-lookup/", {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({ serial_number: serial.trim() }),
      });
      if (
        mounted.current &&
        !pending.signal.aborted &&
        current === lookupGeneration.current
      )
        setLookup(result);
    } catch (failure) {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        current === lookupGeneration.current
      )
        setLookupError(
          failure instanceof Error
            ? failure.message
            : "La recherche n’a pas abouti.",
        );
    } finally {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        current === lookupGeneration.current
      )
        setLookupBusy(false);
    }
  }
  function useProduct(product: SerialLookupProduct) {
    const shortName = product.catalogue_number?.trim();
    const proposal =
      shortName && !["NA", "N/A"].includes(shortName.toUpperCase())
        ? shortName
        : product.product_name;
    if (!proposal || Array.from(proposal).length > 120) {
      setLookupError(
        "Ce nom dépasse la limite de 120 caractères. Renseignez explicitement un modèle court sans troncature automatique.",
      );
      return;
    }
    setModel(proposal);
    setBrand("Eaton");
    setReplacementId(null);
    setConfirmed(false);
  }
  async function mutate(
    action: "prepare" | "validate" | "ready" | "billing" | "close" | "reset",
    payload: RecordData = {},
  ) {
    if (mutationPending.current || loading || isClient) return;
    mutationPending.current = true;
    const current = ++generation.current;
    loadController.current?.abort();
    const request = new AbortController();
    mutationController.current = request;
    setBusy(action);
    setError("");
    setNotice("");
    try {
      const response = await api<RecordData>(
        `requests/${record.id}/exchange/${action === "prepare" ? "" : `${action}/`}`,
        {
          method: action === "prepare" ? "PATCH" : "POST",
          signal: request.signal,
          body: JSON.stringify(payload),
        },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        current !== generation.current
      )
        return;
      setRecord(response);
      setFormOpen(false);
      setConfirmed(false);
      setResetOpen(false);
      setResetReason("");
      setNotice(
        action === "validate" && payload.mark_ready === true
          ? "Échange validé et prêt à être livré. La facturation reste à confirmer."
          : {
              prepare:
                "Préparation enregistrée. Le remplacement reste à valider.",
              validate:
                "Échange validé. Vous pouvez maintenant préparer sa livraison.",
              ready:
                "Le dossier est prêt à être livré. La facturation reste à confirmer.",
              billing:
                "Facturation confirmée. Le dossier peut être clôturé séparément.",
              close: "Dossier clôturé.",
              reset:
                "La préparation est rouverte. Une nouvelle validation technique sera nécessaire.",
            }[action],
      );
      try {
        await onChanged(response);
      } catch {
        if (mounted.current && current === generation.current)
          setError(
            "L’action est enregistrée. L’actualisation des listes a échoué ; rechargez la page pour les actualiser.",
          );
      }
    } catch (failure) {
      if (
        mounted.current &&
        !request.signal.aborted &&
        current === generation.current
      )
        setError(
          failure instanceof Error
            ? failure.message
            : "L’action n’a pas pu être confirmée.",
        );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        current === generation.current
      ) {
        setBusy("");
        mutationPending.current = false;
      }
    }
  }
  function savePreparation(event: FormEvent) {
    event.preventDefault();
    if (!serial.trim() || !model.trim()) return;
    void mutate("prepare", {
      replacement_serial_number: serial.trim(),
      replacement_model: model.trim(),
      replacement_brand: brand.trim(),
      ...(replacementId ? { replacement_equipment: replacementId } : {}),
    });
  }
  function saveBilling(event: FormEvent) {
    event.preventDefault();
    if (!invoiceReference.trim() || !invoicedOn) return;
    void mutate("billing", {
      invoice_reference: invoiceReference.trim(),
      invoiced_on: invoicedOn,
      billing_notes: billingNotes.trim(),
    });
  }
  if (loading && !exchange)
    return (
      <div className="loading-state">
        <LoaderCircle size={18} className="spin" />
        Chargement du suivi de l’échange…
      </div>
    );
  if (isClient && !approved)
    return (
      <section className="exchange-panel exchange-public-pending">
        <Info size={19} />
        <p>
          Le résumé du matériel de remplacement sera disponible après validation
          de l’échange.
        </p>
      </section>
    );
  return (
    <section
      className="exchange-panel"
      aria-label="Suivi du remplacement et de la facturation"
    >
      {loadError && (
        <ErrorMessage>
          {loadError}
          <button
            type="button"
            className="button secondary small"
            onClick={() => void refresh()}
          >
            Actualiser l’échange
          </button>
        </ErrorMessage>
      )}
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={18} />
          {notice}
        </div>
      )}
      <div className="exchange-panel-heading">
        <CallReference record={record} role={user.role} />
        <ExchangeBadge exchange={exchange} />
      </div>
      <div className="exchange-equipment-grid">
        <article>
          <span className="exchange-equipment-label">Onduleur d’origine</span>
          <strong className="serial-text">
            {text(record.equipment_serial || original?.serial_number)}
          </strong>
          <span>{text(record.equipment_model || original?.model)}</span>
          <small>{record.client_name || original?.client_name}</small>
        </article>
        <ArrowRight className="exchange-equipment-arrow" size={24} />
        <article>
          <span className="exchange-equipment-label">
            Matériel de remplacement
          </span>
          <strong className="serial-text">
            {!isClient || approved
              ? text(exchange?.replacement_serial_number)
              : "Remplacement en préparation"}
          </strong>
          <span>
            {!isClient || approved
              ? text(exchange?.replacement_model)
              : "Le matériel sera indiqué après validation."}
          </span>
          {(!isClient || approved) && (
            <small>{exchange?.replacement_brand}</small>
          )}
        </article>
      </div>
      <ol className="exchange-stage-list">
        <li className={approved ? "done" : ""}>
          <ShieldCheck size={17} />
          <div>
            <strong>Validation technique</strong>
            <span>
              {exchange?.validated_at
                ? date(exchange.validated_at, true)
                : "En attente"}
            </span>
            {!isClient && exchange?.validated_by_name && (
              <small>{exchange.validated_by_name}</small>
            )}
          </div>
        </li>
        <li className={exchange?.ready_at ? "done" : ""}>
          <Truck size={17} />
          <div>
            <strong>Prêt à être livré</strong>
            <span>
              {exchange?.ready_at
                ? date(exchange.ready_at, true)
                : "À confirmer après validation"}
            </span>
            {!isClient && exchange?.ready_by_name && (
              <small>{exchange.ready_by_name}</small>
            )}
          </div>
        </li>
        <li className={exchange?.billing_validated_at ? "done" : ""}>
          <FileText size={17} />
          <div>
            <strong>Facturation</strong>
            <span>
              {exchange?.billing_validated_at
                ? "Facturation confirmée"
                : "Facturation en attente"}
            </span>
            {exchange?.invoice_reference && (
              <small>
                Facture {exchange.invoice_reference} ·{" "}
                {date(exchange.invoiced_on)}
              </small>
            )}
            {!isClient && exchange?.billing_validated_by_name && (
              <small>{exchange.billing_validated_by_name}</small>
            )}
          </div>
        </li>
      </ol>
      {!exchange?.validated_at && !isClient && (
        <p className="exchange-advisory">
          <Info size={16} />
          Une ancienne fiche d’échange ou un état historique ne confirme pas le
          remplacement. Vérifiez le matériel et validez explicitement l’échange.
        </p>
      )}
      {!isClient && exchange?.can_prepare && !formOpen && (
        <button
          type="button"
          className="button primary"
          onClick={prepare}
          disabled={!!busy || loading}
        >
          <Pencil size={16} />
          {exchange.replacement_serial_number
            ? "Modifier la préparation"
            : "Préparer l’échange"}
        </button>
      )}
      {!isClient && exchange?.can_prepare && formOpen && (
        <form className="exchange-prepare-form" onSubmit={savePreparation}>
          <h3>Préparer le matériel de remplacement</h3>
          <p>
            La préparation conserve le numéro de série et le modèle proposés.
            L’équipement de remplacement est résolu ou créé lors de la
            validation.
          </p>
          <fieldset disabled={!!busy}>
            <div className="form-grid">
              <div className="form-field span-2">
                <label htmlFor={`${id}-serial`}>
                  Numéro de série du remplacement{" "}
                  <span aria-hidden="true" className="required">
                    *
                  </span>
                </label>
                <div className="exchange-serial-row">
                  <input
                    id={`${id}-serial`}
                    className="input"
                    maxLength={120}
                    required
                    value={serial}
                    onChange={(event) => changeSerial(event.target.value)}
                  />
                  <button
                    type="button"
                    className="button secondary"
                    disabled={!serial.trim() || lookupBusy}
                    onClick={() => void findReplacement()}
                  >
                    {lookupBusy ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <Search size={16} />
                    )}
                    Rechercher le matériel de remplacement
                  </button>
                </div>
              </div>
              <div className="form-field">
                <label htmlFor={`${id}-model`}>
                  Modèle du remplacement{" "}
                  <span aria-hidden="true" className="required">
                    *
                  </span>
                </label>
                <input
                  id={`${id}-model`}
                  className="input"
                  required
                  maxLength={120}
                  disabled={replacementId !== null}
                  value={model}
                  onChange={(event) => {
                    setModel(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </div>
              <div className="form-field">
                <label htmlFor={`${id}-brand`}>Marque du remplacement</label>
                <input
                  id={`${id}-brand`}
                  className="input"
                  maxLength={80}
                  disabled={replacementId !== null}
                  value={brand}
                  onChange={(event) => {
                    setBrand(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </div>
            </div>
            {lookupError && <ErrorMessage>{lookupError}</ErrorMessage>}
            {lookup && (
              <div
                className="exchange-lookup-results"
                aria-label="Résultat de recherche du remplacement"
              >
                {lookup.existing_equipment ? (
                  <>
                    <strong>Équipement déjà enregistré</strong>
                    <p>
                      {lookup.existing_equipment.serial_number} ·{" "}
                      {lookup.existing_equipment.model} ·{" "}
                      {lookup.existing_equipment.client_name}
                    </p>
                    {lookup.existing_equipment.id === record.equipment ? (
                      <p className="error-box">
                        Le remplacement doit être distinct de l’onduleur
                        d’origine.
                      </p>
                    ) : original &&
                      lookup.existing_equipment.client !== original.client ? (
                      <p className="error-box">
                        Cet équipement appartient à une autre société.
                        Choisissez le matériel du client de ce dossier.
                      </p>
                    ) : (
                      <button
                        type="button"
                        className="button secondary small"
                        onClick={() => {
                          const found = lookup.existing_equipment!;
                          setReplacementId(found.id);
                          setModel(found.model);
                          setBrand(found.brand);
                          setConfirmed(false);
                        }}
                      >
                        Utiliser cet équipement
                      </button>
                    )}
                  </>
                ) : lookup.product_candidates.length ? (
                  <>
                    <strong>
                      {lookup.product_candidates.length > 1
                        ? "Plusieurs modèles possibles : choisissez explicitement."
                        : "Modèle proposé par le catalogue"}
                    </strong>
                    {lookup.product_candidates.map((product) => (
                      <div className="exchange-product-choice" key={product.id}>
                        <div>
                          <strong>
                            {product.catalogue_number || product.product_name}
                          </strong>
                          <small>
                            {product.product_name} · {product.structure}
                          </small>
                        </div>
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={() => useProduct(product)}
                        >
                          Utiliser ce modèle
                        </button>
                      </div>
                    ))}
                  </>
                ) : (
                  <p>
                    Aucun modèle identifié. Vous pouvez renseigner explicitement
                    le modèle et la marque ci-dessus.
                  </p>
                )}
              </div>
            )}
            {replacementId !== null && (
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setReplacementId(null);
                  setLookup(null);
                }}
              >
                Revenir à une saisie manuelle
              </button>
            )}
            <div className="exchange-form-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => {
                  setFormOpen(false);
                  lookupController.current?.abort();
                  lookupGeneration.current += 1;
                }}
              >
                Annuler
              </button>
              <button
                type="submit"
                className="button primary"
                disabled={!serial.trim() || !model.trim() || !!busy}
              >
                {busy === "prepare" ? (
                  <LoaderCircle size={16} className="spin" />
                ) : (
                  <ClipboardCheck size={16} />
                )}
                Enregistrer la préparation
              </button>
            </div>
          </fieldset>
        </form>
      )}
      {!isClient && exchange?.can_validate && !formOpen && (
        <div className="exchange-validation">
          <label className="exchange-confirm-check">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!!busy}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              Je confirme le numéro de série et le modèle du matériel de
              remplacement.
            </span>
          </label>
          <button
            type="button"
            className="button primary"
            disabled={
              !confirmed ||
              !exchange.replacement_serial_number?.trim() ||
              !exchange.replacement_model?.trim() ||
              !!busy ||
              loading
            }
            onClick={() => void mutate("validate", { mark_ready: true })}
          >
            {busy === "validate" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Truck size={16} />
            )}
            Valider et mettre prêt à livrer
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={
              !confirmed ||
              !exchange.replacement_serial_number?.trim() ||
              !exchange.replacement_model?.trim() ||
              !!busy ||
              loading
            }
            onClick={() => void mutate("validate")}
          >
            {busy === "validate" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <ShieldCheck size={16} />
            )}
            Valider l’échange
          </button>
        </div>
      )}
      {!isClient && exchange?.can_mark_ready && (
        <div className="exchange-ready-action">
          <p>
            Le remplacement est validé. Confirmez séparément sa disponibilité
            pour la livraison.
          </p>
          <button
            type="button"
            className="button primary"
            disabled={!!busy || loading}
            onClick={() => void mutate("ready")}
          >
            {busy === "ready" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Truck size={16} />
            )}
            Prêt à être livré
          </button>
        </div>
      )}
      {!isClient && (billing || finance || exchange?.billing_validated_at) && (
        <section className="exchange-billing-section">
          <h3>Facturation de l’échange</h3>
          <p>
            Enregistrez la référence de la facture émise dans votre outil de
            facturation. Cette action confirme son enregistrement ; elle ne crée
            aucune facture dans un ERP et ne constate aucun paiement.
          </p>
          {exchange?.billing_validated_at ? (
            <dl className="request-dossier-facts">
              <div>
                <dt>Référence de facture</dt>
                <dd>{text(exchange.invoice_reference)}</dd>
              </div>
              <div>
                <dt>Date de facture</dt>
                <dd>{date(exchange.invoiced_on)}</dd>
              </div>
              <div>
                <dt>Confirmation</dt>
                <dd>{date(exchange.billing_validated_at, true)}</dd>
              </div>
              <div>
                <dt>Validée par</dt>
                <dd>{text(exchange.billing_validated_by_name)}</dd>
              </div>
              {exchange.billing_notes && (
                <div>
                  <dt>Notes internes de facturation</dt>
                  <dd>{exchange.billing_notes}</dd>
                </div>
              )}
            </dl>
          ) : exchange?.can_validate_billing && finance ? (
            <form onSubmit={saveBilling}>
              <fieldset disabled={!!busy}>
                <div className="form-grid">
                  <div className="form-field">
                    <label htmlFor={`${id}-invoice`}>
                      Référence de facture{" "}
                      <span className="required" aria-hidden="true">
                        *
                      </span>
                    </label>
                    <input
                      id={`${id}-invoice`}
                      className="input"
                      required
                      maxLength={120}
                      value={invoiceReference}
                      onChange={(event) =>
                        setInvoiceReference(event.target.value)
                      }
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor={`${id}-invoice-date`}>
                      Date de facture{" "}
                      <span className="required" aria-hidden="true">
                        *
                      </span>
                    </label>
                    <input
                      id={`${id}-invoice-date`}
                      className="input"
                      type="date"
                      required
                      value={invoicedOn}
                      onChange={(event) => setInvoicedOn(event.target.value)}
                    />
                  </div>
                  <div className="form-field span-2">
                    <label htmlFor={`${id}-invoice-notes`}>
                      Notes internes de facturation
                    </label>
                    <textarea
                      id={`${id}-invoice-notes`}
                      className="input"
                      maxLength={4000}
                      rows={3}
                      value={billingNotes}
                      onChange={(event) => setBillingNotes(event.target.value)}
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  className="button primary"
                  disabled={!invoiceReference.trim() || !invoicedOn || !!busy}
                >
                  {busy === "billing" ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <FileText size={16} />
                  )}
                  Confirmer la facturation
                </button>
              </fieldset>
            </form>
          ) : (
            <p className="exchange-billing-wait">
              {!approved || !exchange?.ready_at
                ? "La validation technique et la disponibilité pour livraison sont requises avant la confirmation de facturation."
                : "La confirmation est réservée à un compte autorisé à valider la facturation."}
            </p>
          )}
        </section>
      )}
      {!isClient && exchange?.can_close && (
        <div className="exchange-close-action">
          <p>La facturation est confirmée. Vous pouvez clôturer ce dossier.</p>
          <button
            type="button"
            className="button primary"
            disabled={!!busy || loading}
            onClick={() => void mutate("close")}
          >
            {busy === "close" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <CheckCircle2 size={16} />
            )}
            Clôturer le dossier
          </button>
        </div>
      )}
      {!isClient && exchange?.can_reset && !formOpen && (
        <div className="exchange-reset-action">
          <button
            type="button"
            className="text-button"
            disabled={!!busy}
            onClick={() => setResetOpen((open) => !open)}
          >
            <RefreshCw size={14} />
            Corriger la préparation validée
          </button>
          {resetOpen && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (resetReason.trim())
                  void mutate("reset", { reason: resetReason.trim() });
              }}
            >
              <p>
                La correction annule la validation technique et la disponibilité
                pour livraison. Le journal conserve les actions précédentes.
              </p>
              <div className="form-field">
                <label htmlFor={`${id}-reset`}>
                  Motif de réouverture de la préparation
                </label>
                <textarea
                  id={`${id}-reset`}
                  className="input"
                  required
                  maxLength={4000}
                  value={resetReason}
                  onChange={(event) => setResetReason(event.target.value)}
                />
              </div>
              <button
                type="submit"
                className="button secondary"
                disabled={!resetReason.trim() || !!busy}
              >
                Rouvrir la préparation
              </button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
