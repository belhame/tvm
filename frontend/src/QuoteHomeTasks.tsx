import { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileCheck2,
  RefreshCw,
  Wrench,
} from "lucide-react";
import { api, dateFR, type RecordData, type User } from "./api";
import CallReference from "./CallReference";
import { repairQuoteMoney, type RepairQuote } from "./repairQuotes";
import "./QuoteHomeTasks.css";

type PendingQuotes = { count: number; results: RepairQuote[] };
type HomeSnapshot = {
  pending: PendingQuotes | null;
  toRepair: number | null;
  awaitingReply: number | null;
};

const countValue = (value: unknown): number | null =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;

function readSnapshot(value: RecordData, user: User): HomeSnapshot {
  if (user.role !== "client") {
    const toRepair = countValue(value.metrics?.to_repair_requests);
    const awaitingReply = countValue(value.metrics?.awaiting_quote_reply_requests);
    if (toRepair === null || awaitingReply === null)
      throw new Error("Les dossiers de devis ne sont pas disponibles.");
    return { pending: null, toRepair, awaitingReply };
  }
  const pending = value.pending_repair_quotes;
  const count = countValue(pending?.count);
  const results = pending?.results;
  if (
    !user.client ||
    count === null ||
    !Array.isArray(results) ||
    results.length !== Math.min(count, 8) ||
    new Set(results.map((quote: RepairQuote) => quote.id)).size !== results.length ||
    results.some(
      (quote: RepairQuote) =>
        !Number.isSafeInteger(quote.id) ||
        quote.id <= 0 ||
        quote.client?.id !== user.client ||
        quote.state !== "issued" ||
        !quote.is_current ||
        quote.decision !== "pending" ||
        !quote.can_decide,
    )
  )
    throw new Error("Les devis à confirmer ne sont pas disponibles.");
  return { pending: { count, results }, toRepair: null, awaitingReply: null };
}

