import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileCheck2,
  FileText,
  Info,
  LoaderCircle,
  ShieldCheck,
  Truck,
  Undo2,
} from "lucide-react";
import { api, dateFR, type RecordData, type User } from "./api";
import {
  currencyDigits,
  decimalInput,
  quoteCurrencies,
  quoteMoney,
  validAmount,
  validVatRate,
} from "./quoteMoney";

export type DispositionAction = "repair" | "nonrepairable";
export type DiagnosticQuote = {
  id: number;
  number: string;
  issued_at: string;
  price_ht?: string;
  amount_ht?: string;
  vat_rate: string;
  vat_amount: string;
  total_ttc: string;
  currency: string;
  pdf_url: string;
};
export type Disposition = {
  outcome: "repaired" | "nonrepairable" | "pending";
  state:
    | "ready_for_delivery"
    | "awaiting_quote"
    | "awaiting_invoice"
    | "awaiting_free_approval"
    | "invoiced"
    | "free_approved"
    | "closed"
    | "pending";
  diagnosis: string;
  tests_passed: boolean;
  tested_on: string | null;
  classified_at: string | null;
  fee_mode: "billable" | "free";
  free_reason?: string;
  price_ht: string | null;
  vat_rate: string | null;
  currency: string;
  quote_notes: string;
  requires_diagnostic_billing: boolean;
  quote: DiagnosticQuote | null;
  finance_validated_at?: string | null;
  invoice_reference?: string;
  invoiced_on?: string | null;
  billing_notes?: string;
  finance_free_reason?: string;
  can_mark_repaired?: boolean;
  can_mark_nonrepairable?: boolean;
  can_edit_quote?: boolean;
  can_issue_quote?: boolean;
  can_confirm_invoice?: boolean;
  can_approve_free?: boolean;
  can_close?: boolean;
  can_reset?: boolean;
};
export const dispositionLabels: Record<string, string> = {
  pending: "Décision technique en attente",
  ready_for_delivery: "Réparé — prêt à être livré",
  awaiting_quote: "Devis de diagnostic à émettre",
  awaiting_invoice: "Facturation du diagnostic en attente",
  awaiting_free_approval: "Gratuité à approuver",
  invoiced: "Diagnostic facturé",
  free_approved: "Gratuité approuvée",
  closed: "Dossier clôturé",
};
function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{children}</span>
    </div>
  );
}
const shownDate = (value?: string | null, time = false) =>
  value ? dateFR(value, time) : "Non renseignée";

