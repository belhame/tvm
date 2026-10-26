import { useEffect, useRef } from "react";
import { Clock3 } from "lucide-react";
import { dateFR } from "./api";

export type RequestTiming = {
  timer_state: "unknown" | "running" | "closed";
  elapsed_hours: number | null;
  elapsed_days: number | null;
  is_overdue_48h: boolean;
  threshold_hours: number;
  clock_basis: "business_hours_excluding_weekends";
  timezone?: string;
  as_of: string;
  warning: string | null;
};

/** One refresh per list/detail, never one network request per table row. */
export function useServerTimingRefresh(
  refresh: () => void | Promise<void>,
  enabled = true,
) {
  const callback = useRef(refresh);
  callback.current = refresh;
  useEffect(() => {
    if (!enabled) return;
    let inFlight = false;
    const run = async () => {
      if (document.visibilityState === "hidden" || inFlight) return;
      inFlight = true;
      try {
        await callback.current();
      } catch {
        /* The owning view displays its request error. */
      } finally {
        inFlight = false;
      }
    };
    const interval = window.setInterval(() => void run(), 60000);
    const visible = () => {
      if (document.visibilityState === "visible") void run();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [enabled]);
}

/** Durations are server values. No browser-clock extrapolation crosses weekends. */
export default function RequestTimer({
  timing,
  compact = false,
}: {
  timing?: RequestTiming | null;
  compact?: boolean;
}) {
  const known = Boolean(
    timing &&
      timing.timer_state !== "unknown" &&
      typeof timing.elapsed_hours === "number" &&
      Number.isFinite(timing.elapsed_hours) &&
      timing.elapsed_hours >= 0,
  );
  if (!known || !timing || timing.elapsed_hours === null)
    return (
      <div
        className={`request-timer request-timer-unknown ${compact ? "compact" : ""}`}
      >
        <Clock3 size={compact ? 14 : 19} />
        <div>
          <strong>Durée inconnue</strong>
          <span>Dates à compléter</span>
          {!compact && timing?.warning && <small>{timing.warning}</small>}
        </div>
      </div>
    );
  const minutes = Math.floor(timing.elapsed_hours * 60 + 0.000001);
  const days = Math.floor(minutes / (24 * 60));
  const hours = Math.floor(minutes / 60) % 24;
  const remainingMinutes = minutes % 60;
  const overdue = timing.is_overdue_48h;
  const label = overdue
    ? "Délai de 2 jours ouvrés dépassé"
    : "Dans le délai de 2 jours ouvrés";
  const duration = `${days} j ${String(hours).padStart(2, "0")} h ${String(remainingMinutes).padStart(2, "0")} min`;
  return (
    <div
      className={`request-timer ${overdue ? "request-timer-overdue" : "request-timer-on-time"} ${compact ? "compact" : ""}`}
      aria-label={`${duration} ouvrés. ${label}${timing.timer_state === "closed" ? ". Durée figée à la clôture" : ""}`}
    >
      <Clock3 size={compact ? 14 : 21} />
      <div>
        <strong>{duration}</strong>
        <span>{label}</span>
        {timing.timer_state === "closed" && (
          <small>Durée figée à la clôture</small>
        )}
        {!compact && (
          <>
            <small>
              Jours et heures ouvrés · samedi et dimanche exclus · fuseau{" "}
              {timing.timezone || "du serveur"}.
            </small>
            {timing.as_of && (
              <small>Actualisé le {dateFR(timing.as_of, true)}</small>
            )}
            {timing.warning && <small>{timing.warning}</small>}
          </>
        )}
      </div>
    </div>
  );
}
