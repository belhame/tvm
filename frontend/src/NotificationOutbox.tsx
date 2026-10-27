import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  LoaderCircle,
  Mail,
  MessageCircle,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import { api, dateFR, type RecordData } from "./api";

type Channel = {
  enabled: boolean;
  configured: boolean;
  operational: boolean;
  status: string;
};
type Channels = {
  email: Channel;
  whatsapp: Channel;
  client_preferences: {
    notify_email: boolean;
    notify_whatsapp: boolean;
  } | null;
};
type OutboxEntry = {
  id: number;
  client: { id: number; name: string };
  channel: "email" | "whatsapp";
  event: string;
  state: string;
  blocked_reason: string;
  attempts: number;
  next_attempt_at: string | null;
  sent_at: string | null;
  provider_status: string;
  recipient_redacted: string;
  created_at: string;
  can_retry: boolean;
};
type OutboxPreview = {
  notification: OutboxEntry;
  preview: {
    subject: string;
    text: string;
    recipient_redacted: string;
    call_number: string;
    client_reference: string;
    serial_number: string;
  };
  preview_token: string;
  warnings: string[];
};
const stateLabels: Record<string, string> = {
  blocked: "Bloquée",
  pending: "En attente d’envoi",
  processing: "Traitement en cours",
  sent: "Acceptée par le fournisseur",
  failed: "Échec de l’envoi",
  uncertain: "Résultat fournisseur incertain",
  cancelled: "Annulée",
};

