import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Info,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
} from "lucide-react";
import { api, dateFR, listResult, type User } from "./api";
import {
  isCurrentMissionAccepted,
  logisticsUuid,
  type OutboundJob,
} from "./logistics";
import "./CourierDeliveryNotes.css";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
export type DeliveryNote = {
  id: number;
  reference: string;
  status: "prepared" | "cancelled";
  client: { id: number; name: string };
  courier: { id: number; name: string };
  created_at: string;
  line_count: number;
  comment: string;
  pdf_url: string;
  pdf_sha256: string;
  can_cancel: boolean;
  lines: {
    job: number;
    service_request: number;
    call_number: string;
    client_reference: string;
    equipment: number;
    serial_number: string;
    brand: string;
    model: string;
    kind: "delivery" | "return";
    delivery_address?: string;
  }[];
};
type Props = {
  user: User;
  jobs: OutboundJob[];
  Dialog: ComponentType<DialogProps>;
  initialJobIds?: number[];
  refreshKey?: unknown;
};
const pdfUrl = (note: DeliveryNote) =>
  note.pdf_url?.startsWith("/api/logistics/delivery-notes/") &&
  !note.pdf_url.includes("\\") &&
  !note.pdf_url.includes("//")
    ? note.pdf_url
    : `/api/logistics/delivery-notes/${note.id}/pdf/`;
const jobSignature = (rows: OutboundJob[]) =>
  JSON.stringify(
    rows
      .map((row) => [
        row.id,
        row.assignment_revision,
        row.assigned_courier,
        row.client.id,
        row.equipment,
        row.serial_number,
        row.can_handoff,
        row.accepted,
        row.accepted_revision,
      ])
      .sort((a, b) => Number(a[0]) - Number(b[0])),
  );
