import { useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  FileText,
  History,
  Info,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  Wrench,
} from "lucide-react";
import { api, dateFR, type User, type RecordData } from "./api";
import { requestStatusLabels, statuses } from "./resources";

export type OperationEvent = {
  id: number;
  equipment: number | null;
  equipment_serial?: string | null;
  related_equipment?: number | null;
  related_equipment_serial?: string | null;
  service_request: number | null;
  request_reference?: string | null;
  intervention: number | null;
  intervention_reference?: string | null;
  kind: string;
  actor_name: string;
  created_at: string;
  recorded_created_at?: string | null;
  status_before: string | null;
  status_after: string | null;
  observation: string;
  summary: string;
  is_internal: boolean;
  source: string;
};

type ManualKind = "observation" | "summary" | "status_changed";
type TimelineFilter =
  | "all"
  | "observation"
  | "summary"
  | "status_changed"
  | "interventions"
  | "baseline";

const kindLabels: Record<string, string> = {
  baseline: "État repris",
  created: "Fiche créée",
  updated: "Fiche mise à jour",
  status_changed: "Changement d’état",
  intervention_created: "Intervention créée",
  intervention_updated: "Intervention mise à jour",
  contract_created: "Contrat créé",
  contract_updated: "Contrat mis à jour",
  warranty_created: "Garantie créée",
  warranty_updated: "Garantie mise à jour",
  delivery_created: "Bon de livraison créé",
  delivery_updated: "Bon de livraison mis à jour",
  part_used: "Pièce utilisée",
  attachment_added: "Pièce jointe ajoutée",
  attachment_deleted: "Pièce jointe supprimée",
  exchange_prepared: "Remplacement préparé",
  exchange_validated: "Échange validé",
  exchange_ready: "Échange prêt à être livré",
  exchange_invoiced: "Facturation de l’échange confirmée",
  exchange_billed: "Facturation de l’échange confirmée",
  exchange_billing_details: "Références de facturation enregistrées",
  exchange_closed: "Échange clôturé",
  exchange_reset: "Préparation de l’échange rouverte",
  exchange_reset_reason: "Motif de réouverture de la préparation",
  repair_tests_passed: "Tests de réparation réussis",
  diagnostic_nonrepairable: "Retour non réparable décidé",
  diagnostic_free_proposed: "Gratuité du diagnostic proposée",
  diagnostic_quote_prepared: "Devis de diagnostic préparé",
  diagnostic_quote_issued: "Devis de diagnostic émis",
  diagnostic_invoiced: "Facturation du diagnostic confirmée",
  diagnostic_free_approved: "Gratuité du diagnostic approuvée",
  diagnostic_closed: "Retour client clôturé",
  disposition_reset: "Décision technique rouverte",
  assignment_changed: "Affectation modifiée",
  assignment_accepted: "Prise en charge confirmée",
  assignment_override: "Prise en charge confirmée par l’administrateur",
  observation: "Observation",
  summary: "Synthèse",
};

const requestStatuses = Object.entries(requestStatusLabels);

const interventionStatusLabels: Record<string, string> = {
  scheduled: "Planifiée",
  in_progress: "En maintenance",
  testing: "En test",
  completed: "Terminée",
  cancelled: "Annulée",
};

function statusLabel(value: string | null, event: OperationEvent) {
  if (!value) return "Non renseigné";
  const isOtherResource = /^(contract|warranty|delivery)_/.test(event.kind);
  const isIntervention =
    event.kind.startsWith("intervention_") ||
    (event.kind === "baseline" && event.intervention !== null);
  const labels = isOtherResource
    ? statuses
    : isIntervention
      ? interventionStatusLabels
      : event.service_request !== null
        ? requestStatusLabels
        : statuses;
  return labels[value] || value;
}

function eventLabel(event: OperationEvent) {
  if (event.kind === "created")
    return event.service_request !== null ? "Demande créée" : "Équipement créé";
  if (event.kind === "updated")
    return event.service_request !== null
      ? "Dossier mis à jour"
      : "Équipement mis à jour";
  return kindLabels[event.kind] || "Opération";
}

function eventDate(value: string) {
  return value && !Number.isNaN(new Date(value).getTime())
    ? dateFR(value, true)
    : "Date non disponible";
}

