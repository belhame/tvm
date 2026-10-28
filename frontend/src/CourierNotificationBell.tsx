import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { api } from "./api";
import "./CourierNotificationBell.css";

export default function CourierNotificationBell({ onClick, userId }: {
  onClick: () => void;
  userId?: number;
}) {
  const [unread, setUnread] = useState<number | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    let pending = false;
    let controller: AbortController | null = null;
    setUnread(null);
    setUnavailable(false);
    async function refresh() {
      if (!active || pending || document.hidden) return;
      pending = true;
      controller = new AbortController();
      try {
        const result = await api<{ unread_count: number }>("logistics/notifications/", { signal: controller.signal });
        if (active && !controller.signal.aborted) {
          setUnread(Number.isSafeInteger(result.unread_count) && result.unread_count >= 0 ? result.unread_count : null);
          setUnavailable(false);
        }
      } catch {
        if (active && !controller.signal.aborted) {
          setUnread(null);
          setUnavailable(true);
        }
      } finally {
        pending = false;
      }
    }
    const update = () => void refresh();
    update();
    const timer = window.setInterval(update, 30_000);
    document.addEventListener("visibilitychange", update);
    window.addEventListener("focus", update);
    window.addEventListener("tvm-notifications-changed", update);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
      window.removeEventListener("focus", update);
      window.removeEventListener("tvm-notifications-changed", update);
    };
  }, [userId]);
  return (
    <button type="button" className="icon-button courier-notification-bell"
      aria-label="Notifications et rappels"
      title={unavailable ? "Ouvrir les notifications — actualisation indisponible" : unread === null ? "Ouvrir les notifications" : `${unread} notification${unread > 1 ? "s" : ""} non lue${unread > 1 ? "s" : ""}`}
      onClick={onClick}>
      <Bell size={20} aria-hidden="true" />
      {unread !== null && unread > 0 && <span className="courier-notification-count" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}
      {unread !== null && <span className="sr-only" role="status" aria-live="polite">{unread} notification(s) non lue(s)</span>}
    </button>
  );
}