export function NotificationChannels({
  clientId,
  personal = false,
}: {
  clientId?: string;
  personal?: boolean;
}) {
  const [channels, setChannels] = useState<Channels | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const pending = new AbortController();
    setChannels(null);
    setError("");
    api<Channels>(
      `logistics/channels/${clientId ? `?client=${encodeURIComponent(clientId)}` : ""}`,
      { signal: pending.signal },
    )
      .then((result) => {
        if (!pending.signal.aborted) setChannels(result);
      })
      .catch((failure: Error) => {
        if (!pending.signal.aborted) setError(failure.message);
      });
    return () => pending.abort();
  }, [clientId]);
  return (
    <section
      className="notification-channels"
      aria-label="Canaux de notification client"
    >
      <h2>
        {personal
          ? "Notifications de votre société"
          : "Canaux de notification client"}
      </h2>
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}
      <div className="notification-channel-grid">
        {(["email", "whatsapp"] as const).map((key) => {
          const channel = channels?.[key];
          return (
            <div className="notification-channel-card" key={key}>
              {key === "email" ? (
                <Mail size={22} />
              ) : (
                <MessageCircle size={22} />
              )}
              <div>
                <strong>{key === "email" ? "E-mail" : "WhatsApp"}</strong>
                <span>
                  {!channel
                    ? error
                      ? "État non vérifié"
                      : "Vérification…"
                    : channel.operational
                      ? "Disponible pour les envois autorisés"
                      : !channel.enabled
                        ? "Canal désactivé côté serveur"
                        : !channel.configured
                          ? "Accès fournisseur manquants"
                          : "Configuration à vérifier"}
                </span>
                {channels?.client_preferences && (
                  <small>
                    {(
                      key === "email"
                        ? channels.client_preferences.notify_email
                        : channels.client_preferences.notify_whatsapp
                    )
                      ? "Autorisées pour cette société"
                      : "Désactivées pour cette société"}
                  </small>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <p>
        Une notification est annoncée comme envoyée uniquement après acceptation
        réelle du fournisseur. Cette acceptation ne prouve pas sa lecture ni la
        remise du matériel.
      </p>
    </section>
  );
}

export default function NotificationOutbox({
  clients,
}: {
  clients: RecordData[];
}) {
  const [clientId, setClientId] = useState("");
  const [state, setState] = useState("");
  const [channel, setChannel] = useState("");
  const [rows, setRows] = useState<OutboxEntry[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [preview, setPreview] = useState<OutboxPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState<number | null>(null);
  const [uncertainConfirmed, setUncertainConfirmed] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const mounted = useRef(true);
  const scopeGeneration = useRef(0);
  const previewController = useRef<AbortController | null>(null);
  const retryController = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      scopeGeneration.current += 1;
      previewController.current?.abort();
      retryController.current?.abort();
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    scopeGeneration.current += 1;
    previewController.current?.abort();
    setPreview(null);
    setUncertainConfirmed(false);
    setPreviewBusy(null);
    setRows([]);
    setLoading(true);
    setError("");
    const parameters = new URLSearchParams();
    if (clientId) parameters.set("client", clientId);
    if (state) parameters.set("state", state);
    if (channel) parameters.set("channel", channel);
    api<{ results: OutboxEntry[]; counts: Record<string, number> }>(
      `logistics/outbox/?${parameters}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          setRows(result.results);
          setCounts(result.counts);
        }
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [clientId, state, channel, revision]);
  async function inspect(entry: OutboxEntry) {
    previewController.current?.abort();
    const pending = new AbortController();
    previewController.current = pending;
    const generation = scopeGeneration.current;
    setPreviewBusy(entry.id);
    setError("");
    setUncertainConfirmed(false);
    try {
      const result = await api<OutboxPreview>(
        `logistics/outbox/${entry.id}/preview/`,
        { signal: pending.signal },
      );
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === scopeGeneration.current
      )
        setPreview(result);
    } catch (failure) {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === scopeGeneration.current
      )
        setError(
          failure instanceof Error
            ? failure.message
            : "L’aperçu n’a pas pu être chargé.",
        );
    } finally {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === scopeGeneration.current
      )
        setPreviewBusy(null);
    }
  }
  async function retry() {
    if (
      !preview ||
      retrying ||
      (preview.notification.state === "uncertain" && !uncertainConfirmed)
    )
      return;
    const pending = new AbortController();
    retryController.current = pending;
    const generation = scopeGeneration.current;
    setRetrying(true);
    setError("");
    setNotice("");
    try {
      const result = await api<OutboxEntry>(
        `logistics/outbox/${preview.notification.id}/retry/`,
        {
          method: "POST",
          signal: pending.signal,
          body: JSON.stringify({
            preview_token: preview.preview_token,
            ...(preview.notification.state === "uncertain"
              ? { confirm_uncertain: true }
              : {}),
          }),
        },
      );
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === scopeGeneration.current
      ) {
        setNotice(
          `Demande de relance enregistrée. État actuel : ${stateLabels[result.state] || result.state}.`,
        );
        setPreview(null);
        setRevision((value) => value + 1);
      }
    } catch (failure) {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === scopeGeneration.current
      )
        setError(
          failure instanceof Error
            ? failure.message
            : "La relance n’a pas pu être confirmée.",
        );
    } finally {
      if (mounted.current && !pending.signal.aborted) setRetrying(false);
    }
  }
  return (
    <section
      className="notification-outbox card"
      aria-label="Journal des notifications client"
    >
      <div className="notification-outbox-heading">
        <div>
          <h2>Journal des notifications client</h2>
          <p>
            Les rappels personnels de 08:00 sont distincts de ces messages
            destinés aux sociétés clientes.
          </p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Actualiser le journal des notifications"
          onClick={() => setRevision((value) => value + 1)}
        >
          <RefreshCw size={17} />
        </button>
      </div>
      <div className="notification-outbox-filters">
        <select
          className="input"
          aria-label="Société des notifications"
          value={clientId}
          onChange={(event) => setClientId(event.target.value)}
          disabled={retrying}
        >
          <option value="">Toutes les sociétés autorisées</option>
          {clients.map((client) => (
            <option value={client.id} key={client.id}>
              {client.name}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="État des notifications client"
          value={state}
          onChange={(event) => setState(event.target.value)}
          disabled={retrying}
        >
          <option value="">Tous les états</option>
          {Object.entries(stateLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          className="input"
          aria-label="Canal des notifications client"
          value={channel}
          onChange={(event) => setChannel(event.target.value)}
          disabled={retrying}
        >
          <option value="">Tous les canaux</option>
          <option value="email">E-mail</option>
          <option value="whatsapp">WhatsApp</option>
        </select>
      </div>
      <NotificationChannels clientId={clientId} />
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={17} />
          {notice}
        </div>
      )}
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}
      <div className="notification-outbox-counts">
        {Object.entries(counts).map(([key, value]) => (
          <span key={key}>
            {stateLabels[key] || key} : <strong>{value}</strong>
          </span>
        ))}
      </div>
      {loading ? (
        <div className="loading-state">
          <LoaderCircle size={18} className="spin" />
          Chargement du journal…
        </div>
      ) : rows.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Société / événement</th>
                <th>Canal / destinataire masqué</th>
                <th>État réel</th>
                <th>Horodatage / tentatives</th>
                <th>Vérification</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <div className="primary-cell">
                      <span>{row.client.name}</span>
                      <small>{row.event}</small>
                    </div>
                  </td>
                  <td>
                    <div className="primary-cell">
                      <span>
                        {row.channel === "email" ? "E-mail" : "WhatsApp"}
                      </span>
                      <small>
                        {row.recipient_redacted ||
                          "Destinataire non disponible"}
                      </small>
                    </div>
                  </td>
                  <td>
                    <span
                      className={`notification-outbox-state outbox-${row.state}`}
                    >
                      {stateLabels[row.state] || row.state}
                    </span>
                    {row.blocked_reason && (
                      <small className="notification-outbox-reason">
                        {row.blocked_reason}
                      </small>
                    )}
                    {row.provider_status && (
                      <small className="notification-outbox-reason">
                        {row.provider_status}
                      </small>
                    )}
                  </td>
                  <td>
                    <div className="primary-cell">
                      <span>
                        {row.sent_at
                          ? `Acceptée le ${dateFR(row.sent_at, true)}`
                          : row.next_attempt_at
                            ? `Prochaine tentative : ${dateFR(row.next_attempt_at, true)}`
                            : `Créée le ${dateFR(row.created_at, true)}`}
                      </span>
                      <small>{row.attempts} tentative(s)</small>
                    </div>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={retrying || previewBusy !== null}
                      onClick={() => void inspect(row)}
                    >
                      {previewBusy === row.id ? (
                        <LoaderCircle size={15} className="spin" />
                      ) : (
                        <Eye size={15} />
                      )}
                      {row.can_retry
                        ? "Prévisualiser avant relance"
                        : "Voir l’aperçu"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">
          <Mail size={28} />
          <h3>Aucune notification dans cette vue</h3>
          <p>
            Les événements autorisés alimenteront ce journal avec leur état
            réel.
          </p>
        </div>
      )}
      {preview && (
        <section
          className="notification-outbox-preview"
          aria-label="Aperçu de la notification client"
        >
          <div>
            <h3>Aperçu avant toute relance</h3>
            <button
              type="button"
              className="icon-button"
              aria-label="Fermer l’aperçu de notification"
              disabled={retrying}
              onClick={() => setPreview(null)}
            >
              <X size={17} />
            </button>
          </div>
          <p>
            <strong>Destinataire masqué :</strong>{" "}
            {preview.preview.recipient_redacted}
          </p>
          {preview.preview.subject && (
            <p>
              <strong>Objet :</strong> {preview.preview.subject}
            </p>
          )}
          <pre>{preview.preview.text}</pre>
          {preview.warnings.map((warning, index) => (
            <p className="notification-outbox-warning" key={index}>
              {warning}
            </p>
          ))}
          {preview.notification.state === "uncertain" && (
            <label className="notification-uncertain-confirm">
              <input
                type="checkbox"
                checked={uncertainConfirmed}
                onChange={(event) =>
                  setUncertainConfirmed(event.target.checked)
                }
                disabled={retrying}
              />
              <span>
                Je comprends que cette notification peut avoir déjà été acceptée
                par le fournisseur.
              </span>
            </label>
          )}
          {preview.notification.can_retry && (
            <button
              type="button"
              className="button primary"
              disabled={
                retrying ||
                (preview.notification.state === "uncertain" &&
                  !uncertainConfirmed)
              }
              onClick={() => void retry()}
            >
              {retrying ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <Send size={16} />
              )}
              Confirmer la demande de relance
            </button>
          )}
          <small>
            La relance utilise cet aperçu pendant 10 minutes. Le journal
            affichera le résultat réel du traitement.
          </small>
        </section>
      )}
    </section>
  );
}