function EventIcon({ kind }: { kind: string }) {
  if (kind === "observation") return <MessageSquare size={16} />;
  if (kind === "summary") return <FileText size={16} />;
  if (kind.startsWith("intervention_")) return <Wrench size={16} />;
  if (kind === "status_changed") return <RefreshCw size={16} />;
  if (kind === "baseline") return <History size={16} />;
  return <ClipboardList size={16} />;
}

function validId(value: number | undefined) {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** A scope change remounts the inner component, isolating drafts and pending requests. */
export default function OperationTimeline({
  equipmentId,
  requestId,
  user,
  canWrite,
  onChanged,
  onEventsLoaded,
  requestRecord,
  refreshKey,
  showComposer = true,
}: {
  equipmentId?: number;
  requestId?: number;
  user: User;
  canWrite?: boolean;
  onChanged?: () => Promise<void>;
  onEventsLoaded?: (events: OperationEvent[]) => void;
  requestRecord?: RecordData;
  refreshKey?: unknown;
  showComposer?: boolean;
}) {
  const canAdd =
    user.role !== "client" &&
    (canWrite ?? (user.role === "admin" || user.role === "manager"));
  const isRequest = validId(requestId);
  const scopeId = isRequest
    ? requestId
    : validId(equipmentId)
      ? equipmentId
      : null;
  if (scopeId === null)
    return (
      <section className="operation-timeline">
        <div className="operation-timeline-heading">
          <History size={19} />
          <h3>Historique des opérations</h3>
        </div>
        <p className="operation-timeline-empty">
          Sélectionnez un équipement ou un dossier SAV pour consulter ses
          opérations.
        </p>
      </section>
    );
  const scope = isRequest ? "requests" : "equipment";
  return (
    <ScopedOperationTimeline
      key={`${scope}:${scopeId}:${user.id}:${user.role}:${canAdd}`}
      endpoint={`${scope}/${scopeId}/timeline/`}
      isRequest={isRequest}
      user={user}
      canWrite={canAdd}
      onChanged={onChanged}
      onEventsLoaded={onEventsLoaded}
      requestRecord={requestRecord}
      refreshKey={refreshKey}
      showComposer={showComposer}
    />
  );
}

function ScopedOperationTimeline({
  endpoint,
  isRequest,
  user,
  canWrite,
  onChanged,
  onEventsLoaded,
  requestRecord,
  refreshKey,
  showComposer,
}: {
  endpoint: string;
  isRequest: boolean;
  user: User;
  canWrite: boolean;
  onChanged?: () => Promise<void>;
  onEventsLoaded?: (events: OperationEvent[]) => void;
  requestRecord?: RecordData;
  refreshKey?: unknown;
  showComposer: boolean;
}) {
  const id = useId();
  const isClient = user.role === "client";
  const [events, setEvents] = useState<OperationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const [order, setOrder] = useState<"oldest" | "newest">("newest");
  const [composerOpen, setComposerOpen] = useState(false);
  const [draftBase, setDraftBase] = useState<{
    status: string;
    revision: number;
  } | null>(null);
  const draftIsStale = Boolean(
    isRequest &&
      draftBase &&
      requestRecord &&
      (draftBase.status !== requestRecord.status ||
        draftBase.revision !== (requestRecord.assignment?.revision ?? 0)),
  );
  const [kind, setKind] = useState<ManualKind>("observation");
  const [note, setNote] = useState("");
  const [targetStatus, setTargetStatus] = useState("");
  const [isInternal, setIsInternal] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const loadGeneration = useRef(0);
  const saveGeneration = useRef(0);
  const loadController = useRef<AbortController | null>(null);
  const saveController = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const eventsLoadedCallback = useRef(onEventsLoaded);
  eventsLoadedCallback.current = onEventsLoaded;

  async function load() {
    loadController.current?.abort();
    const request = new AbortController();
    loadController.current = request;
    const generation = ++loadGeneration.current;
    setLoading(true);
    setLoadError("");
    try {
      const data = await api<OperationEvent[]>(endpoint, {
        signal: request.signal,
      });
      if (
        !mounted.current ||
        request.signal.aborted ||
        loadGeneration.current !== generation
      )
        return;
      if (!Array.isArray(data))
        throw new Error(
          "Le serveur n’a pas renvoyé un historique exploitable.",
        );
      const visibleData = isClient
        ? data.filter((event) => event.is_internal === false)
        : data;
      setEvents(visibleData);
      setLoaded(true);
      try {
        eventsLoadedCallback.current?.(visibleData);
      } catch {
        setNotice(
          "L’historique est chargé. La synthèse de la fiche n’a pas pu être actualisée.",
        );
      }
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        loadGeneration.current !== generation
      )
        return;
      setLoadError(
        err instanceof Error
          ? err.message
          : "Impossible de charger l’historique des opérations.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        loadGeneration.current === generation
      )
        setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      loadGeneration.current += 1;
      saveGeneration.current += 1;
      loadController.current?.abort();
      saveController.current?.abort();
    };
  }, [endpoint]);
  useEffect(() => {
    if (loaded) void load();
  }, [refreshKey]);

  async function save() {
    if (!canWrite || isClient || submitting.current || loading) return;
    if (draftIsStale) {
      setSaveError(
        "Le dossier ou son affectation a changé. Actualisez la base du suivi avant d’enregistrer.",
      );
      return;
    }
    const value = note.trim();
    if (!value) {
      setSaveError(
        kind === "summary"
          ? "Saisissez une synthèse avant de l’enregistrer."
          : kind === "status_changed"
            ? "Une observation est obligatoire pour chaque changement d’état."
            : "Saisissez une observation avant de l’enregistrer.",
      );
      return;
    }
    if (value.length > 10000) {
      setSaveError("Le texte doit contenir au maximum 10 000 caractères.");
      return;
    }
    if (
      kind === "status_changed" &&
      (!isRequest ||
        !requestStatuses.some(([status]) => status === targetStatus))
    ) {
      setSaveError("Choisissez le nouvel état du dossier SAV.");
      return;
    }
    submitting.current = true;
    saveController.current?.abort();
    const request = new AbortController();
    saveController.current = request;
    const generation = ++saveGeneration.current;
    const payload: {
      kind: ManualKind;
      is_internal: boolean;
      observation?: string;
      summary?: string;
      status_after?: string;
      expected_status?: string;
      assignment_revision?: number;
    } = { kind, is_internal: isInternal };
    if (isRequest && requestRecord) {
      payload.expected_status = draftBase?.status ?? requestRecord.status;
      payload.assignment_revision =
        draftBase?.revision ?? requestRecord.assignment?.revision ?? 0;
    }
    if (kind === "summary") payload.summary = value;
    else if (value) payload.observation = value;
    if (kind === "status_changed") payload.status_after = targetStatus;
    setSaving(true);
    setSaveError("");
    setNotice("");
    try {
      await api<OperationEvent>(endpoint, {
        method: "POST",
        signal: request.signal,
        body: JSON.stringify(payload),
      });
      if (
        !mounted.current ||
        request.signal.aborted ||
        saveGeneration.current !== generation
      )
        return;
      setNote("");
      setTargetStatus("");
      setDraftBase(null);
      setComposerOpen(false);
      setIsInternal(true);
      setNotice(
        kind === "status_changed"
          ? "Le nouvel état du dossier a été enregistré."
          : kind === "summary"
            ? "La synthèse a été enregistrée."
            : "L’observation a été enregistrée.",
      );
      await load();
      if (
        !mounted.current ||
        request.signal.aborted ||
        saveGeneration.current !== generation
      )
        return;
      try {
        await onChanged?.();
      } catch {
        if (mounted.current && saveGeneration.current === generation)
          setNotice(
            "L’opération a été enregistrée. Actualisez la fiche pour recharger ses autres informations.",
          );
      }
    } catch (err) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        saveGeneration.current !== generation
      )
        return;
      setSaveError(
        err instanceof TypeError
          ? "Le serveur n’a pas confirmé l’enregistrement. Actualisez l’historique avant de renouveler l’envoi."
          : err instanceof Error
            ? err.message
            : "L’opération n’a pas pu être confirmée.",
      );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        saveGeneration.current === generation
      ) {
        submitting.current = false;
        setSaving(false);
      }
    }
  }

  const allowedEvents = isClient
    ? events.filter((event) => event.is_internal === false)
    : events;
  const visibleEvents = allowedEvents
    .filter((event) => {
      if (filter === "all") return true;
      if (filter === "interventions")
        return event.kind.startsWith("intervention_");
      if (filter === "baseline")
        return event.kind === "baseline" || event.source === "baseline";
      return event.kind === filter;
    })
    .sort((first, second) => {
      const dateDifference =
        (Date.parse(first.created_at) || 0) -
        (Date.parse(second.created_at) || 0);
      const difference = dateDifference || first.id - second.id;
      return order === "oldest" ? difference : -difference;
    });
  const noteLabel =
    kind === "summary"
      ? "Synthèse"
      : kind === "status_changed"
        ? "Observation"
        : "Observation";

  return (
    <section
      className="operation-timeline"
      aria-label="Historique des opérations"
    >
      <div className="operation-timeline-header">
        <div className="operation-timeline-heading">
          <History size={19} />
          <div>
            <h3>Historique des opérations</h3>
            <p>
              {isRequest
                ? "Suivi chronologique du dossier SAV."
                : "Suivi des dossiers et interventions de cet équipement."}
            </p>
          </div>
        </div>
        <div className="operation-timeline-actions">
          <button
            type="button"
            className="button secondary small"
            onClick={() => void load()}
            disabled={loading || saving}
            aria-label="Actualiser l’historique des opérations"
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} />
            Actualiser
          </button>
          {canWrite && showComposer && !isClient && (
            <button
              type="button"
              className="button primary small"
              aria-expanded={composerOpen}
              aria-controls={`${id}-composer`}
              disabled={saving}
              onClick={() => {
                if (!composerOpen && !draftBase && isRequest && requestRecord)
                  setDraftBase({
                    status: requestRecord.status,
                    revision: requestRecord.assignment?.revision ?? 0,
                  });
                setComposerOpen((value) => !value);
              }}
            >
              <Plus size={15} />
              Ajouter une opération
            </button>
          )}
        </div>
      </div>

      {isClient && (
        <p className="operation-timeline-notice">
          <Info size={15} />
          Les opérations partagées par votre équipe SAV sont consultables ici.
        </p>
      )}
      {!isClient && !canWrite && (
        <p className="operation-timeline-notice">
          <LockKeyhole size={15} />
          Historique en lecture seule. Les ajouts nécessitent l’affectation
          courante et la confirmation de la prise en charge.
        </p>
      )}
      {notice && (
        <p className="operation-timeline-success" role="status">
          <CheckCircle2 size={16} />
          {notice}
        </p>
      )}

      {canWrite && showComposer && !isClient && composerOpen && (
        <div
          id={`${id}-composer`}
          role="group"
          aria-labelledby={`${id}-composer-title`}
          className="operation-timeline-composer"
        >
          <h4 id={`${id}-composer-title`}>Nouvelle opération</h4>
          <div className="operation-timeline-fields">
            <label className="operation-timeline-field" htmlFor={`${id}-kind`}>
              <span>Type d’opération</span>
              <select
                id={`${id}-kind`}
                className="input"
                value={kind}
                disabled={saving}
                onChange={(event) => {
                  setKind(event.target.value as ManualKind);
                  setSaveError("");
                }}
              >
                <option value="observation">Ajouter une observation</option>
                <option value="summary">Ajouter une synthèse</option>
                {isRequest && (
                  <option value="status_changed">
                    Changer l’état du dossier
                  </option>
                )}
              </select>
            </label>
            {kind === "status_changed" && (
              <label
                className="operation-timeline-field"
                htmlFor={`${id}-status`}
              >
                <span>Nouvel état du dossier</span>
                <select
                  id={`${id}-status`}
                  className="input"
                  value={targetStatus}
                  disabled={saving}
                  onChange={(event) => {
                    setTargetStatus(event.target.value);
                    setSaveError("");
                  }}
                >
                  <option value="">Choisir un état…</option>
                  {requestStatuses.map(([value, label]) => (
                    <option
                      key={value}
                      value={value}
                      disabled={
                        value !== requestRecord?.status &&
                        (["ready_for_delivery", "return_to_client"].includes(
                          value,
                        ) ||
                          (value === "new" &&
                            Boolean(requestRecord?.assigned_technician)))
                      }
                    >
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="operation-timeline-field operation-timeline-field-wide">
              <label htmlFor={`${id}-note`}>{noteLabel}</label>
              <textarea
                id={`${id}-note`}
                className="input"
                value={note}
                rows={4}
                maxLength={10000}
                disabled={saving}
                aria-describedby={`${id}-note-length`}
                onChange={(event) => {
                  setNote(event.target.value);
                  setSaveError("");
                }}
                placeholder={
                  kind === "summary"
                    ? "Résumez les constats, travaux et suites à donner…"
                    : "Décrivez les faits et informations utiles au suivi…"
                }
              />
              <small id={`${id}-note-length`}>
                {note.length.toLocaleString("fr-FR")} / 10 000 caractères
              </small>
            </div>
          </div>
          <label
            className="operation-timeline-internal"
            htmlFor={`${id}-internal`}
          >
            <input
              id={`${id}-internal`}
              type="checkbox"
              checked={isInternal}
              disabled={saving}
              onChange={(event) => setIsInternal(event.target.checked)}
            />
            <LockKeyhole size={14} />
            {kind === "status_changed"
              ? "Conserver la note d’accompagnement en interne"
              : "Note interne — masquée au client"}
          </label>
          <p className="operation-timeline-notice">
            <Info size={14} />
            {kind === "status_changed"
              ? "Le changement d’état est visible au client. La note d’accompagnement reste privée si l’option interne est cochée."
              : isInternal
                ? "Cette note sera réservée à l’équipe interne."
                : "Cette note sera visible dans le portail du client concerné."}
          </p>
          {user.role === "technician" && (
            <p className="operation-timeline-notice">
              Les ajouts et changements d’état sont réservés au technicien
              actuellement affecté, après confirmation de sa prise en charge.
            </p>
          )}
          {!isRequest && (
            <p className="operation-timeline-notice">
              Pour changer l’état d’un dossier SAV, ouvrez ce dossier.
            </p>
          )}
          {draftIsStale && (
            <div className="sav-followup-warning" role="status">
              <p>
                L’état ou l’affectation a changé pendant votre saisie. Le texte
                est conservé ; relisez-le avant de poursuivre.
              </p>
              <button
                type="button"
                className="button secondary small"
                disabled={saving}
                onClick={() => {
                  if (requestRecord)
                    setDraftBase({
                      status: requestRecord.status,
                      revision: requestRecord.assignment?.revision ?? 0,
                    });
                  setSaveError("");
                }}
              >
                Utiliser l’état actuel
              </button>
            </div>
          )}
          {saveError && (
            <div className="operation-timeline-error" role="alert">
              <AlertCircle size={16} />
              <span>{saveError}</span>
            </div>
          )}
          <div className="operation-timeline-actions">
            <button
              type="button"
              className="button primary small"
              disabled={
                saving || loading || !loaded || !!loadError || draftIsStale
              }
              onClick={() => void save()}
            >
              {saving ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <Send size={15} />
              )}
              {saving ? "Enregistrement…" : "Enregistrer l’opération"}
            </button>
            <button
              type="button"
              className="button secondary small"
              disabled={saving}
              onClick={() => setComposerOpen(false)}
            >
              Fermer
            </button>
          </div>
        </div>
      )}

      <div className="operation-timeline-controls">
        <label className="operation-timeline-filter" htmlFor={`${id}-filter`}>
          <span>Afficher</span>
          <select
            id={`${id}-filter`}
            className="input"
            value={filter}
            onChange={(event) =>
              setFilter(event.target.value as TimelineFilter)
            }
          >
            <option value="all">Toutes les opérations</option>
            <option value="observation">Observations</option>
            <option value="summary">Synthèses</option>
            <option value="status_changed">Changements d’état</option>
            <option value="interventions">Interventions</option>
            <option value="baseline">États repris</option>
          </select>
        </label>
        <label className="operation-timeline-filter" htmlFor={`${id}-order`}>
          <span>Ordre</span>
          <select
            id={`${id}-order`}
            className="input"
            value={order}
            onChange={(event) =>
              setOrder(event.target.value as "oldest" | "newest")
            }
          >
            <option value="oldest">Chronologique</option>
            <option value="newest">Plus récent d’abord</option>
          </select>
        </label>
        {loaded && (
          <span className="operation-timeline-count">
            {visibleEvents.length} / {allowedEvents.length} opération
            {allowedEvents.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {loading && (
        <p className="operation-timeline-status" role="status">
          <LoaderCircle size={16} className="spin" />
          Chargement de l’historique…
        </p>
      )}
      {loadError && (
        <div className="operation-timeline-error" role="alert">
          <AlertCircle size={16} />
          <div>
            <p>{loadError}</p>
            <button
              type="button"
              className="button secondary small"
              disabled={loading || saving}
              onClick={() => void load()}
            >
              Réessayer
            </button>
          </div>
        </div>
      )}
      {!loading && loaded && !visibleEvents.length && (
        <p className="operation-timeline-empty" role="status">
          {allowedEvents.length
            ? "Aucune opération ne correspond à ce filtre."
            : "Aucune opération n’est enregistrée dans cet historique."}
        </p>
      )}
      <ol className="operation-timeline-list" aria-busy={loading}>
        {visibleEvents.map((event) => (
          <li
            key={event.id}
            className={`operation-timeline-item kind-${event.kind}`}
          >
            <div className="operation-timeline-icon" aria-hidden="true">
              <EventIcon kind={event.kind} />
            </div>
            <article className="operation-timeline-event">
              <div className="operation-timeline-event-header">
                <strong>{eventLabel(event)}</strong>
                {!isClient && (
                  <span
                    className={`badge ${event.is_internal ? "amber" : "blue"}`}
                  >
                    {event.is_internal ? "Interne" : "Visible au client"}
                  </span>
                )}
              </div>
              <div className="operation-timeline-meta">
                <span>
                  {isClient ? "Équipe SAV" : event.actor_name || "Équipe SAV"}
                </span>
                <time dateTime={event.created_at}>
                  {event.source === "baseline" || event.kind === "baseline"
                    ? "Historique activé le "
                    : ""}
                  {eventDate(event.created_at)}
                </time>
                {!isRequest && event.service_request !== null && (
                  <span>
                    {event.request_reference
                      ? `N° d’appel TVM ${event.request_reference}`
                      : `Dossier SAV n° ${event.service_request}`}
                  </span>
                )}
                {event.intervention !== null && (
                  <span>
                    {event.intervention_reference
                      ? `Référence de visite ${event.intervention_reference}`
                      : `Visite n° ${event.intervention}`}
                  </span>
                )}
              </div>
              {!!(event.status_before || event.status_after) && (
                <div className="operation-timeline-transition">
                  {event.status_before && (
                    <>
                      <span>{statusLabel(event.status_before, event)}</span>
                      <ArrowRight size={13} aria-hidden="true" />
                    </>
                  )}
                  <strong>{statusLabel(event.status_after, event)}</strong>
                </div>
              )}
              {event.observation && (
                <p className="operation-timeline-body">{event.observation}</p>
              )}
              {event.summary && (
                <div className="operation-timeline-summary">
                  <span>Synthèse</span>
                  <p className="operation-timeline-body">{event.summary}</p>
                </div>
              )}
              {(event.source === "baseline" || event.kind === "baseline") && (
                <p className="operation-timeline-notice">
                  <Info size={13} />
                  État repris lors de la mise en place du suivi. Les opérations
                  antérieures n’ont pas été reconstituées.
                </p>
              )}
              {(event.source === "baseline" || event.kind === "baseline") &&
                event.recorded_created_at && (
                  <p className="operation-timeline-notice">
                    <CalendarDays size={13} />
                    <span>
                      Date de création enregistrée :{" "}
                      <time dateTime={event.recorded_created_at}>
                        {eventDate(event.recorded_created_at)}
                      </time>
                      . Cette date ne correspond pas à une transition d’état.
                    </span>
                  </p>
                )}
            </article>
          </li>
        ))}
      </ol>
    </section>
  );
}
