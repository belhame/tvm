import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  ShieldCheck,
  UserCheck,
  UserRound,
  X,
} from "lucide-react";
import { api, dateFR, type RecordData, type User } from "./api";
import { callIdentity } from "./CallReference";
import "./RequestAssignment.css";

export type RequestAssignmentState = {
  revision: number;
  technician: number | null;
  technician_name: string;
  assigned_at: string | null;
  accepted: boolean;
  accepted_at: string | null;
  accepted_by: number | null;
  accepted_by_name: string;
  can_confirm: boolean;
  can_claim: boolean;
  can_takeover: boolean;
  can_write_followup: boolean;
};

function positiveId(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : null;
}

/** Legacy assignment is visible, but never treated as accepted without server confirmation. */
export function assignmentOf(record: RecordData): RequestAssignmentState {
  const value =
    record.assignment && typeof record.assignment === "object"
      ? record.assignment
      : {};
  const technician = positiveId(
    Object.prototype.hasOwnProperty.call(value, "technician")
      ? value.technician
      : record.assigned_technician,
  );
  return {
    revision:
      typeof value.revision === "number" &&
      Number.isSafeInteger(value.revision) &&
      value.revision >= 0
        ? value.revision
        : 0,
    technician,
    technician_name:
      typeof value.technician_name === "string"
        ? value.technician_name
        : typeof record.assigned_technician_name === "string"
          ? record.assigned_technician_name
          : "",
    assigned_at:
      typeof value.assigned_at === "string" ? value.assigned_at : null,
    accepted: technician !== null && value.accepted === true,
    accepted_at:
      typeof value.accepted_at === "string" ? value.accepted_at : null,
    accepted_by: positiveId(value.accepted_by),
    accepted_by_name:
      typeof value.accepted_by_name === "string" ? value.accepted_by_name : "",
    can_confirm: value.can_confirm === true,
    can_claim: value.can_claim === true,
    can_takeover: value.can_takeover === true,
    can_write_followup: value.can_write_followup === true,
  };
}

export function assignmentFingerprint(record: RecordData) {
  const assignment = assignmentOf(record);
  return JSON.stringify([
    record.id,
    assignment.revision,
    assignment.technician,
    assignment.accepted,
    assignment.accepted_at,
    assignment.can_confirm,
    assignment.can_claim,
    assignment.can_takeover,
    assignment.can_write_followup,
    record.status === "closed",
  ]);
}

function technicianLabel(record: RecordData): string {
  return (
    [record.first_name, record.last_name].filter(Boolean).join(" ").trim() ||
    record.name ||
    record.username ||
    `Compte ${record.id}`
  );
}

type AssignmentAction =
  | "assignment"
  | "confirm"
  | "proxy"
  | "claim"
  | "takeover";
type Panel = AssignmentAction | null;