export default function QuoteHomeTasks({
  user,
  dashboard,
  onNavigate,
}: {
  user: User;
  dashboard: RecordData;
  onNavigate: (path: string) => void;
}) {
  const client = user.role === "client";
  const [snapshot, setSnapshot] = useState<HomeSnapshot | null>(() => {
    try {
      return readSnapshot(dashboard, user);
    } catch {
      return null;
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let alive = true;
    let controller: AbortController | null = null;
    const load = async () => {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      setBusy(true);
      try {
        const result = await api<RecordData>("dashboard/", { signal: request.signal });
        if (alive && !request.signal.aborted) {
          setSnapshot(readSnapshot(result, user));
          setError(false);
        }
      } catch {
        if (alive && !request.signal.aborted) setError(true);
      } finally {
        if (alive && !request.signal.aborted) setBusy(false);
      }
    };
    const onFocus = () => void load();
    const onVisibility = () => {
      if (document.visibilityState === "visible") void load();
    };
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 30_000);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive = false;
      controller?.abort();
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [user.id, user.role, user.client, refresh]);

  const refreshButton = (
    <button
      type="button"
      className="button secondary small"
      aria-label={client ? "Actualiser les devis à confirmer" : "Actualiser les dossiers de devis"}
      disabled={busy}
      onClick={() => setRefresh((value) => value + 1)}
    >
      <RefreshCw size={16} className={busy ? "spin" : ""} />
      Actualiser
    </button>
  );
  const errorMessage = error ? (
    <p className="quote-home-error" role="alert">
      <AlertCircle size={17} />
      {snapshot
        ? "L’actualisation est indisponible. Les informations affichées peuvent avoir changé."
        : client
          ? "Les devis à confirmer sont indisponibles. Réessayez l’actualisation."
          : "Les dossiers de devis sont indisponibles. Réessayez l’actualisation."}
    </p>
  ) : null;

  if (!client) {
    const own = user.role === "technician";
    return (
      <section className="quote-home-workflow" aria-label="Suivi des accords client">
        <div className="quote-home-workflow-heading">
          <h2>Les accords de vos clients</h2>
          {refreshButton}
        </div>
        {errorMessage}
        <div className="quote-home-workflow-grid">
          <article className="quote-home-workflow-card to-repair">
            <Wrench size={24} />
            <div>
              <h3>À réparer</h3>
              <strong className="quote-home-workflow-count">{snapshot?.toRepair ?? "—"}</strong>
              <p>{own ? "Vos dossiers affectés avec devis accepté." : "Dossiers dont le devis a été accepté."}</p>
            </div>
            <button
              type="button"
              className="button primary small"
              aria-label={own ? "Voir mes dossiers à réparer" : "Voir les dossiers à réparer"}
              onClick={() => onNavigate(`requests/to_repair${own ? "/mine" : ""}`)}
            >
              Ouvrir les dossiers <ArrowRight size={16} />
            </button>
          </article>
          <article className="quote-home-workflow-card quote-sent">
            <Clock3 size={24} />
            <div>
              <h3>Devis envoyés</h3>
              <strong className="quote-home-workflow-count">{snapshot?.awaitingReply ?? "—"}</strong>
              <p>{own ? "Vos dossiers affectés en attente de réponse." : "En attente de la réponse du client."}</p>
            </div>
            <button
              type="button"
              className="button secondary small"
              aria-label={own ? "Voir mes devis envoyés" : "Voir les devis envoyés"}
              onClick={() => onNavigate(`requests/quote_sent${own ? "/mine" : ""}`)}
            >
              Ouvrir les dossiers <ArrowRight size={16} />
            </button>
          </article>
        </div>
      </section>
    );
  }

  const pending = snapshot?.pending;
  return (
    <section className="customer-quote-inbox" aria-label="Devis à confirmer">
      <header className="customer-quote-inbox-heading">
        <div className="customer-quote-inbox-title">
          <FileCheck2 size={25} />
          <div>
            <div className="customer-quote-inbox-title-line">
              <h2>Devis à confirmer</h2>
              <span className="customer-quote-inbox-count" aria-label={pending ? `${pending.count} devis à confirmer` : "Nombre de devis indisponible"}>{pending?.count ?? "—"}</span>
            </div>
            <p>Votre accord permet à TVM de poursuivre la réparation.</p>
          </div>
        </div>
        <div className="customer-quote-inbox-actions">
          {refreshButton}
          <button
            type="button"
            className="button primary small"
            onClick={() => onNavigate("repair-quotes/pending")}
          >
            Voir les devis à confirmer <ArrowRight size={16} />
          </button>
        </div>
      </header>
      {errorMessage}
      {!pending && !error && <p role="status">Chargement des devis à confirmer…</p>}
      {pending?.count === 0 && (
        <p className="customer-quote-inbox-empty"><CheckCircle2 size={19} /> Aucun devis à confirmer.</p>
      )}
      {pending && pending.count > 0 && (
        <>
          <div className="customer-quote-inbox-grid">
            {pending.results.map((quote) => (
              <article key={quote.id} className="customer-quote-inbox-card">
                <div className="customer-quote-inbox-card-heading">
                  <h3>{quote.reference}</h3>
                  <span>Votre réponse est attendue</span>
                </div>
                <CallReference record={quote} role={user.role} compact />
                <dl>
                  <div><dt>Onduleur</dt><dd>{quote.equipment.model || "Modèle à identifier"}</dd></div>
                  <div><dt>N° de série</dt><dd>{quote.equipment.serial_number}</dd></div>
                  <div><dt>Envoyé le</dt><dd>{dateFR(quote.issued_at)}</dd></div>
                  <div className="customer-quote-inbox-total"><dt>Total TTC</dt><dd>{repairQuoteMoney(quote.amounts.total_ttc, quote.amounts.currency, quote.amounts.precision)}</dd></div>
                </dl>
                <button
                  type="button"
                  className="button primary"
                  aria-label={`Confirmer le devis ${quote.reference}`}
                  onClick={() => onNavigate(`repair-quotes/${quote.id}`)}
                >
                  Examiner le devis <ArrowRight size={17} />
                </button>
              </article>
            ))}
          </div>
          {pending.count > pending.results.length && (
            <p className="customer-quote-inbox-more">{pending.results.length} devis affichés sur {pending.count}. Retrouvez les autres dans « Voir les devis à confirmer ».</p>
          )}
        </>
      )}
    </section>
  );
}