export default function CourierDeliveryNotes({
  user,
  jobs,
  Dialog,
  initialJobIds = [],
  refreshKey,
}: Props) {
  const id = useId();
  const [notes, setNotes] = useState<DeliveryNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number[]>(initialJobIds);
  const [preview, setPreview] = useState<OutboundJob[] | null>(null);
  const [comment, setComment] = useState("");
  const [created, setCreated] = useState<DeliveryNote | null>(null);
  const [detail, setDetail] = useState<DeliveryNote | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const mounted = useRef(true);
  const read = useRef<AbortController | null>(null);
  const write = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const submitting = useRef(false);
  const key = useRef<{ signature: string; key: string } | null>(null);
  const refreshSeen = useRef(refreshKey);
  const allowed = user.role === "courier" && user.courier_kind !== "client";
  async function load() {
    if (!allowed) return;
    read.current?.abort();
    const request = new AbortController();
    read.current = request;
    const stamp = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const result = await api<DeliveryNote[]>("logistics/delivery-notes/", {
        signal: request.signal,
      });
      if (
        mounted.current &&
        !request.signal.aborted &&
        stamp === generation.current
      ) {
        const visible = listResult(result) as DeliveryNote[];
        setNotes(visible);
        setDetail((current) =>
          current
            ? visible.find((note) => note.id === current.id) || null
            : null,
        );
      }
    } catch (failure) {
      if (
        mounted.current &&
        !request.signal.aborted &&
        stamp === generation.current
      )
        setError((failure as Error).message);
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        stamp === generation.current
      )
        setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      generation.current += 1;
      read.current?.abort();
      write.current?.abort();
    };
  }, [user.id, allowed]);
  useEffect(() => {
    if (refreshSeen.current !== refreshKey) {
      refreshSeen.current = refreshKey;
      void load();
    }
  }, [refreshKey]);
  const initialSignature = JSON.stringify(initialJobIds);
  useEffect(() => {
    setSelected(initialJobIds);
    if (initialJobIds.length) {
      const rows = jobs.filter(
        (job) =>
          initialJobIds.includes(job.id) &&
          job.can_handoff &&
          isCurrentMissionAccepted(job) &&
          job.assigned_courier === user.id &&
          job.status === "assigned",
      );
      if (
        rows.length === initialJobIds.length &&
        new Set(rows.map((job) => job.client.id)).size === 1
      ) {
        setPreview(rows);
        setComment("");
        setCreated(null);
        setSaveError("");
        key.current = null;
      }
    }
  }, [initialSignature]);
  const eligible = jobs.filter(
    (job) =>
      job.assigned_courier === user.id &&
      job.status === "assigned" &&
      job.can_handoff &&
      isCurrentMissionAccepted(job),
  );
  const prepared = new Map<number, DeliveryNote>();
  notes
    .filter((note) => note.status === "prepared")
    .forEach((note) =>
      note.lines.forEach((line) => prepared.set(line.job, note)),
    );
  const chosen = eligible.filter((job) => selected.includes(job.id));
  const company = chosen[0]?.client.id;
  const currentPreview = preview
    ? jobs.filter((job) => preview.some((snapshot) => snapshot.id === job.id))
    : [];
  const stale = Boolean(
    preview &&
      (jobSignature(currentPreview) !== jobSignature(preview) ||
        currentPreview.some(
          (job) =>
            !eligible.some((item) => item.id === job.id) ||
            prepared.has(job.id),
        )),
  );
  function toggle(job: OutboundJob, checked: boolean) {
    if (checked && company && company !== job.client.id) {
      setError("Un bon de livraison doit contenir un seul client.");
      return;
    }
    setError("");
    setSelected((rows) =>
      checked
        ? [...new Set([...rows, job.id])]
        : rows.filter((value) => value !== job.id),
    );
  }
  function openPreview(rows: OutboundJob[]) {
    if (!rows.length || new Set(rows.map((job) => job.client.id)).size !== 1) {
      setError("Sélectionnez des missions acceptées d’un même client.");
      return;
    }
    setPreview(rows);
    setComment("");
    setCreated(null);
    setSaveError("");
    key.current = null;
  }
  async function create() {
    if (!preview || stale || saving || submitting.current || !allowed) return;
    const body = {
      job_ids: preview.map((job) => job.id).sort((a, b) => a - b),
      ...(comment.trim() ? { comment: comment.trim() } : {}),
    };
    const signature = JSON.stringify(body);
    if (!key.current || key.current.signature !== signature)
      key.current = { signature, key: logisticsUuid() };
    const request = new AbortController();
    write.current = request;
    submitting.current = true;
    setSaving(true);
    setSaveError("");
    try {
      const note = await api<DeliveryNote>("logistics/delivery-notes/", {
        method: "POST",
        body: JSON.stringify({ ...body, request_key: key.current.key }),
        signal: request.signal,
      });
      if (!mounted.current || request.signal.aborted) return;
      setCreated(note);
      setSelected([]);
      setNotes((rows) => [note, ...rows.filter((row) => row.id !== note.id)]);
    } catch (failure) {
      if (mounted.current && !request.signal.aborted) {
        setSaveError((failure as Error).message);
        await load();
      }
    } finally {
      submitting.current = false;
      if (mounted.current && !request.signal.aborted) setSaving(false);
    }
  }
  async function cancel() {
    if (
      !detail?.can_cancel ||
      !cancelReason.trim() ||
      saving ||
      submitting.current
    )
      return;
    const request = new AbortController();
    write.current = request;
    submitting.current = true;
    setSaving(true);
    setSaveError("");
    try {
      const note = await api<DeliveryNote>(
        `logistics/delivery-notes/${detail.id}/cancel/`,
        {
          method: "POST",
          body: JSON.stringify({ reason: cancelReason.trim() }),
          signal: request.signal,
        },
      );
      if (!mounted.current || request.signal.aborted) return;
      setDetail(null);
      setNotes((rows) => rows.filter((row) => row.id !== note.id));
      setNotice(
        "Le bon est annulé. Son PDF original reste archivé pour les responsables ; aucun transport ni dossier SAV n’a été clôturé.",
      );
      setCancelOpen(false);
      setCancelReason("");
    } catch (failure) {
      if (mounted.current && !request.signal.aborted)
        setSaveError((failure as Error).message);
    } finally {
      submitting.current = false;
      if (mounted.current && !request.signal.aborted) setSaving(false);
    }
  }
  if (!allowed) return null;
  function summary(note: DeliveryNote) {
    return (
      <>
        <div className="courier-bl-document">
          <FileText size={30} />
          <div>
            <h3>{note.reference}</h3>
            <p>
              {note.client.name} · {note.courier.name}
            </p>
            <span
              className={`courier-bl-state ${note.status === "cancelled" ? "bl-cancelled" : "bl-prepared"}`}
            >
              {note.status === "cancelled" ? "Annulé" : "Préparé"}
            </span>
          </div>
        </div>
        <NoteLines rows={note.lines} />
        <p className="courier-bl-info">
          <Info size={17} />
          Ce document ne confirme ni la remise au client ni la clôture du SAV.
          La remise physique reste une action distincte.
        </p>
        {note.comment && (
          <div className="courier-bl-comment">
            <h4>Commentaire figurant sur le PDF</h4>
            <p>{note.comment}</p>
          </div>
        )}
        <a
          className="button primary"
          href={pdfUrl(note)}
          target="_blank"
          rel="noreferrer"
        >
          <Download size={17} />
          Télécharger le BL PDF
        </a>
      </>
    );
  }
  return (
    <section className="courier-delivery-notes">
      <div className="courier-bl-heading">
        <div>
          <h2>Bons de livraison</h2>
          <p>
            Préparez un document individuel ou un lot de vos missions acceptées
            pour un même client.
          </p>
        </div>
        <button
          type="button"
          className="button secondary small"
          onClick={() => void load()}
          disabled={loading || saving}
        >
          <RefreshCw size={16} className={loading ? "spin" : ""} />
          Actualiser les BL
        </button>
      </div>
      <div className="courier-bl-info">
        <Info size={18} />
        Seules vos missions acceptées, encore à remettre, sont proposées. Une
        affectation administrative nécessite d’abord votre acceptation.
      </div>
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={17} />
          {notice}
        </div>
      )}
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={17} />
          {error}
        </div>
      )}
      <div className="card courier-bl-selection">
        <div className="courier-bl-selection-heading">
          <h3>Mes missions acceptées</h3>
          <button
            type="button"
            className="button primary"
            disabled={!chosen.length || chosen.length > 100 || loading}
            onClick={() => openPreview(chosen)}
          >
            <PackageCheck size={17} />
            Générer le BL du lot{chosen.length ? ` (${chosen.length})` : ""}
          </button>
        </div>
        {eligible.length ? (
          <div className="courier-bl-job-list">
            {eligible.map((job) => {
              const existing = prepared.get(job.id);
              return (
                <article key={job.id} className="courier-bl-job">
                  <label className="courier-bl-select">
                    <input
                      type="checkbox"
                      checked={selected.includes(job.id)}
                      onChange={(event) => toggle(job, event.target.checked)}
                      disabled={
                        Boolean(existing) ||
                        Boolean(company && company !== job.client.id)
                      }
                      aria-label={`Sélectionner ${job.call_number} · ${job.serial_number}`}
                    />
                    <div>
                      <strong>{job.client.name}</strong>
                      <span>
                        {job.serial_number} · {job.model}
                      </span>
                      <small>
                        N° TVM : {job.call_number}
                        {job.client_reference
                          ? ` · N° client : ${job.client_reference}`
                          : ""}
                      </small>
                    </div>
                  </label>
                  {existing ? (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => {
                        setDetail(existing);
                        setSaveError("");
                        setCancelOpen(false);
                      }}
                    >
                      Voir {existing.reference}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={loading}
                      onClick={() => openPreview([job])}
                    >
                      Préparer le BL
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="courier-empty-state">
            <PackageCheck size={28} />
            <h3>Aucune mission acceptée à préparer</h3>
            <p>
              Acceptez d’abord une livraison ou un retour qui vous est affecté.
            </p>
          </div>
        )}
      </div>
      <section className="card courier-bl-history">
        <h3>Historique de mes bons de livraison</h3>
        {loading && !notes.length ? (
          <div className="loading-state">
            <LoaderCircle className="spin" size={18} />
            Chargement des bons…
          </div>
        ) : notes.length ? (
          <div className="courier-bl-history-list">
            {notes.map((note) => (
              <article key={note.id}>
                <div>
                  <strong>{note.reference}</strong>
                  <p>
                    {note.client.name} · {note.line_count} ligne
                    {note.line_count > 1 ? "s" : ""}
                  </p>
                  <small>{dateFR(note.created_at, true)}</small>
                  <span
                    className={`courier-bl-state ${note.status === "cancelled" ? "bl-cancelled" : "bl-prepared"}`}
                  >
                    {note.status === "cancelled" ? "Annulé" : "Préparé"}
                  </span>
                </div>
                <button
                  className="button secondary small"
                  type="button"
                  onClick={() => {
                    setDetail(note);
                    setCancelOpen(false);
                    setSaveError("");
                  }}
                >
                  Consulter le BL
                </button>
                <a
                  href={pdfUrl(note)}
                  target="_blank"
                  rel="noreferrer"
                  className="button secondary small"
                >
                  <Download size={16} />
                  PDF
                </a>
              </article>
            ))}
          </div>
        ) : (
          <p className="courier-bl-empty">
            Aucun bon préparé. Les documents enregistrés apparaîtront ici.
          </p>
        )}
      </section>
      {preview && (
        <Dialog
          title={
            created
              ? "Bon de livraison préparé"
              : "Vérifier le bon de livraison"
          }
          subtitle={created?.reference || preview[0]?.client.name}
          onClose={() => {
            if (!saving) {
              setPreview(null);
              setCreated(null);
            }
          }}
          wide
        >
          <div className="courier-bl-modal">
            {created ? (
              <>
                <div className="success-box" role="status">
                  <CheckCircle2 size={18} />
                  Bon préparé sur le serveur. Aucune remise n’a été enregistrée.
                </div>
                {summary(created)}
              </>
            ) : (
              <>
                <h3>{preview[0]?.client.name}</h3>
                <p>
                  {preview.length} mission{preview.length > 1 ? "s" : ""} ·
                  livreur : {preview[0]?.assigned_courier_name}
                </p>
                <NoteLines
                  rows={preview.map((job) => ({ ...job, job: job.id }))}
                />
                <div className="field">
                  <label htmlFor={`${id}-comment`}>
                    Commentaire du BL (facultatif, visible sur le PDF)
                  </label>
                  <textarea
                    id={`${id}-comment`}
                    className="input"
                    rows={3}
                    maxLength={4000}
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    disabled={saving}
                  />
                </div>
                <p className="courier-bl-info">
                  <Info size={17} />
                  Vérifiez les séries et les références avant de créer le PDF.
                  Le BL ne confirme aucune remise physique.
                </p>
                {stale && (
                  <div className="courier-bl-warning" role="alert">
                    Les missions ou leur affectation ont changé. Fermez cet
                    aperçu et reprenez la sélection actualisée.
                  </div>
                )}
              </>
            )}
            {saveError && (
              <div className="error-box" role="alert">
                <AlertCircle size={17} />
                {saveError}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="button secondary"
              disabled={saving}
              onClick={() => {
                setPreview(null);
                setCreated(null);
              }}
            >
              {created ? "Fermer" : "Annuler"}
            </button>
            {!created && (
              <button
                type="button"
                className="button primary"
                disabled={saving || stale}
                onClick={() => void create()}
              >
                {saving && <LoaderCircle className="spin" size={17} />}Créer le
                bon de livraison
              </button>
            )}
          </div>
        </Dialog>
      )}
      {detail && (
        <Dialog
          title="Bon de livraison"
          subtitle={detail.reference}
          onClose={() => {
            if (!saving) setDetail(null);
          }}
          wide
        >
          <div className="courier-bl-modal">
            {summary(detail)}
            {cancelOpen && (
              <div className="courier-bl-cancel">
                <label htmlFor={`${id}-cancel`}>Motif d’annulation du BL</label>
                <textarea
                  id={`${id}-cancel`}
                  className="input"
                  rows={3}
                  maxLength={4000}
                  value={cancelReason}
                  onChange={(event) => setCancelReason(event.target.value)}
                  disabled={saving}
                />
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setCancelOpen(false)}
                  disabled={saving}
                >
                  Conserver le BL
                </button>
                <button
                  type="button"
                  className="button danger"
                  onClick={() => void cancel()}
                  disabled={saving || !cancelReason.trim()}
                >
                  Confirmer l’annulation
                </button>
              </div>
            )}
            {saveError && (
              <div className="error-box" role="alert">
                <AlertCircle size={17} />
                {saveError}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="button secondary"
              onClick={() => setDetail(null)}
              disabled={saving}
            >
              Fermer
            </button>
            {detail.can_cancel &&
              detail.status === "prepared" &&
              !cancelOpen && (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => {
                    setCancelOpen(true);
                    setCancelReason("");
                  }}
                >
                  Annuler le BL
                </button>
              )}
          </div>
        </Dialog>
      )}
    </section>
  );
}
function NoteLines({ rows }: { rows: DeliveryNote["lines"] }) {
  return (
    <div className="courier-bl-lines">
      {rows.map((line) => (
        <article key={line.job}>
          <div>
            <strong>{line.serial_number}</strong>
            <span>
              {line.brand} · {line.model}
            </span>
            <small>
              {line.kind === "return" ? "Retour client" : "Livraison"}
            </small>
          </div>
          <dl>
            <div>
              <dt>N° d’appel TVM</dt>
              <dd>{line.call_number}</dd>
            </div>
            <div>
              <dt>N° d’appel client</dt>
              <dd>{line.client_reference || "Non renseigné"}</dd>
            </div>
            <div>
              <dt>Destination</dt>
              <dd>{line.delivery_address || "Non renseignée"}</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

export { pdfUrl as deliveryNotePdfUrl, NoteLines as DeliveryNoteLines };
