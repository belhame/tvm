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
  ArrowLeft,
  CheckCircle2,
  FileText,
  Info,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import { ApiError, api, dateFR, type RecordData, type User } from "./api";
import CallReference from "./CallReference";
import RepairQuoteEditor from "./RepairQuoteEditor";
import RepairQuoteSummary from "./RepairQuoteSummary";
import {
  repairQuoteDecisionLabels,
  repairQuoteInput,
  repairQuoteMoney,
  type RepairQuote,
  type RepairQuoteDecision,
  type RepairQuoteInput,
} from "./repairQuotes";
import "./RepairQuotes.css";

type DialogComponent = ComponentType<{
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}>;
type Creation = { requestId: number | null; values?: RepairQuoteInput };
type DecisionAttempt = {
  quote: RepairQuote;
  decision: Exclude<RepairQuoteDecision, "pending">;
  key: string;
};

export default function RepairQuotesWorkspace({
  user,
  requests,
  requestId,
  quoteId,
  createRequested = false,
  onNavigate,
  onOpenRequest,
  onChanged,
  Dialog,
}: {
  user: User;
  requests: RecordData[];
  requestId?: number;
  quoteId?: number;
  createRequested?: boolean;
  onNavigate: (path: string) => void;
  onOpenRequest: (record: RecordData) => void;
  onChanged?: () => Promise<void>;
  Dialog: DialogComponent;
}) {
  const id = useId();
  const canManage = user.role === "admin" || user.role === "manager";
  const [rows, setRows] = useState<RepairQuote[]>([]);
  const [detailState, setDetail] = useState<RepairQuote | null>(null);
  const detail = detailState?.id === quoteId ? detailState : null;
  const [editingQuoteId, setEditingQuoteId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [creation, setCreation] = useState<Creation | null>(
    createRequested && canManage ? { requestId: requestId ?? null } : null,
  );
  const [decisionAttempt, setDecisionAttempt] =
    useState<DecisionAttempt | null>(null);
  const [decisionError, setDecisionError] = useState("");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionConflict, setDecisionConflict] = useState(false);
  const [changeMind, setChangeMind] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [existingDraft, setExistingDraft] = useState<number | null>(null);
  const [contextRequest, setContextRequest] = useState<RecordData | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState("");
  const [contextReload, setContextReload] = useState(0);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const creating = useRef<{ fingerprint: string; key: string } | null>(null);
  const issueKeys = useRef(new Map<string, string>());
  const deciding = useRef(false);
  const currentQuoteId = useRef(quoteId);
  currentQuoteId.current = quoteId;
  const contextRequestId = creation?.requestId ?? requestId;
  const requestOptions: RecordData[] =
    contextRequest && contextRequest.id === contextRequestId &&
    !requests.some((row) => row.id === contextRequestId)
      ? [contextRequest, ...requests]
      : requests;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++generation.current;
      listController.current?.abort();
      detailController.current?.abort();
      mutationController.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (createRequested && canManage)
      setCreation((current) =>
        current?.requestId === requestId
          ? current
          : { requestId: requestId ?? null },
      );
    else setCreation(null);
  }, [requestId, createRequested, canManage]);
  useEffect(() => {
    setContextRequest(null);
    setContextError("");
    if (
      !contextRequestId ||
      requests.some((row) => row.id === contextRequestId)
    ) {
      setContextLoading(false);
      return;
    }
    const controller = new AbortController();
    setContextLoading(true);
    api<RecordData>(`requests/${contextRequestId}/`, {
      signal: controller.signal,
    })
      .then((record) => {
        if (!controller.signal.aborted && mounted.current)
          setContextRequest(record);
      })
      .catch((failure) => {
        if (!controller.signal.aborted && mounted.current)
          setContextError((failure as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted && mounted.current)
          setContextLoading(false);
      });
    return () => controller.abort();
  }, [contextRequestId, requests, user.id, contextReload]);
  useEffect(() => {
    setChangeMind(false);
    setDetailError("");
    setDecisionAttempt(null);
    setDecisionError("");
    setDecisionConflict(false);
    setEditingQuoteId(null);
    mutationController.current?.abort();
  }, [quoteId]);
  useEffect(() => {
    if (
      detail?.id === quoteId &&
      detail?.state === "draft" &&
      canManage &&
      detail.can_edit
    )
      setEditingQuoteId(detail.id);
  }, [detail?.id, quoteId, canManage]);

  useEffect(() => {
    const controller = new AbortController();
    listController.current?.abort();
    listController.current = controller;
    const stamp = ++generation.current;
    setLoading(true);
    setError("");
    api<RepairQuote[]>(
      `repair-quotes/${requestId ? `?service_request=${requestId}` : ""}`,
      { signal: controller.signal },
    )
      .then((values) => {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          stamp === generation.current
        ) {
          setRows(values);
          if (currentQuoteId.current)
            setDetail(
              values.find((row) => row.id === currentQuoteId.current) || null,
            );
        }
      })
      .catch((failure) => {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          stamp === generation.current
        )
          setError((failure as Error).message);
      })
      .finally(() => {
        if (
          !controller.signal.aborted &&
          mounted.current &&
          stamp === generation.current
        )
          setLoading(false);
      });
    return () => controller.abort();
  }, [requestId, user.id, refreshVersion]);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible")
        setRefreshVersion((value) => value + 1);
    };
    const interval = window.setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => {
    detailController.current?.abort();
    if (!quoteId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    detailController.current = controller;
    setDetail(null);
    setDetailLoading(true);
    setDetailError("");
    api<RepairQuote>(`repair-quotes/${quoteId}/`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted && mounted.current) setDetail(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted && mounted.current)
          setDetailError((failure as Error).message);
      })
      .finally(() => {
        if (!controller.signal.aborted && mounted.current)
          setDetailLoading(false);
      });
    return () => controller.abort();
  }, [quoteId, user.id]);

  function apply(value: RepairQuote) {
    listController.current?.abort();
    detailController.current?.abort();
    ++generation.current;
    setLoading(false);
    setDetailLoading(false);
    setRows((current) =>
      [value, ...current.filter((row) => row.id !== value.id)].map((row) =>
        value.state === "issued" &&
        row.service_request === value.service_request &&
        row.id !== value.id
          ? { ...row, is_current: false, can_decide: false }
          : row,
      ),
    );
    if (quoteId === value.id) setDetail(value);
  }
  function notifyRequestChanged() {
    if (onChanged)
      void onChanged().catch(() => {
        if (mounted.current)
          setNotice(
            "Le devis est enregistré. Actualisez les autres données du SAV pour recharger leur état.",
          );
      });
  }

  async function save(
    input: RepairQuoteInput,
    signal: AbortSignal,
    expectedRevision?: number,
  ) {
    if (!canManage)
      throw new Error(
        "La création et l’édition sont réservées aux responsables SAV.",
      );
    if (detail?.state === "draft" && !creation) {
      if (typeof expectedRevision !== "number")
        throw new Error(
          "La révision du brouillon est inconnue. Rechargez le devis avant de l’enregistrer.",
        );
      const result = await api<RepairQuote>(`repair-quotes/${detail.id}/`, {
        method: "PATCH",
        signal,
        body: JSON.stringify({ ...input, expected_revision: expectedRevision }),
      });
      if (!signal.aborted && mounted.current) {
        apply(result);
        notifyRequestChanged();
      }
      return result;
    }
    if (!creation?.requestId)
      throw new Error(
        "Sélectionnez le dossier SAV concerné avant d’enregistrer.",
      );
    if (!requestOptions.some((row) => row.id === creation.requestId))
      throw new Error(
        "Le dossier SAV doit être chargé avant d’enregistrer ce devis. Utilisez « Recharger le dossier » si nécessaire.",
      );
    const payload = { service_request: creation.requestId, ...input };
    const fingerprint = JSON.stringify(payload);
    if (creating.current?.fingerprint !== fingerprint)
      creating.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const result = await api<RepairQuote>("repair-quotes/", {
        method: "POST",
        signal,
        body: JSON.stringify({ ...payload, request_key: creating.current.key }),
      });
      if (!signal.aborted && mounted.current) {
        apply(result);
        notifyRequestChanged();
        setExistingDraft(null);
      }
      return result;
    } catch (failure) {
      if (!signal.aborted && mounted.current && failure instanceof ApiError) {
        const payload = failure.payload as { existing_quote?: { id?: number } };
        if (typeof payload?.existing_quote?.id === "number")
          setExistingDraft(payload.existing_quote.id);
      }
      throw failure;
    }
  }
  async function reloadEditor(signal: AbortSignal) {
    if (!quoteId) throw new Error("Aucun brouillon n’est sélectionné.");
    const fresh = await api<RepairQuote>(`repair-quotes/${quoteId}/`, {
      signal,
    });
    if (!signal.aborted && mounted.current) apply(fresh);
    if (!signal.aborted && mounted.current && fresh.state === "issued")
      setEditingQuoteId(null);
    return fresh;
  }
  async function issue(saved: RepairQuote, signal: AbortSignal) {
    const signature = `${saved.id}:${saved.revision}`;
    if (!issueKeys.current.has(signature))
      issueKeys.current.set(signature, crypto.randomUUID());
    const result = await api<RepairQuote>(`repair-quotes/${saved.id}/issue/`, {
      method: "POST",
      signal,
      body: JSON.stringify({
        expected_revision: saved.revision,
        request_key: issueKeys.current.get(signature),
      }),
    });
    if (!signal.aborted && mounted.current) {
      apply(result);
      notifyRequestChanged();
      setNotice(
        "Devis émis. Le PDF de cette version est figé et le client peut répondre dans son espace.",
      );
      setCreation(null);
      setEditingQuoteId(null);
      onNavigate(`repair-quotes/${result.id}`);
    }
    return result;
  }
  async function reloadDetail() {
    if (!quoteId) return;
    detailController.current?.abort();
    const controller = new AbortController();
    detailController.current = controller;
    setDetailLoading(true);
    setDetailError("");
    try {
      const fresh = await api<RepairQuote>(`repair-quotes/${quoteId}/`, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted && mounted.current) apply(fresh);
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current)
        setDetailError((failure as Error).message);
    } finally {
      if (!controller.signal.aborted && mounted.current)
        setDetailLoading(false);
    }
  }
  async function openRequest(quote: RepairQuote) {
    mutationController.current?.abort();
    const controller = new AbortController();
    mutationController.current = controller;
    try {
      const record = await api<RecordData>(
        `requests/${quote.service_request}/`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted && mounted.current) onOpenRequest(record);
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current)
        setDetailError((failure as Error).message);
    }
  }
  async function decide() {
    const attempt = decisionAttempt;
    if (!attempt || deciding.current || decisionStale) return;
    const controller = new AbortController();
    mutationController.current?.abort();
    mutationController.current = controller;
    deciding.current = true;
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const result = await api<RepairQuote>(
        `repair-quotes/${attempt.quote.id}/decision/`,
        {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            expected_revision: attempt.quote.decision_revision,
            decision: attempt.decision,
            request_key: attempt.key,
          }),
        },
      );
      if (!controller.signal.aborted && mounted.current) {
        apply(result);
        notifyRequestChanged();
        setDecisionAttempt(null);
        setChangeMind(false);
        setNotice(
          `Votre réponse « ${repairQuoteDecisionLabels[result.decision]} » est enregistrée pour la version ${result.version}. TVM a été informé dans l’application.`,
        );
      }
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current) {
        setDecisionError((failure as Error).message);
        if (failure instanceof ApiError && failure.status === 409)
          setDecisionConflict(true);
      }
    } finally {
      deciding.current = false;
      if (!controller.signal.aborted && mounted.current) setDecisionBusy(false);
    }
  }
  const activeDecision =
    decisionAttempt &&
    (rows.find((row) => row.id === decisionAttempt.quote.id) || detail);
  const decisionStale = Boolean(
    decisionAttempt &&
      (decisionConflict ||
        !activeDecision ||
        !activeDecision.is_current ||
        !activeDecision.can_decide ||
        activeDecision.decision_revision !==
          decisionAttempt.quote.decision_revision),
  );
  const selectedRequest = requestOptions.find(
    (row) => row.id === creation?.requestId,
  );
  const visible = rows
    .filter(
      (quote) =>
        (filter === "all" || filter === "draft"
          ? filter === "all" || quote.state === "draft"
          : quote.state === "issued" && quote.decision === filter) &&
        [
          quote.reference,
          quote.call_number,
          quote.client_reference,
          quote.client.name,
          quote.equipment.serial_number,
          quote.equipment.model,
        ]
          .join(" ")
          .toLocaleLowerCase("fr")
          .includes(query.toLocaleLowerCase("fr")),
    )
    .sort(
      (a, b) =>
        Number(b.is_current) - Number(a.is_current) ||
        Number(a.state === "issued") - Number(b.state === "issued") ||
        b.service_request - a.service_request ||
        b.version - a.version,
    );
  return (
    <div className="repair-quotes-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">RÉPARATION & ACCORD CLIENT</div>
          <h1>
            {user.role === "client" ? "Mes devis" : "Devis de réparation"}
          </h1>
          <p>
            {user.role === "client"
              ? "Consultez vos devis, téléchargez leurs PDF et répondez sur la version courante."
              : "Préparez des devis chiffrés et conservez chaque version ainsi que les réponses du client."}
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            className="button primary"
            onClick={() => {
              setExistingDraft(null);
              setCreation({ requestId: requestId ?? null });
            }}
          >
            <Plus size={17} />
            Créer un devis
          </button>
        )}
      </div>
      {requestId && (
        <div className="repair-quotes-info">
          <FileText size={17} />
          Devis du dossier{" "}
          {requestOptions.find((row) => row.id === requestId)?.call_number ||
            requestOptions.find((row) => row.id === requestId)?.reference ||
            `n° ${requestId}`}
          <button
            type="button"
            className="text-button"
            onClick={() => onNavigate("repair-quotes")}
          >
            Voir tous les devis
          </button>
        </div>
      )}
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={18} />
          {notice}
        </div>
      )}
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={18} />
          {error}
        </div>
      )}
      <section className="card repair-quotes-list">
        <div className="repair-quotes-toolbar">
          <label className="repair-quotes-search">
            <Search size={17} />
            <input
              className="input"
              aria-label="Rechercher un devis"
              placeholder={
                user.role === "client"
                  ? "Votre n° d’appel client, devis, série…"
                  : "N° TVM, n° client, devis, client, série…"
              }
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label className="repair-quotes-filter" htmlFor={`${id}-filter`}>
            Afficher
            <select
              className="input"
              id={`${id}-filter`}
              aria-label="État des devis"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">Toutes les versions ({rows.length})</option>
              <option value="pending">
                En attente (
                {
                  rows.filter(
                    (row) =>
                      row.state === "issued" && row.decision === "pending",
                  ).length
                }
                )
              </option>
              <option value="accepted">
                Acceptés (
                {
                  rows.filter(
                    (row) =>
                      row.state === "issued" && row.decision === "accepted",
                  ).length
                }
                )
              </option>
              <option value="refused">
                Refusés (
                {
                  rows.filter(
                    (row) =>
                      row.state === "issued" && row.decision === "refused",
                  ).length
                }
                )
              </option>
              {canManage && (
                <option value="draft">
                  Brouillons (
                  {rows.filter((row) => row.state === "draft").length})
                </option>
              )}
            </select>
          </label>
          <button
            type="button"
            className="button secondary small"
            onClick={() => setRefreshVersion((value) => value + 1)}
            disabled={loading}
          >
            <RefreshCw size={16} />
            Actualiser les devis
          </button>
        </div>
        {loading && !rows.length ? (
          <div className="loading-state" role="status">
            <LoaderCircle className="spin" size={22} />
            Chargement des devis…
          </div>
        ) : visible.length ? (
          <div className="repair-quotes-cards">
            {visible.map((quote) => (
              <article className="repair-quotes-card" key={quote.id}>
                <header>
                  <div>
                    <strong>
                      {quote.reference ||
                        `Brouillon · version ${quote.version}`}
                    </strong>
                    <CallReference record={quote} role={user.role} compact />
                  </div>
                  <span
                    className={`repair-quotes-state ${quote.state === "draft" ? "draft" : quote.decision}`}
                  >
                    {quote.state === "draft"
                      ? "Brouillon"
                      : repairQuoteDecisionLabels[quote.decision]}
                  </span>
                </header>
                <p>{quote.client.name}</p>
                <div className="repair-quotes-card-equipment">
                  <strong>
                    {quote.equipment.model || "Modèle à identifier"}
                  </strong>
                  <span>S/N : {quote.equipment.serial_number}</span>
                </div>
                <footer>
                  <div>
                    <strong>
                      {repairQuoteMoney(
                        quote.amounts.total_ttc,
                        quote.amounts.currency,
                        quote.amounts.precision,
                      )}
                    </strong>
                    <small>
                      {quote.state === "draft"
                        ? "Non publié au client"
                        : quote.is_current
                          ? `Version ${quote.version} · Courante`
                          : `Version ${quote.version} · Historique`}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="button secondary small"
                    onClick={() => onNavigate(`repair-quotes/${quote.id}`)}
                  >
                    Consulter le devis
                  </button>
                </footer>
              </article>
            ))}
          </div>
        ) : (
          <div className="repair-quotes-empty">
            <FileText size={30} />
            <h2>Aucun devis à afficher</h2>
            <p>
              {query || filter !== "all"
                ? "Aucun devis ne correspond à ces filtres."
                : "Les devis publiés apparaîtront ici. Aucun devis n’est émis automatiquement."}
            </p>
          </div>
        )}
      </section>
      {quoteId && !decisionAttempt && !creation && (
        <Dialog
          title="Devis de réparation"
          subtitle={detail?.reference || "Version du devis"}
          onClose={() =>
            onNavigate(
              requestId
                ? `repair-quotes/request/${requestId}`
                : "repair-quotes",
            )
          }
          wide
        >
          <div className="modal-content repair-quotes-detail">
            {detailError && (
              <div className="error-box" role="alert">
                <AlertCircle size={18} />
                {detailError}
              </div>
            )}
            {detailLoading && !detail ? (
              <p role="status">
                <LoaderCircle className="spin" size={20} />
                Chargement du devis…
              </p>
            ) : detail ? (
              <>
                {editingQuoteId === detail.id && canManage ? (
                  <RepairQuoteEditor
                    quote={detail}
                    onSave={save}
                    onIssue={issue}
                    onSaved={apply}
                    onReload={reloadEditor}
                  />
                ) : (
                  <RepairQuoteSummary quote={detail} user={user} />
                )}
                <div className="repair-quotes-actions">
                  <button
                    type="button"
                    className="button secondary small"
                    disabled={detailLoading}
                    onClick={() => void reloadDetail()}
                  >
                    <RefreshCw size={16} />
                    Actualiser le devis
                  </button>
                  <button
                    type="button"
                    className="button secondary small"
                    onClick={() => void openRequest(detail)}
                  >
                    <FileText size={16} />
                    Ouvrir le dossier SAV
                  </button>
                  {canManage && detail.state === "issued" && (
                    <button
                      type="button"
                      className="button secondary small"
                      onClick={() => {
                        setCreation({
                          requestId: detail.service_request,
                          values: repairQuoteInput(detail),
                        });
                        setExistingDraft(null);
                        onNavigate(
                          `repair-quotes/new/${detail.service_request}`,
                        );
                      }}
                    >
                      <Pencil size={16} />
                      Créer une nouvelle révision
                    </button>
                  )}
                </div>
                {user.role === "client" &&
                  detail.state === "issued" &&
                  detail.is_current && (
                    <section className="repair-quotes-decision">
                      <h3>Votre réponse au devis</h3>
                      <p className="repair-quotes-info">
                        <Info size={17} />
                        Votre réponse est enregistrée et communiquée à TVM. Elle
                        ne modifie pas automatiquement les travaux, les
                        livraisons ou les factures.
                      </p>
                      {detail.can_decide ? (
                        <>
                          {detail.decision !== "pending" && !changeMind ? (
                            <>
                              <p>
                                Réponse actuelle :{" "}
                                <strong>
                                  {repairQuoteDecisionLabels[detail.decision]}
                                </strong>
                              </p>
                              <button
                                type="button"
                                className="button secondary"
                                onClick={() => setChangeMind(true)}
                              >
                                Changer d’avis
                              </button>
                            </>
                          ) : (
                            <div className="repair-quotes-actions">
                              {(["accepted", "refused"] as const).map(
                                (choice) => (
                                  <button
                                    type="button"
                                    key={choice}
                                    className={`button ${choice === "accepted" ? "primary" : "secondary"}`}
                                    disabled={detail.decision === choice}
                                    onClick={() => {
                                      setDecisionError("");
                                      setDecisionConflict(false);
                                      setDecisionAttempt({
                                        quote: detail,
                                        decision: choice,
                                        key: crypto.randomUUID(),
                                      });
                                    }}
                                  >
                                    {choice === "accepted"
                                      ? "Accepter le devis"
                                      : "Refuser le devis"}
                                  </button>
                                ),
                              )}
                            </div>
                          )}
                        </>
                      ) : (
                        <p>
                          Cette version n’accepte actuellement aucune nouvelle
                          réponse. Actualisez le devis pour vérifier son état.
                        </p>
                      )}
                    </section>
                  )}
              </>
            ) : (
              !detailError && <p>Devis non disponible.</p>
            )}
          </div>
        </Dialog>
      )}
      {creation && canManage && (
        <Dialog
          title="Créer un devis de réparation"
          subtitle="Brouillon : aucun envoi ni accord automatique"
          onClose={() => {
            setCreation(null);
            setExistingDraft(null);
            if (createRequested)
              onNavigate(
                requestId
                  ? `repair-quotes/request/${requestId}`
                  : "repair-quotes",
              );
          }}
          wide
        >
          <div className="modal-content repair-quotes-detail">
            <div className="repair-quotes-field">
              <label htmlFor={`${id}-request`}>Dossier SAV concerné</label>
              <select
                id={`${id}-request`}
                className="input"
                value={creation.requestId ?? ""}
                onChange={(event) => {
                  setCreation({
                    requestId: event.target.value
                      ? Number(event.target.value)
                      : null,
                  });
                  setExistingDraft(null);
                  creating.current = null;
                }}
              >
                <option value="">Choisir un dossier SAV</option>
                {creation.requestId &&
                  !requestOptions.some(
                    (row) => row.id === creation.requestId,
                  ) && (
                    <option value={creation.requestId}>
                      {contextLoading
                        ? "Chargement du dossier SAV…"
                        : "Dossier SAV à charger"}
                    </option>
                  )}
                {requestOptions.map((request) => (
                  <option key={request.id} value={request.id}>
                    {request.call_number || request.reference} ·{" "}
                    {request.client_reference
                      ? `N° client ${request.client_reference} · `
                      : ""}
                    {request.client_name} · {request.equipment_serial}
                  </option>
                ))}
              </select>
            </div>
            {contextLoading && (
              <p role="status">Chargement du dossier SAV sélectionné…</p>
            )}
            {contextError && (
              <div className="error-box" role="alert">
                <AlertCircle size={17} />
                {contextError}
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => setContextReload((value) => value + 1)}
                >
                  Recharger le dossier
                </button>
              </div>
            )}
            {selectedRequest?.warranty_status === "warranty" && (
              <div className="repair-quotes-info">
                <Info size={17} />
                Ce dossier est indiqué sous garantie. Vérifiez la couverture et
                le motif de la prestation facturable avant d’émettre ce devis.
              </div>
            )}
            {creation.values && (
              <div className="repair-quotes-info">
                <Info size={17} />
                Nouvelle révision : l’ancienne version et sa réponse restent
                inchangées jusqu’à l’émission de ce brouillon. La nouvelle
                version demandera une nouvelle réponse du client.
              </div>
            )}
            {existingDraft && (
              <div className="repair-quotes-info" role="status">
                <Info size={17} />
                Un brouillon existe déjà pour ce dossier.
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => {
                    setCreation(null);
                    onNavigate(`repair-quotes/${existingDraft}`);
                  }}
                >
                  Ouvrir le brouillon existant
                </button>
              </div>
            )}
            <RepairQuoteEditor
              key={`${creation.requestId || "none"}:${creation.values ? "revision" : "new"}`}
              initialValues={creation.values}
              onSave={save}
              onIssue={issue}
              onSaved={(value) => {
                apply(value);
                if (value.state === "draft") {
                  setCreation(null);
                  onNavigate(`repair-quotes/${value.id}`);
                }
              }}
            />
          </div>
        </Dialog>
      )}
      {decisionAttempt && (
        <Dialog
          title={
            decisionAttempt.decision === "accepted"
              ? "Accepter le devis"
              : "Refuser le devis"
          }
          onClose={() => {
            if (!decisionBusy) setDecisionAttempt(null);
          }}
        >
          <div className="modal-content repair-quotes-decision-confirm">
            <FileText size={30} />
            <p>
              Confirmez-vous votre réponse «{" "}
              <strong>
                {repairQuoteDecisionLabels[decisionAttempt.decision]}
              </strong>{" "}
              » pour le devis <strong>{decisionAttempt.quote.reference}</strong>
              , version {decisionAttempt.quote.version} ?
            </p>
            <p>
              Total TTC :{" "}
              <strong>
                {repairQuoteMoney(
                  decisionAttempt.quote.amounts.total_ttc,
                  decisionAttempt.quote.amounts.currency,
                  decisionAttempt.quote.amounts.precision,
                )}
              </strong>
            </p>
            <p>
              Votre nouvelle réponse sera conservée dans l’historique. Aucune
              opération physique ou facture déjà enregistrée ne sera annulée
              automatiquement.
            </p>
            {decisionStale && (
              <div className="repair-quotes-obsolete" role="alert">
                Le devis ou sa réponse a changé. Annulez cette confirmation puis
                actualisez le devis avant de répondre.
              </div>
            )}
            {decisionError && (
              <div className="error-box" role="alert">
                <AlertCircle size={18} />
                {decisionError}
              </div>
            )}
            <div className="repair-quotes-actions">
              <button
                type="button"
                className="button secondary"
                disabled={decisionBusy}
                onClick={() => setDecisionAttempt(null)}
              >
                Annuler
              </button>
              <button
                type="button"
                className="button primary"
                disabled={decisionBusy || decisionStale}
                onClick={() => void decide()}
              >
                {decisionBusy && <LoaderCircle className="spin" size={17} />}
                Oui, confirmer
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