export default function DispositionPanel({
  record: initialRecord,
  user,
  onChanged,
  initialAction,
}: {
  record: RecordData;
  user: User;
  onChanged: (record: RecordData) => Promise<void>;
  initialAction?: DispositionAction;
}) {
  const id = useId();
  const [record, setRecord] = useState(initialRecord);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [action, setAction] = useState<DispositionAction | null>(
    initialAction || null,
  );
  const [diagnosis, setDiagnosis] = useState("");
  const [testsPassed, setTestsPassed] = useState(false);
  const [testedOn, setTestedOn] = useState("");
  const [feeMode, setFeeMode] = useState<"billable" | "free">("billable");
  const [freeReason, setFreeReason] = useState("");
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [priceHt, setPriceHt] = useState("");
  const [vatRate, setVatRate] = useState("");
  const [currency, setCurrency] = useState("TND");
  const [quoteNotes, setQuoteNotes] = useState("");
  const [invoiceReference, setInvoiceReference] = useState("");
  const [invoicedOn, setInvoicedOn] = useState("");
  const [billingNotes, setBillingNotes] = useState("");
  const [financeReason, setFinanceReason] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [resetReason, setResetReason] = useState("");
  const mounted = useRef(true);
  const loadController = useRef<AbortController | null>(null);
  const mutationController = useRef<AbortController | null>(null);
  const mutating = useRef(false);
  const generation = useRef(0);
  const disposition = record.disposition as Disposition | null | undefined;
  const internal = user.role !== "client";
  const finance =
    internal && (user.role === "admin" || user.can_validate_billing === true);
  useEffect(() => {
    setRecord(initialRecord);
  }, [initialRecord]);
  useEffect(() => {
    if (initialAction) {
      setAction(initialAction);
      setError("");
    }
  }, [initialAction]);
  async function refresh() {
    loadController.current?.abort();
    const request = new AbortController();
    loadController.current = request;
    setLoading(true);
    setLoadError("");
    try {
      const response = await api<RecordData>(
        `requests/${initialRecord.id}/disposition/`,
        { signal: request.signal },
      );
      if (mounted.current && !request.signal.aborted) setRecord(response);
    } catch (failure) {
      if (mounted.current && !request.signal.aborted)
        setLoadError(
          failure instanceof Error
            ? failure.message
            : "Le suivi n’a pas pu être actualisé.",
        );
    } finally {
      if (mounted.current && !request.signal.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      generation.current += 1;
      loadController.current?.abort();
      mutationController.current?.abort();
    };
  }, [initialRecord.id]);
  function chooseAction(next: DispositionAction) {
    setAction(next);
    setDiagnosis(disposition?.diagnosis || "");
    setTestsPassed(false);
    setTestedOn("");
    setFeeMode(disposition?.fee_mode || "billable");
    setFreeReason(disposition?.free_reason || "");
    setError("");
  }
  function editQuote() {
    setPriceHt(disposition?.price_ht ?? "");
    setVatRate(disposition?.vat_rate ?? "");
    setCurrency(disposition?.currency || "TND");
    setQuoteNotes(disposition?.quote_notes || "");
    setFeeMode(disposition?.fee_mode || "billable");
    setFreeReason(disposition?.free_reason || "");
    setQuoteOpen(true);
    setError("");
  }
  async function mutate(
    operation:
      | "repair"
      | "nonrepairable"
      | "draft"
      | "quote/issue"
      | "invoice"
      | "free"
      | "close"
      | "reset",
    body: RecordData = {},
  ) {
    if (!internal || loading || mutating.current) return;
    mutating.current = true;
    const current = ++generation.current;
    loadController.current?.abort();
    const request = new AbortController();
    mutationController.current = request;
    setBusy(operation);
    setError("");
    setNotice("");
    try {
      const result = await api<RecordData>(
        `requests/${record.id}/disposition/${operation === "draft" ? "" : `${operation}/`}`,
        {
          method: operation === "draft" ? "PATCH" : "POST",
          signal: request.signal,
          body: JSON.stringify(body),
        },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        current !== generation.current
      )
        return;
      setRecord(result);
      setAction(null);
      setQuoteOpen(false);
      setResetOpen(false);
      setTestsPassed(false);
      setNotice(
        {
          repair:
            "Tests enregistrés : l’onduleur réparé est prêt à être livré.",
          nonrepairable:
            "Retour client enregistré. Le diagnostic reste à régler par facturation ou gratuité approuvée.",
          draft:
            "Conditions du devis enregistrées. Vous pouvez émettre le devis PDF après vérification.",
          "quote/issue":
            "Devis de diagnostic émis dans TVM. Ses montants et son contenu sont figés.",
          invoice:
            "Facturation du diagnostic confirmée. La clôture reste une action distincte.",
          free: "Gratuité du diagnostic approuvée. Le dossier peut être clôturé.",
          close: "Dossier clôturé.",
          reset:
            "La décision technique est rouverte. Les événements précédents restent dans le journal.",
        }[operation],
      );
      try {
        await onChanged(result);
      } catch {
        if (mounted.current && current === generation.current)
          setError(
            "L’action est enregistrée. Rechargez la liste pour actualiser son affichage.",
          );
      }
    } catch (failure) {
      if (
        mounted.current &&
        !request.signal.aborted &&
        current === generation.current
      )
        setError(
          failure instanceof Error
            ? failure.message
            : "L’action n’a pas pu être confirmée.",
        );
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        current === generation.current
      ) {
        setBusy("");
        mutating.current = false;
      }
    }
  }
  function saveDecision(event: FormEvent) {
    event.preventDefault();
    if (!diagnosis.trim() || !action) return;
    if (action === "repair") {
      if (!testsPassed || !testedOn) return;
      void mutate("repair", {
        diagnosis: diagnosis.trim(),
        tests_passed: true,
        tested_on: testedOn,
      });
    } else {
      if (feeMode === "free" && !freeReason.trim()) return;
      void mutate("nonrepairable", {
        diagnosis: diagnosis.trim(),
        fee_mode: feeMode,
        ...(feeMode === "free" ? { free_reason: freeReason.trim() } : {}),
      });
    }
  }
  const amountIsZero = /^0+(?:\.0+)?$/.test(decimalInput(priceHt));
  const quoteValid =
    validAmount(priceHt, currency) &&
    validVatRate(vatRate) &&
    (feeMode === "free" ? amountIsZero && !!freeReason.trim() : !amountIsZero);
  function saveQuote(event: FormEvent) {
    event.preventDefault();
    if (!quoteValid) return;
    void mutate("draft", {
      price_ht: decimalInput(priceHt),
      vat_rate: decimalInput(vatRate),
      currency,
      quote_notes: quoteNotes.trim(),
      fee_mode: feeMode,
      ...(feeMode === "free" ? { free_reason: freeReason.trim() } : {}),
    });
  }
  const savedAmount = disposition?.price_ht;
  const savedRate = disposition?.vat_rate;
  const savedAmountIsZero =
    savedAmount != null && /^0+(?:\.0+)?$/.test(String(savedAmount));
  const savedQuoteReady =
    savedAmount != null &&
    savedRate != null &&
    validAmount(String(savedAmount), disposition?.currency || "TND") &&
    validVatRate(String(savedRate)) &&
    (disposition?.fee_mode === "free"
      ? savedAmountIsZero && !!disposition.free_reason?.trim()
      : !savedAmountIsZero);
  const quote = disposition?.quote;
  const publicPending =
    !internal && (!disposition || disposition.outcome === "pending");
  if (loading && !disposition)
    return (
      <div className="loading-state">
        <LoaderCircle size={18} className="spin" />
        Chargement de la décision technique…
      </div>
    );
  if (publicPending)
    return (
      <div className="disposition-public-pending">
        <Info size={18} />
        <p>
          La décision technique et les documents autorisés seront disponibles
          après leur enregistrement.
        </p>
      </div>
    );
  return (
    <section
      className="disposition-panel"
      aria-label="Décision technique, livraison et retour client"
    >
      {loadError && (
        <ErrorBox>
          {loadError}
          <button
            type="button"
            className="button secondary small"
            onClick={() => void refresh()}
          >
            Actualiser le suivi
          </button>
        </ErrorBox>
      )}
      {error && <ErrorBox>{error}</ErrorBox>}
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={18} />
          {notice}
        </div>
      )}
      {disposition && disposition.outcome !== "pending" && (
        <div
          className={`disposition-summary disposition-${disposition.outcome}`}
        >
          <span className="disposition-summary-icon">
            {disposition.outcome === "repaired" ? (
              <Truck size={23} />
            ) : (
              <Undo2 size={23} />
            )}
          </span>
          <div>
            <span className="disposition-summary-type">
              {disposition.outcome === "repaired"
                ? "Réparation testée"
                : "Onduleur non réparable"}
            </span>
            <h3>{dispositionLabels[disposition.state] || disposition.state}</h3>
            <p className="disposition-diagnosis">{disposition.diagnosis}</p>
            <small>
              {disposition.outcome === "repaired"
                ? `Tests réussis le ${shownDate(disposition.tested_on)}`
                : `Retour décidé le ${shownDate(disposition.classified_at, true)}`}
            </small>
          </div>
        </div>
      )}
      {internal &&
        (disposition?.can_mark_repaired ||
          disposition?.can_mark_nonrepairable) &&
        !action && (
          <div className="disposition-decision-actions">
            <div>
              <h3>Décision après diagnostic et tests</h3>
              <p>
                Confirmez le résultat réel pour orienter le dossier vers la
                livraison ou le retour client.
              </p>
            </div>
            {disposition.can_mark_repaired && (
              <button
                type="button"
                className="button primary"
                disabled={loading || !!busy}
                onClick={() => chooseAction("repair")}
              >
                <ShieldCheck size={17} />
                Tests validés — Réparé
              </button>
            )}
            {disposition.can_mark_nonrepairable && (
              <button
                type="button"
                className="button secondary"
                disabled={loading || !!busy}
                onClick={() => chooseAction("nonrepairable")}
              >
                <Undo2 size={17} />
                Non réparable — Retour client
              </button>
            )}
          </div>
        )}
      {internal &&
        action &&
        (action === "repair"
          ? disposition?.can_mark_repaired
          : disposition?.can_mark_nonrepairable) && (
          <form className="disposition-decision-form" onSubmit={saveDecision}>
            <h3>
              {action === "repair"
                ? "Confirmer les tests de l’onduleur réparé"
                : "Préparer le retour de l’onduleur non réparable"}
            </h3>
            <fieldset disabled={!!busy || loading}>
              <div className="form-grid">
                <div className="form-field span-2">
                  <label htmlFor={`${id}-diagnosis`}>
                    {action === "repair"
                      ? "Synthèse technique des tests"
                      : "Diagnostic de non-réparabilité"}
                  </label>
                  <textarea
                    id={`${id}-diagnosis`}
                    className="input"
                    required
                    maxLength={10000}
                    rows={4}
                    value={diagnosis}
                    onChange={(event) => setDiagnosis(event.target.value)}
                  />
                </div>
                {action === "repair" ? (
                  <>
                    <div className="form-field">
                      <label htmlFor={`${id}-tested`}>Date des tests</label>
                      <input
                        id={`${id}-tested`}
                        className="input"
                        required
                        type="date"
                        value={testedOn}
                        onChange={(event) => setTestedOn(event.target.value)}
                      />
                    </div>
                    <label className="disposition-confirm-check span-2">
                      <input
                        type="checkbox"
                        required
                        checked={testsPassed}
                        onChange={(event) =>
                          setTestsPassed(event.target.checked)
                        }
                      />
                      <span>
                        Je confirme que les tests de fonctionnement sont
                        réussis.
                      </span>
                    </label>
                  </>
                ) : (
                  <>
                    <div className="form-field">
                      <label htmlFor={`${id}-fee`}>
                        Facturation du diagnostic
                      </label>
                      <select
                        id={`${id}-fee`}
                        className="input"
                        value={feeMode}
                        onChange={(event) =>
                          setFeeMode(event.target.value as "billable" | "free")
                        }
                      >
                        <option value="billable">Diagnostic facturable</option>
                        <option value="free">Demander une gratuité</option>
                      </select>
                    </div>
                    {feeMode === "free" && (
                      <div className="form-field span-2">
                        <label htmlFor={`${id}-free`}>
                          Motif de gratuité demandée
                        </label>
                        <textarea
                          id={`${id}-free`}
                          className="input"
                          required
                          maxLength={4000}
                          value={freeReason}
                          onChange={(event) =>
                            setFreeReason(event.target.value)
                          }
                        />
                      </div>
                    )}
                    <p className="disposition-help span-2">
                      Un devis PDF est émis dans TVM. Le diagnostic doit ensuite
                      être facturé, ou la gratuité à zéro doit être approuvée
                      par un compte autorisé en finance.
                    </p>
                  </>
                )}
              </div>
              <div className="disposition-form-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={() => setAction(null)}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={
                    !diagnosis.trim() ||
                    (action === "repair"
                      ? !testsPassed || !testedOn
                      : feeMode === "free" && !freeReason.trim()) ||
                    !!busy
                  }
                >
                  {busy ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : action === "repair" ? (
                    <Truck size={16} />
                  ) : (
                    <Undo2 size={16} />
                  )}
                  {action === "repair"
                    ? "Confirmer la réparation et mettre prêt à livrer"
                    : "Enregistrer le retour client"}
                </button>
              </div>
            </fieldset>
          </form>
        )}
      {disposition?.requires_diagnostic_billing && (
        <section className="diagnostic-quote-section">
          <div className="diagnostic-quote-heading">
            <span>
              <FileText size={20} />
            </span>
            <div>
              <h3>Devis de diagnostic TVM</h3>
              <p>
                {quote
                  ? "Le document émis conserve les montants et les conditions enregistrés lors de son émission."
                  : "Renseignez le prix, la devise et le taux de TVA applicable avant d’émettre le devis."}
              </p>
            </div>
          </div>
          {quote ? (
            <>
              <div className="diagnostic-quote-reference">
                <strong>{quote.number}</strong>
                <span>Émis le {shownDate(quote.issued_at, true)}</span>
                <span>
                  {disposition.fee_mode === "free"
                    ? "Proposition de gratuité — approbation financière distincte"
                    : "Diagnostic facturable"}
                </span>
              </div>
              <dl className="diagnostic-quote-totals">
                <div>
                  <dt>Montant HT</dt>
                  <dd>
                    {quoteMoney(
                      quote.price_ht ?? quote.amount_ht,
                      quote.currency,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Taux de TVA</dt>
                  <dd>{quote.vat_rate} %</dd>
                </div>
                <div>
                  <dt>TVA</dt>
                  <dd>{quoteMoney(quote.vat_amount, quote.currency)}</dd>
                </div>
                <div className="diagnostic-quote-total">
                  <dt>Total TTC</dt>
                  <dd>{quoteMoney(quote.total_ttc, quote.currency)}</dd>
                </div>
              </dl>
              <a
                className="button secondary"
                href={`/api/diagnostic-quotes/${quote.id}/pdf/`}
                target="_blank"
                rel="noreferrer"
              >
                <Download size={16} />
                Télécharger le devis PDF
              </a>
            </>
          ) : (
            internal && (
              <>
                {disposition.can_edit_quote && !quoteOpen && (
                  <button
                    type="button"
                    className="button secondary"
                    disabled={loading || !!busy}
                    onClick={editQuote}
                  >
                    <FileCheck2 size={16} />
                    Renseigner les conditions du devis
                  </button>
                )}
                {quoteOpen && disposition.can_edit_quote && (
                  <form onSubmit={saveQuote} className="diagnostic-quote-form">
                    <fieldset disabled={!!busy || loading}>
                      <div className="form-grid">
                        <div className="form-field">
                          <label htmlFor={`${id}-quote-fee`}>
                            Facturation du diagnostic
                          </label>
                          <select
                            id={`${id}-quote-fee`}
                            className="input"
                            value={feeMode}
                            onChange={(event) =>
                              setFeeMode(
                                event.target.value as "billable" | "free",
                              )
                            }
                          >
                            <option value="billable">
                              Diagnostic facturable
                            </option>
                            <option value="free">Demander une gratuité</option>
                          </select>
                        </div>
                        <div className="form-field">
                          <label htmlFor={`${id}-currency`}>Devise</label>
                          <select
                            id={`${id}-currency`}
                            className="input"
                            value={currency}
                            onChange={(event) =>
                              setCurrency(event.target.value)
                            }
                          >
                            {quoteCurrencies.map(([code, label]) => (
                              <option key={code} value={code}>
                                {label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="form-field">
                          <label htmlFor={`${id}-price`}>Montant HT</label>
                          <input
                            id={`${id}-price`}
                            className="input"
                            type="text"
                            inputMode="decimal"
                            required
                            value={priceHt}
                            onChange={(event) => setPriceHt(event.target.value)}
                            aria-describedby={`${id}-price-help`}
                            placeholder={
                              currency === "TND" ? "Ex. 25,000" : "Ex. 25,00"
                            }
                          />
                          <small id={`${id}-price-help`}>
                            {currencyDigits(currency)} décimales maximum.{" "}
                            {feeMode === "free"
                              ? "Une proposition gratuite exige un montant HT égal à zéro."
                              : "Un diagnostic facturable exige un montant HT strictement positif."}
                          </small>
                        </div>
                        <div className="form-field">
                          <label htmlFor={`${id}-vat`}>Taux de TVA (%)</label>
                          <input
                            id={`${id}-vat`}
                            className="input"
                            type="text"
                            inputMode="decimal"
                            required
                            value={vatRate}
                            onChange={(event) => setVatRate(event.target.value)}
                            aria-describedby={`${id}-vat-help`}
                            placeholder="Taux applicable à renseigner"
                          />
                          <small id={`${id}-vat-help`}>
                            De 0 à 100, avec 2 décimales maximum. Saisissez
                            explicitement 0 si applicable ; aucun taux n’est
                            supposé.
                          </small>
                        </div>
                        {feeMode === "free" && (
                          <div className="form-field span-2">
                            <label htmlFor={`${id}-quote-free`}>
                              Motif de gratuité demandée
                            </label>
                            <textarea
                              id={`${id}-quote-free`}
                              className="input"
                              required
                              maxLength={4000}
                              value={freeReason}
                              onChange={(event) =>
                                setFreeReason(event.target.value)
                              }
                            />
                          </div>
                        )}
                        <div className="form-field span-2">
                          <label htmlFor={`${id}-quote-notes`}>
                            Conditions du devis
                          </label>
                          <textarea
                            id={`${id}-quote-notes`}
                            className="input"
                            rows={3}
                            maxLength={4000}
                            value={quoteNotes}
                            onChange={(event) =>
                              setQuoteNotes(event.target.value)
                            }
                            aria-describedby={`${id}-quote-notes-help`}
                          />
                          <small id={`${id}-quote-notes-help`}>
                            Ces conditions accompagnent le devis destiné au
                            client. Réservez les notes internes aux champs
                            financiers dédiés.
                          </small>
                        </div>
                      </div>
                      <div className="disposition-form-actions">
                        <button
                          type="button"
                          className="button secondary"
                          onClick={() => setQuoteOpen(false)}
                        >
                          Annuler
                        </button>
                        <button
                          type="submit"
                          className="button primary"
                          disabled={!quoteValid || !!busy}
                        >
                          {busy === "draft" ? (
                            <LoaderCircle size={16} className="spin" />
                          ) : (
                            <CheckCircle2 size={16} />
                          )}
                          Enregistrer les conditions du devis
                        </button>
                      </div>
                    </fieldset>
                  </form>
                )}
                {!quoteOpen &&
                  disposition.price_ht != null &&
                  disposition.vat_rate != null && (
                    <dl className="diagnostic-quote-totals">
                      <div>
                        <dt>Montant HT proposé</dt>
                        <dd>
                          {quoteMoney(
                            disposition.price_ht,
                            disposition.currency,
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Taux de TVA proposé</dt>
                        <dd>{disposition.vat_rate} %</dd>
                      </div>
                    </dl>
                  )}
                {!quoteOpen && disposition.can_issue_quote && (
                  <div className="diagnostic-quote-issue">
                    <p>
                      Vérifiez les conditions enregistrées. L’émission attribue
                      un numéro de devis et fige son contenu ; le PDF devient
                      disponible au téléchargement.
                    </p>
                    <button
                      type="button"
                      className="button primary"
                      disabled={loading || !!busy || !savedQuoteReady}
                      onClick={() => void mutate("quote/issue")}
                    >
                      {busy === "quote/issue" ? (
                        <LoaderCircle size={16} className="spin" />
                      ) : (
                        <FileText size={16} />
                      )}
                      Émettre le devis PDF
                    </button>
                  </div>
                )}
              </>
            )
          )}
        </section>
      )}
      {internal && disposition?.requires_diagnostic_billing && (
        <section className="diagnostic-finance-section">
          <h3>Règlement du diagnostic</h3>
          {disposition.finance_validated_at ? (
            <div className="diagnostic-finance-confirmed">
              <CheckCircle2 size={20} />
              <div>
                <strong>
                  {disposition.state === "free_approved" ||
                  disposition.finance_free_reason
                    ? "Gratuité du diagnostic approuvée"
                    : "Facturation du diagnostic confirmée"}
                </strong>
                <p>
                  Validation enregistrée le{" "}
                  {shownDate(disposition.finance_validated_at, true)}
                </p>
                {disposition.invoice_reference && (
                  <p>
                    Facture {disposition.invoice_reference} ·{" "}
                    {shownDate(disposition.invoiced_on)}
                  </p>
                )}
                {disposition.finance_free_reason && (
                  <p>Motif : {disposition.finance_free_reason}</p>
                )}
                {disposition.billing_notes && (
                  <p>Note interne : {disposition.billing_notes}</p>
                )}
              </div>
            </div>
          ) : disposition.can_confirm_invoice && finance ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (invoiceReference.trim() && invoicedOn)
                  void mutate("invoice", {
                    invoice_reference: invoiceReference.trim(),
                    invoiced_on: invoicedOn,
                    billing_notes: billingNotes.trim(),
                  });
              }}
            >
              <p>
                Confirmez la référence de la facture émise pour ce devis. Cette
                saisie ne crée aucune facture dans un ERP et ne confirme aucun
                paiement.
              </p>
              <fieldset disabled={!!busy || loading}>
                <div className="form-grid">
                  <div className="form-field">
                    <label htmlFor={`${id}-invoice`}>
                      Référence de facture
                    </label>
                    <input
                      id={`${id}-invoice`}
                      className="input"
                      required
                      maxLength={120}
                      value={invoiceReference}
                      onChange={(event) =>
                        setInvoiceReference(event.target.value)
                      }
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor={`${id}-invoice-date`}>
                      Date de facture
                    </label>
                    <input
                      id={`${id}-invoice-date`}
                      className="input"
                      required
                      type="date"
                      value={invoicedOn}
                      onChange={(event) => setInvoicedOn(event.target.value)}
                    />
                  </div>
                  <div className="form-field span-2">
                    <label htmlFor={`${id}-billing-notes`}>
                      Notes internes de facturation
                    </label>
                    <textarea
                      id={`${id}-billing-notes`}
                      className="input"
                      maxLength={4000}
                      value={billingNotes}
                      onChange={(event) => setBillingNotes(event.target.value)}
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  className="button primary"
                  disabled={!invoiceReference.trim() || !invoicedOn || !!busy}
                >
                  {busy === "invoice" ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <FileCheck2 size={16} />
                  )}
                  Confirmer la facturation du diagnostic
                </button>
              </fieldset>
            </form>
          ) : disposition.can_approve_free && finance ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (financeReason.trim())
                  void mutate("free", { reason: financeReason.trim() });
              }}
            >
              <p>
                La gratuité proposée reste soumise à votre approbation
                explicite. Le devis émis à zéro conserve son contenu d’origine.
              </p>
              {disposition.free_reason && (
                <p className="diagnostic-free-request">
                  Motif proposé : {disposition.free_reason}
                </p>
              )}
              <div className="form-field">
                <label htmlFor={`${id}-finance-free`}>
                  Motif de gratuité approuvée
                </label>
                <textarea
                  id={`${id}-finance-free`}
                  className="input"
                  required
                  maxLength={4000}
                  value={financeReason}
                  onChange={(event) => setFinanceReason(event.target.value)}
                  disabled={!!busy || loading}
                />
              </div>
              <button
                type="submit"
                className="button primary"
                disabled={!financeReason.trim() || !!busy}
              >
                {busy === "free" ? (
                  <LoaderCircle size={16} className="spin" />
                ) : (
                  <ShieldCheck size={16} />
                )}
                Approuver la gratuité du diagnostic
              </button>
            </form>
          ) : (
            <p className="diagnostic-finance-wait">
              {!quote
                ? "Émettez d’abord le devis de diagnostic pour ouvrir la validation financière."
                : "La facturation ou la gratuité doit être confirmée par un compte autorisé à valider la facturation."}
            </p>
          )}
        </section>
      )}
      {internal && disposition?.can_close && (
        <div className="disposition-close-action">
          <p>
            {disposition.requires_diagnostic_billing
              ? "Le diagnostic est réglé par facturation ou gratuité approuvée. Le dossier peut être clôturé séparément."
              : "La décision technique est enregistrée. Confirmez la clôture du dossier quand sa prise en charge est terminée."}
          </p>
          <button
            type="button"
            className="button primary"
            disabled={!!busy || loading}
            onClick={() => void mutate("close")}
          >
            {busy === "close" ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <CheckCircle2 size={16} />
            )}
            Clôturer le dossier
          </button>
        </div>
      )}
      {internal && disposition?.can_reset && (
        <div className="disposition-reset-action">
          <button
            type="button"
            className="text-button"
            disabled={!!busy}
            onClick={() => setResetOpen((open) => !open)}
          >
            Corriger la décision avant émission du devis
          </button>
          {resetOpen && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (resetReason.trim())
                  void mutate("reset", { reason: resetReason.trim() });
              }}
            >
              <div className="form-field">
                <label htmlFor={`${id}-reset`}>
                  Motif de correction de la décision
                </label>
                <textarea
                  id={`${id}-reset`}
                  className="input"
                  required
                  maxLength={4000}
                  value={resetReason}
                  onChange={(event) => setResetReason(event.target.value)}
                />
              </div>
              <button
                type="submit"
                className="button secondary"
                disabled={!resetReason.trim() || !!busy}
              >
                Rouvrir la décision technique
              </button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
