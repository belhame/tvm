import { useEffect, useId, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Info,
  LoaderCircle,
} from "lucide-react";
import { api, dateFR } from "./api";
import {
  DeliveryNoteLines,
  deliveryNotePdfUrl,
  type DeliveryNote,
} from "./CourierDeliveryNotes";
export default function LogisticsDeliveryNoteDetail({
  id,
  onClose,
  onChanged,
}: {
  id: number;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const prefix = useId();
  const [record, setRecord] = useState<DeliveryNote | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const write = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const activeId = useRef(id);
  activeId.current = id;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      write.current?.abort();
    };
  }, []);
  useEffect(() => {
    const request = new AbortController();
    setLoading(true);
    setError("");
    setRecord(null);
    api<DeliveryNote>(`logistics/delivery-notes/${id}/`, {
      signal: request.signal,
    })
      .then((note) => {
        if (!request.signal.aborted) setRecord(note);
      })
      .catch((failure: Error) => {
        if (!request.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [id, retry]);
  async function cancel() {
    if (!record?.can_cancel || !reason.trim() || busy) return;
    const request = new AbortController();
    write.current = request;
    const scope = id;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const note = await api<DeliveryNote>(
        `logistics/delivery-notes/${id}/cancel/`,
        {
          method: "POST",
          body: JSON.stringify({ reason: reason.trim() }),
          signal: request.signal,
        },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        activeId.current !== scope
      )
        return;
      setRecord(note);
      setCancelOpen(false);
      setNotice(
        "La préparation du bon a été annulée. Le PDF original reste archivé.",
      );
      try {
        await onChanged();
      } catch {
        if (mounted.current && !request.signal.aborted)
          setNotice(
            "Le bon est annulé. Actualisez la liste pour recharger les autres informations.",
          );
      }
    } catch (failure) {
      if (
        mounted.current &&
        !request.signal.aborted &&
        activeId.current === scope
      )
        setError((failure as Error).message);
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        activeId.current === scope
      )
        setBusy(false);
    }
  }
  return (
    <>
      <div className="courier-bl-modal">
        {loading ? (
          <div className="loading-state" role="status">
            <LoaderCircle className="spin" size={19} />
            Chargement du bon préparé…
          </div>
        ) : (
          record && (
            <>
              <div className="courier-bl-document">
                <FileText size={30} />
                <div>
                  <h3>{record.reference}</h3>
                  <p>
                    {record.client.name} · Livreur : {record.courier.name}
                  </p>
                  <small>Préparé le {dateFR(record.created_at, true)}</small>
                  <span
                    className={`courier-bl-state ${record.status === "cancelled" ? "bl-cancelled" : "bl-prepared"}`}
                  >
                    {record.status === "cancelled" ? "Annulé" : "Préparé"}
                  </span>
                </div>
              </div>
              <DeliveryNoteLines rows={record.lines} />
              <div className="courier-bl-info">
                <Info size={18} />
                Les lignes et le PDF sont figés à la préparation. Ce document ne
                confirme aucune remise physique ni clôture du SAV. Pour
                remplacer le document, annulez sa préparation puis créez un
                nouveau bon.
              </div>
              {record.comment && (
                <div className="courier-bl-comment">
                  <h4>Commentaire figurant sur le PDF</h4>
                  <p>{record.comment}</p>
                </div>
              )}
              {cancelOpen && (
                <div className="courier-bl-cancel">
                  <label htmlFor={`${prefix}-reason`}>
                    Motif d’annulation du BL
                  </label>
                  <textarea
                    id={`${prefix}-reason`}
                    className="input"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={4000}
                    rows={3}
                    required
                    disabled={busy}
                  />
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setCancelOpen(false)}
                    disabled={busy}
                  >
                    Conserver le BL
                  </button>
                  <button
                    type="button"
                    className="button danger"
                    onClick={() => void cancel()}
                    disabled={busy || !reason.trim()}
                  >
                    {busy && <LoaderCircle size={17} className="spin" />}
                    Confirmer l’annulation
                  </button>
                </div>
              )}
            </>
          )
        )}
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={17} />
            {error}
            {!record && (
              <button
                type="button"
                className="button secondary small"
                onClick={() => setRetry((value) => value + 1)}
              >
                Réessayer
              </button>
            )}
          </div>
        )}
        {notice && (
          <div className="success-box" role="status">
            <CheckCircle2 size={17} />
            {notice}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button
          type="button"
          className="button secondary"
          onClick={onClose}
          disabled={busy}
        >
          Fermer
        </button>
        {record && (
          <a
            className="button primary"
            href={deliveryNotePdfUrl(record)}
            target="_blank"
            rel="noreferrer"
          >
            <Download size={17} />
            Télécharger le BL PDF
          </a>
        )}
        {record?.can_cancel && record.status === "prepared" && !cancelOpen && (
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setCancelOpen(true);
              setReason("");
            }}
          >
            Annuler le BL
          </button>
        )}
      </div>
    </>
  );
}
