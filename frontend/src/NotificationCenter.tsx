import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  Bell,
  Check,
  Clock3,
  LoaderCircle,
  LockKeyhole,
  MessageCircle,
  RefreshCw,
} from "lucide-react";
import { api, dateFR, type User } from "./api";

type Notification = {
  id: number;
  kind: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
  channel: "in_app";
  call_number?: string;
  client_reference?: string;
  target?: string;
};
type Preference = {
  schedule_mode?: "disabled" | "catch_up_today" | "next_08";
  enabled: boolean;
  hour: number;
  minute: number;
  timezone: string;
  next_run_at: string | null;
  editable: boolean;
  pickup_count: number;
  delivery_count: number;
  in_app_status: string;
  channel_status: string;
  whatsapp_connected: boolean;
  whatsapp_can_send: boolean;
  whatsapp_preview?: {
    text: string;
    scheduled_for: string;
    timezone: string;
    status: "preview_only";
    outbound_sent: false;
  };
};
function scheduledDate(value: string, timezone: string) {
  try {
    return new Intl.DateTimeFormat("fr-FR", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return dateFR(value, true);
  }
}
export default function NotificationCenter({
  user,
  compact = false,
  onOpenReady,
  onOpenMissions,
}: {
  user: User;
  compact?: boolean;
  onOpenReady?: () => void;
  onOpenMissions?: () => void;
}) {
  const id = useId();
  const hasPreferences = user.role === "admin" || user.role === "courier";
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [preference, setPreference] = useState<Preference | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [timezone, setTimezone] = useState("");
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [reading, setReading] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    const pending = new AbortController();
    setLoading(true);
    setErrors([]);
    const endpoints = [
      "logistics/notifications/",
      ...(hasPreferences ? ["logistics/notifications/preferences/"] : []),
    ];
    void Promise.allSettled(
      endpoints.map((endpoint) => api(endpoint, { signal: pending.signal })),
    ).then((results) => {
      if (pending.signal.aborted) return;
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "rejected")
          failures.push(
            result.reason instanceof Error
              ? result.reason.message
              : "Chargement impossible.",
          );
        else if (index === 0) {
          setNotifications(result.value.results || []);
          setUnread(result.value.unread_count || 0);
        } else {
          setPreference(result.value);
          setEnabled(result.value.enabled);
          setTimezone(result.value.timezone);
        }
      });
      setErrors(failures);
      setLoading(false);
    });
    return () => pending.abort();
  }, [hasPreferences, revision, user.id]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!hasPreferences || !timezone.trim() || saving) return;
    const pending = new AbortController();
    controller.current = pending;
    setSaving(true);
    setNotice("");
    setErrors([]);
    try {
      const result = await api<Preference>(
        "logistics/notifications/preferences/",
        {
          method: "PATCH",
          signal: pending.signal,
          body: JSON.stringify({ enabled, timezone: timezone.trim() }),
        },
      );
      if (mounted.current && !pending.signal.aborted) {
        setPreference(result);
        setEnabled(result.enabled);
        setTimezone(result.timezone);
        setNotice(
          "Préférences enregistrées. Le rappel personnel de 08:00 reste dans TVM ; les messages clients ont leur journal séparé.",
        );
      }
    } catch (error) {
      if (mounted.current && !pending.signal.aborted)
        setErrors([
          error instanceof Error ? error.message : "Enregistrement impossible.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setSaving(false);
    }
  }
  async function markRead(notification: Notification) {
    if (reading !== null) return;
    const pending = new AbortController();
    controller.current = pending;
    setReading(notification.id);
    try {
      const result = await api<Notification>(
        `logistics/notifications/${notification.id}/read/`,
        {
          method: "PATCH",
          signal: pending.signal,
          body: JSON.stringify({ read: true }),
        },
      );
      if (mounted.current && !pending.signal.aborted) {
        setNotifications((rows) =>
          rows.map((row) => (row.id === result.id ? result : row)),
        );
        setUnread((count) =>
          Math.max(0, count - (notification.read_at ? 0 : 1)),
        );
        window.dispatchEvent(new Event("tvm-notifications-changed"));
      }
    } catch (error) {
      if (mounted.current && !pending.signal.aborted)
        setErrors([
          error instanceof Error
            ? error.message
            : "La notification n’a pas pu être marquée comme lue.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setReading(null);
    }
  }
  return (
    <section
      className={`notification-center ${compact ? "notification-center-compact" : ""}`}
      aria-label="Notifications et rappels"
    >
      <div className="notification-center-heading">
        <div>
          <Bell size={19} />
          <h2>Notifications et rappels</h2>
          <span>
            {unread} non lue{unread > 1 ? "s" : ""}
          </span>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Actualiser les notifications"
          onClick={() => setRevision((value) => value + 1)}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {errors.map((error, index) => (
        <div className="error-box" role="alert" key={index}>
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      ))}
      {notice && (
        <div className="success-box" role="status">
          <Check size={17} />
          {notice}
        </div>
      )}
      {loading ? (
        <div className="loading-state">
          <LoaderCircle size={18} className="spin" />
          Chargement des notifications…
        </div>
      ) : (
        <>
          {hasPreferences && preference && (
            <form className="notification-preferences" onSubmit={save}>
              <div className="notification-reminder-title">
                <Clock3 size={20} />
                <div>
                  <h3>Rappel quotidien à 08:00</h3>
                  <p>
                    Un rappel dans l’application pour vos enlèvements et
                    livraisons affectés.
                  </p>
                </div>
              </div>
              <label className="notification-toggle">
                <input
                  type="checkbox"
                  checked={enabled}
                  disabled={!preference.editable || saving}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                <span>Activer le rappel quotidien dans l’application</span>
              </label>
              <div className="form-field">
                <label htmlFor={`${id}-timezone`}>
                  Fuseau horaire du rappel
                </label>
                <input
                  id={`${id}-timezone`}
                  className="input"
                  value={timezone}
                  disabled={!preference.editable || saving}
                  required
                  onChange={(event) => setTimezone(event.target.value)}
                  placeholder="Ex. Africa/Tunis"
                  aria-describedby={`${id}-timezone-help`}
                />
                <small id={`${id}-timezone-help`}>
                  Fuseau IANA utilisé par le serveur. L’heure reste fixée à
                  08:00 dans ce fuseau.
                </small>
              </div>
              <div className="notification-schedule">
                <span>
                  {preference.enabled
                    ? "Rappel dans l’application activé"
                    : "Rappel désactivé"}
                </span>
                {preference.schedule_mode === "catch_up_today" ? (
                  <span>
                    Rattrapage d’aujourd’hui au prochain passage du serveur ·{" "}
                    {preference.timezone}
                  </span>
                ) : (
                  preference.next_run_at && (
                    <span>
                      Prochaine préparation :{" "}
                      {scheduledDate(
                        preference.next_run_at,
                        preference.timezone,
                      )}{" "}
                      · {preference.timezone}
                    </span>
                  )
                )}
                <small>
                  {preference.pickup_count} enlèvement(s) et{" "}
                  {preference.delivery_count} livraison(s) affectés
                </small>
              </div>
              {preference.editable && (
                <button
                  type="submit"
                  className="button primary small"
                  disabled={saving || !timezone.trim()}
                >
                  {saving ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Check size={16} />
                  )}
                  Enregistrer les rappels
                </button>
              )}
              <div className="notification-whatsapp-state">
                <MessageCircle size={19} />
                <div>
                  <strong>Rappel WhatsApp personnel non connecté</strong>
                  <p>
                    Ce rappel de 08:00 reste dans TVM. Les messages clients par
                    e-mail ou WhatsApp ont leur journal séparé ; cet écran ne
                    déclenche aucun envoi externe.
                  </p>
                  {preference.whatsapp_preview?.text && (
                    <details>
                      <summary>Aperçu du message prévu</summary>
                      <p className="notification-preview-text">
                        {preference.whatsapp_preview.text}
                      </p>
                      <small>Aperçu uniquement · aucun envoi effectué</small>
                    </details>
                  )}
                </div>
                <LockKeyhole size={16} />
              </div>
            </form>
          )}
          <div className="notification-list">
            {notifications.length ? (
              notifications.map((notification) => (
                <article
                  key={notification.id}
                  className={
                    notification.read_at
                      ? "notification-read"
                      : "notification-unread"
                  }
                >
                  <div>
                    <strong>{notification.title}</strong>
                    <p>{notification.body}</p>
                    {onOpenReady && notification.target === "courier_ready_queue" && (
                      <button
                        type="button"
                        className="button secondary small"
                        disabled={reading !== null}
                        onClick={async () => {
                          if (!notification.read_at) await markRead(notification);
                          onOpenReady();
                        }}
                      >
                        Voir les prêts à livrer
                      </button>
                    )}
                    {onOpenMissions && notification.target === "courier_missions" && (
                      <button
                        type="button"
                        className="button secondary small"
                        disabled={reading !== null}
                        onClick={async () => {
                          if (!notification.read_at) await markRead(notification);
                          onOpenMissions();
                        }}
                      >
                        Voir mes missions
                      </button>
                    )}
                    <small>
                      {dateFR(notification.created_at, true)} · Dans
                      l’application
                    </small>
                  </div>
                  {!notification.read_at && (
                    <button
                      type="button"
                      className="button secondary small"
                      disabled={reading !== null}
                      onClick={() => void markRead(notification)}
                    >
                      {reading === notification.id ? (
                        <LoaderCircle size={15} className="spin" />
                      ) : (
                        <Check size={15} />
                      )}
                      Marquer comme lue
                    </button>
                  )}
                </article>
              ))
            ) : (
              <div className="notification-empty">
                Aucune notification pour votre compte.
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