export default function RequestAssignment({
  record,
  user,
  technicians,
  onChanged,
  compact = false,
}: {
  record: RecordData;
  user: User;
  technicians: RecordData[];
  onChanged: (record: RecordData) => Promise<void> | void;
  compact?: boolean;
}) {
  const prefix = useId();
  const [current, setCurrent] = useState(record);
  const [panel, setPanel] = useState<Panel>(null);
  const [technician, setTechnician] = useState(
    String(assignmentOf(record).technician || ""),
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const recordScope = useRef(record.id);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;
  const fingerprint = assignmentFingerprint(record);
  const assignment = assignmentOf(current);
  const isManager = user.role === "admin" || user.role === "manager";
  const isInternal = ["admin", "manager", "technician"].includes(user.role);
  const canConfirm =
    isInternal && assignment.can_confirm && !assignment.accepted;
  const canClaim =
    user.role === "technician" &&
    assignment.can_claim &&
    assignment.technician === null &&
    current.status !== "closed" &&
    record.status !== "closed";
  const canTakeover =
    user.role === "technician" &&
    assignment.can_takeover &&
    assignment.technician !== null &&
    assignment.technician !== user.id &&
    current.status !== "closed" &&
    record.status !== "closed";
  const actorName = technicianLabel(user);
  const canProxy =
    user.role === "admin" &&
    assignment.technician !== null &&
    assignment.technician !== user.id &&
    !assignment.accepted;
  const reference = callIdentity(current).tvm || "non renseigné";
  const options = technicians.filter(
    (person) =>
      person.is_active !== false &&
      ["technician", "manager", "admin"].includes(person.role),
  );

  useEffect(() => {
    generation.current += 1;
    controller.current?.abort();
    submitting.current = false;
    setBusy(false);
    setCurrent(record);
    setTechnician(String(assignmentOf(record).technician || ""));
    setPanel(null);
    setReason("");
    if (recordScope.current !== record.id) {
      setError("");
      setNotice("");
      recordScope.current = record.id;
    }
  }, [fingerprint]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      controller.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!panel) return;
    panelRef.current
      ?.querySelector<HTMLElement>("select,textarea,button")
      ?.focus();
  }, [panel]);

  useEffect(() => {
    if (notice) summaryRef.current?.focus();
  }, [notice]);

  function restoreFocus() {
    if (triggerRef.current?.isConnected) triggerRef.current.focus();
    else summaryRef.current?.focus();
  }

  function closePanel() {
    if (busy) return;
    setPanel(null);
    setReason("");
    setError("");
    restoreFocus();
  }

  function openPanel(value: Panel, trigger: HTMLButtonElement) {
    if (busy) return;
    triggerRef.current = trigger;
    setTechnician(String(assignment.technician || ""));
    setReason("");
    setError("");
    setNotice("");
    setPanel(value);
  }

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && panel) {
      event.stopPropagation();
      event.preventDefault();
      closePanel();
    } else if (event.key === "Enter" || event.key === " ") {
      event.stopPropagation();
    }
  }

  async function mutate(mode: AssignmentAction) {
    if (submitting.current || !isInternal) return;
    if (mode === "assignment" && !isManager) return;
    if (mode === "confirm" && !canConfirm) return;
    if (mode === "claim" && !canClaim) return;
    if (mode === "takeover" && !canTakeover) return;
    if (
      mode === "takeover" &&
      (!reason.trim() || reason.trim().length > 2000)
    ) {
      setError(
        "Indiquez le motif de la prise de relais, en 2 000 caractères maximum.",
      );
      return;
    }
    if (
      mode === "proxy" &&
      (!canProxy || !reason.trim() || reason.trim().length > 2000)
    ) {
      setError("Indiquez le motif de cette confirmation au nom du technicien.");
      return;
    }
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    const stamp = ++generation.current;
    const live = () =>
      mounted.current &&
      !request.signal.aborted &&
      generation.current === stamp;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const endpoint = `requests/${current.id}/assignment/${mode === "assignment" ? "" : mode === "claim" ? "claim/" : mode === "takeover" ? "takeover/" : "confirm/"}`;
    const body =
      mode === "assignment"
        ? {
            technician: technician ? Number(technician) : null,
            expected_revision: assignment.revision,
          }
        : mode === "claim"
          ? { expected_revision: assignment.revision }
          : mode === "takeover"
            ? { expected_revision: assignment.revision, reason: reason.trim() }
            : {
                expected_revision: assignment.revision,
                accept: true,
                ...(mode === "proxy"
                  ? { on_behalf: true, reason: reason.trim() }
                  : {}),
              };
    let updated: RecordData;
    try {
      updated = await api<RecordData>(endpoint, {
        method: "POST",
        body: JSON.stringify(body),
        signal: request.signal,
      });
    } catch (failure) {
      if (!live()) return;
      const message =
        failure instanceof Error
          ? failure.message
          : "La modification de l’affectation n’a pas abouti.";
      setError(message);
      // A stale revision must refresh the real assignment. Other failures also
      // receive a safe read-only refresh, without repeating the mutation.
      try {
        const fresh = await api<RecordData>(`requests/${current.id}/`, {
          signal: request.signal,
        });
        if (live()) {
          setCurrent(fresh);
          setTechnician(String(assignmentOf(fresh).technician || ""));
          setPanel(null);
          setReason("");
          await onChangedRef.current(fresh);
        }
      } catch {
        if (live())
          setError(
            `${message} Rechargez le dossier pour vérifier l’affectation actuelle.`,
          );
      } finally {
        if (live()) {
          submitting.current = false;
          setBusy(false);
        }
      }
      return;
    }
    if (!live()) return;
    setCurrent(updated);
    setTechnician(String(assignmentOf(updated).technician || ""));
    setPanel(null);
    setReason("");
    setNotice(
      mode === "assignment"
        ? assignmentOf(updated).technician === null
          ? "La demande est désaffectée."
          : "Affectation enregistrée. La prise en charge doit être confirmée."
        : mode === "claim"
          ? "La demande vous est affectée et votre prise en charge est confirmée."
          : mode === "takeover"
            ? "Vous avez pris le relais. Votre prise en charge est confirmée."
            : "La prise en charge de la demande est confirmée.",
    );
    try {
      await onChangedRef.current(updated);
    } catch {
      if (live())
        setError(
          "La modification est enregistrée. La vue n’a pas pu être actualisée ; rechargez le dossier.",
        );
    } finally {
      if (live()) {
        submitting.current = false;
        setBusy(false);
        restoreFocus();
      }
    }
  }

  if (user.role === "client" || user.role === "courier")
    return (
      <div className="request-assignment-public">
        <span>
          {record.assigned_technician_name || "Technicien non précisé"}
        </span>
      </div>
    );

  return (
    <div
      className={`request-assignment${compact ? " request-assignment-compact" : ""}`}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleKey}
    >
      <div
        ref={summaryRef}
        tabIndex={-1}
        className="request-assignment-summary"
        role="group"
        aria-label={`Affectation actuelle de la demande ${reference}`}
      >
        <span
          className={`request-assignment-badge ${assignment.technician === null ? "assignment-unassigned" : assignment.accepted ? "assignment-accepted" : "assignment-pending"}`}
        >
          {assignment.technician === null ? (
            <UserRound size={14} />
          ) : assignment.accepted ? (
            <CheckCircle2 size={14} />
          ) : (
            <Clock3 size={14} />
          )}
          {assignment.technician === null
            ? "Non affecté"
            : assignment.accepted
              ? "Prise en charge confirmée"
              : "À confirmer"}
        </span>
        {assignment.technician !== null && (
          <strong>{assignment.technician_name || "Technicien désigné"}</strong>
        )}
        {!compact && assignment.accepted_at && (
          <small>
            Confirmée le {dateFR(assignment.accepted_at, true)}
            {isInternal && assignment.accepted_by_name
              ? ` par ${assignment.accepted_by_name}`
              : ""}
          </small>
        )}
        {!compact && assignment.technician !== null && !assignment.accepted && (
          <small>
            Le technicien doit confirmer la prise en charge avant de modifier le
            suivi.
          </small>
        )}
      </div>
      {isInternal && (
        <div className="request-assignment-actions">
          {isManager && (
            <button
              type="button"
              className="button secondary small"
              onClick={(event) => openPanel("assignment", event.currentTarget)}
              disabled={busy}
              aria-expanded={panel === "assignment"}
              aria-controls={`${prefix}-panel`}
            >
              <UserRound size={14} />
              {compact ? "Affecter" : "Modifier l’affectation"}
            </button>
          )}
          {canClaim && (
            <button
              type="button"
              className="button primary small"
              onClick={(event) => openPanel("claim", event.currentTarget)}
              disabled={busy}
              aria-expanded={panel === "claim"}
              aria-controls={`${prefix}-panel`}
            >
              <UserCheck size={14} />
              Prendre en charge
            </button>
          )}
          {canTakeover && (
            <button
              type="button"
              className="button secondary small"
              onClick={(event) => openPanel("takeover", event.currentTarget)}
              disabled={busy}
              aria-expanded={panel === "takeover"}
              aria-controls={`${prefix}-panel`}
            >
              <UserRound size={14} />
              Prendre le relais
            </button>
          )}
          {canConfirm && (
            <button
              type="button"
              className="button primary small"
              onClick={(event) => openPanel("confirm", event.currentTarget)}
              disabled={busy}
              aria-expanded={panel === "confirm"}
              aria-controls={`${prefix}-panel`}
            >
              <UserCheck size={14} />
              Confirmer la prise en charge
            </button>
          )}
          {canProxy && !compact && (
            <button
              type="button"
              className="button secondary small"
              onClick={(event) => openPanel("proxy", event.currentTarget)}
              disabled={busy}
              aria-expanded={panel === "proxy"}
              aria-controls={`${prefix}-panel`}
            >
              <ShieldCheck size={14} />
              Confirmer au nom du technicien
            </button>
          )}
        </div>
      )}
      {panel && (
        <div
          ref={panelRef}
          id={`${prefix}-panel`}
          className="request-assignment-panel"
          role={panel === "assignment" ? "region" : "alertdialog"}
          aria-labelledby={`${prefix}-title`}
          aria-describedby={
            panel === "assignment" ? undefined : `${prefix}-question`
          }
        >
          <div className="request-assignment-panel-heading">
            <h3 id={`${prefix}-title`}>
              {panel === "assignment"
                ? "Affecter la demande"
                : panel === "proxy"
                  ? "Confirmation administrative"
                  : panel === "claim"
                    ? "Prendre en charge"
                    : panel === "takeover"
                      ? "Prendre le relais"
                      : "Confirmer la prise en charge"}
            </h3>
            <button
              type="button"
              className="icon-button"
              onClick={closePanel}
              aria-label="Fermer la confirmation d’affectation"
              disabled={busy}
            >
              <X size={16} />
            </button>
          </div>
          {panel === "assignment" ? (
            <>
              <label htmlFor={`${prefix}-technician`}>
                Technicien de la demande
              </label>
              <select
                id={`${prefix}-technician`}
                className="input"
                value={technician}
                onChange={(event) => setTechnician(event.target.value)}
                disabled={busy}
              >
                <option value="">Aucun technicien · désaffecter</option>
                {assignment.technician !== null &&
                  !options.some(
                    (person) => person.id === assignment.technician,
                  ) && (
                    <option value={assignment.technician} disabled>
                      {assignment.technician_name || "Technicien actuel"} ·
                      indisponible
                    </option>
                  )}
                {options.map((person) => (
                  <option key={person.id} value={person.id}>
                    {technicianLabel(person)}
                  </option>
                ))}
              </select>
              <p>
                Une nouvelle affectation remet la prise en charge à confirmer.
                Les anciens intervenants gardent un accès en lecture.
              </p>
              <div className="request-assignment-panel-actions">
                <button
                  type="button"
                  className="button secondary small"
                  onClick={closePanel}
                  disabled={busy}
                >
                  Annuler
                </button>
                <button
                  type="button"
                  className="button primary small"
                  onClick={() => void mutate("assignment")}
                  disabled={
                    busy || technician === String(assignment.technician || "")
                  }
                >
                  {busy && <LoaderCircle className="spin" size={14} />}
                  {technician ? "Affecter" : "Désaffecter"}
                </button>
              </div>
            </>
          ) : (
            <>
              <p id={`${prefix}-question`}>
                {panel === "claim"
                  ? "Voulez-vous prendre en charge la demande n° "
                  : panel === "takeover"
                    ? "Voulez-vous prendre le relais sur la demande n° "
                    : "Voulez-vous confirmer la prise en charge de la demande n° "}
                {reference} ?
              </p>
              {(panel === "claim" || panel === "takeover") && (
                <div className="request-assignment-handover">
                  <dl>
                    <div>
                      <dt>Technicien actuel</dt>
                      <dd>
                        {panel === "claim"
                          ? "Aucun technicien affecté"
                          : assignment.technician_name ||
                            "Technicien actuellement affecté"}
                      </dd>
                    </div>
                    <div>
                      <dt>Nouveau technicien</dt>
                      <dd>{actorName}</dd>
                    </div>
                  </dl>
                  <p>
                    Vous devenez le technicien responsable et votre prise en
                    charge est confirmée immédiatement.{" "}
                    {panel === "takeover"
                      ? "L’ancien technicien perd ses droits d’écriture sur ce dossier. "
                      : ""}
                    Les visites existantes et leurs auteurs sont conservés.
                  </p>
                </div>
              )}
              {panel === "takeover" && (
                <div className="request-assignment-proxy">
                  <label htmlFor={`${prefix}-takeover-reason`}>
                    Motif de la prise de relais
                  </label>
                  <textarea
                    id={`${prefix}-takeover-reason`}
                    className="input"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={2000}
                    required
                    rows={3}
                    disabled={busy}
                    aria-describedby={`${prefix}-takeover-help`}
                  />
                  <p id={`${prefix}-takeover-help`}>
                    Obligatoire. Ce motif est conservé dans l’historique interne
                    du dossier.
                  </p>
                </div>
              )}

              {panel === "proxy" && (
                <div className="request-assignment-proxy">
                  <p>
                    Vous confirmez au nom de{" "}
                    <strong>
                      {assignment.technician_name || "la personne désignée"}
                    </strong>
                    . Cette action et son motif sont conservés dans
                    l’historique.
                  </p>
                  <label htmlFor={`${prefix}-reason`}>
                    Motif de confirmation au nom du technicien
                  </label>
                  <textarea
                    id={`${prefix}-reason`}
                    className="input"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={2000}
                    required
                    rows={3}
                    disabled={busy}
                  />
                </div>
              )}
              <div className="request-assignment-panel-actions">
                <button
                  type="button"
                  className="button secondary small"
                  onClick={closePanel}
                  disabled={busy}
                >
                  Annuler
                </button>
                <button
                  type="button"
                  className="button primary small"
                  onClick={() => void mutate(panel)}
                  disabled={
                    busy ||
                    (["proxy", "takeover"].includes(panel) && !reason.trim())
                  }
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={14} />
                  ) : (
                    <CheckCircle2 size={14} />
                  )}
                  Oui
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {error && (
        <div className="request-assignment-error" role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="request-assignment-notice" role="status">
          <CheckCircle2 size={15} />
          <span>{notice}</span>
        </div>
      )}
    </div>
  );
}
