import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileCheck2,
  Info,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { ApiError } from "./api";
import {
  currencyDigits,
  decimalInput,
  quoteCurrencies,
  validAmount,
  validVatRate,
} from "./quoteMoney";
import {
  repairQuoteInput,
  repairQuoteMoney,
  repairQuotePdfUrl,
  type RepairQuote,
  type RepairQuoteInput,
} from "./repairQuotes";
import "./RepairQuotes.css";

type Props = {
  quote?: RepairQuote | null;
  initialValues?: RepairQuoteInput;
  onSave: (
    values: RepairQuoteInput,
    signal: AbortSignal,
    expectedRevision?: number,
  ) => Promise<RepairQuote>;
  onIssue: (quote: RepairQuote, signal: AbortSignal) => Promise<RepairQuote>;
  onSaved?: (quote: RepairQuote) => void;
  onClose?: () => void;
  onReload?: (signal: AbortSignal) => Promise<RepairQuote>;
};

function emptyDraft(): RepairQuoteInput {
  return {
    lines: [{ description: "", quantity: "1", unit_ht: "" }],
    currency: "TND",
    vat_rate: "",
    discount_kind: "none",
    discount_value: "0",
    terms: "",
    valid_until: null,
  };
}
function copyInput(values: RepairQuoteInput): RepairQuoteInput {
  return {
    lines: values.lines.map((line) => ({ ...line })),
    currency: values.currency,
    vat_rate: values.vat_rate,
    discount_kind: values.discount_kind,
    discount_value:
      values.discount_kind === "none" ? "0" : values.discount_value,
    terms: values.terms || "",
    valid_until: values.valid_until || null,
  };
}
function quoteVersion(quote?: RepairQuote | null) {
  return quote
    ? JSON.stringify([
        quote.id,
        quote.revision,
        quote.state,
        quote.can_edit,
        quote.can_issue,
      ])
    : "new";
}
function positiveQuantity(value: string) {
  const normalized = decimalInput(value);
  return (
    /^\d+(?:\.\d{1,3})?$/.test(normalized) && !/^0+(?:\.0+)?$/.test(normalized)
  );
}
function normalizedInput(values: RepairQuoteInput): RepairQuoteInput {
  return {
    lines: values.lines.map((line) => ({
      description: line.description.trim(),
      quantity: decimalInput(line.quantity),
      unit_ht: decimalInput(line.unit_ht),
    })),
    currency: values.currency,
    vat_rate: decimalInput(values.vat_rate),
    discount_kind: values.discount_kind,
    discount_value:
      values.discount_kind === "none"
        ? "0"
        : decimalInput(values.discount_value),
    terms: values.terms?.trim() || "",
    valid_until: values.valid_until || null,
  };
}

export default function RepairQuoteEditor({
  quote,
  initialValues,
  onSave,
  onIssue,
  onSaved,
  onClose,
  onReload,
}: Props) {
  const id = useId();
  const [saved, setSaved] = useState<RepairQuote | null>(quote || null);
  const [values, setValues] = useState<RepairQuoteInput>(() =>
    copyInput(quote ? repairQuoteInput(quote) : initialValues || emptyDraft()),
  );
  const [busy, setBusy] = useState<"save" | "issue" | "reload" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [obsolete, setObsolete] = useState(false);
  const [reloadConfirm, setReloadConfirm] = useState(false);
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const submitting = useRef(false);
  const savedRef = useRef(saved);
  savedRef.current = saved;
  const dirty =
    !saved ||
    JSON.stringify(copyInput(values)) !==
      JSON.stringify(copyInput(repairQuoteInput(saved)));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const incomingVersion = quoteVersion(quote);
  const previousIncoming = useRef(incomingVersion);
  const readOnly = Boolean(saved && !saved.can_edit);
  const editable = !readOnly && !obsolete;
  const canIssue = Boolean(
    saved &&
      saved.state === "draft" &&
      saved.can_issue &&
      !dirty &&
      !obsolete &&
      !busy,
  );
  const currentQuote = useRef(quote);
  currentQuote.current = quote;
  const callbackRef = useRef({ onSave, onIssue, onSaved, onReload });
  callbackRef.current = { onSave, onIssue, onSaved, onReload };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      controller.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (previousIncoming.current === incomingVersion) return;
    previousIncoming.current = incomingVersion;
    const incoming = currentQuote.current;
    const local = savedRef.current;
    // The parent's refresh after our own save is the same version. It must
    // not replace a new local draft that the user has already started typing.
    if (incoming && quoteVersion(incoming) === quoteVersion(local)) return;
    generation.current += 1;
    controller.current?.abort();
    submitting.current = false;
    setBusy(null);
    setReloadConfirm(false);
    if (!incoming || (local && incoming.id !== local.id)) {
      setSaved(incoming || null);
      setValues(
        copyInput(
          incoming ? repairQuoteInput(incoming) : initialValues || emptyDraft(),
        ),
      );
      setObsolete(false);
      setError("");
      setNotice("");
      return;
    }
    if (dirtyRef.current) {
      setObsolete(true);
      setNotice("");
    } else {
      setSaved(incoming);
      setValues(copyInput(repairQuoteInput(incoming)));
      setObsolete(false);
      setError("");
    }
  }, [incomingVersion]);

  function edit(next: (previous: RepairQuoteInput) => RepairQuoteInput) {
    if (!editable || busy) return;
    setValues(next);
    setError("");
    setNotice("");
  }
  function validationError(input: RepairQuoteInput): string | null {
    if (!input.lines.length) return "Ajoutez au moins une ligne au devis.";
    if (input.lines.length > 100)
      return "Le devis peut contenir au maximum 100 lignes.";
    for (let index = 0; index < input.lines.length; index += 1) {
      const line = input.lines[index];
      if (!line.description)
        return `Renseignez la description de la ligne ${index + 1}.`;
      if (line.description.length > 2000)
        return `La description de la ligne ${index + 1} ne peut pas dépasser 2 000 caractères.`;
      if (!positiveQuantity(line.quantity))
        return `La quantité de la ligne ${index + 1} doit être positive, avec trois décimales au maximum.`;
      if (!validAmount(line.unit_ht, input.currency))
        return `Le prix unitaire HT de la ligne ${index + 1} doit être positif ou nul, avec ${currencyDigits(input.currency)} décimales au maximum.`;
    }
    if ((input.terms?.length || 0) > 10000)
      return "Les conditions publiques ne peuvent pas dépasser 10 000 caractères.";
    if (!validVatRate(input.vat_rate))
      return "Renseignez explicitement le taux de TVA applicable, de 0 à 100 %, avec deux décimales au maximum.";
    if (
      input.discount_kind === "percent" &&
      !validVatRate(input.discount_value)
    )
      return "La remise en pourcentage doit être comprise entre 0 et 100 %, avec deux décimales au maximum.";
    if (
      input.discount_kind === "fixed" &&
      !validAmount(input.discount_value, input.currency)
    )
      return `Renseignez le montant de remise avec ${currencyDigits(input.currency)} décimales au maximum.`;
    return null;
  }

  async function mutate(mode: "save" | "issue", event?: FormEvent) {
    event?.preventDefault();
    if (submitting.current || busy || obsolete) return;
    if (mode === "save" && !editable) return;
    if (mode === "issue" && !canIssue) return;
    const input = normalizedInput(values);
    if (mode === "save") {
      const validation = validationError(input);
      if (validation) {
        setError(validation);
        return;
      }
    }
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const stamp = ++generation.current;
    const live = () =>
      mounted.current &&
      !request.signal.aborted &&
      generation.current === stamp;
    submitting.current = true;
    setBusy(mode);
    setError("");
    setNotice("");
    try {
      const response =
        mode === "save"
          ? await callbackRef.current.onSave(
              input,
              request.signal,
              saved?.revision,
            )
          : await callbackRef.current.onIssue(
              saved as RepairQuote,
              request.signal,
            );
      if (!live()) return;
      setSaved(response);
      savedRef.current = response;
      setValues(copyInput(repairQuoteInput(response)));
      setObsolete(false);
      setNotice(
        mode === "save"
          ? "Brouillon enregistré. Les montants ci-dessous sont calculés par le serveur."
          : "Devis émis. Son contenu et ses montants sont figés dans le PDF.",
      );
      try {
        callbackRef.current.onSaved?.(response);
      } catch {
        if (live())
          setNotice(
            "Le devis est enregistré. Actualisez la liste pour recharger ses autres informations.",
          );
      }
    } catch (failure) {
      if (!live()) return;
      setError(
        failure instanceof Error
          ? failure.message
          : "Le serveur n’a pas confirmé l’enregistrement du devis.",
      );
      if (failure instanceof ApiError && failure.status === 409)
        setObsolete(true);
    } finally {
      if (live()) {
        submitting.current = false;
        setBusy(null);
      }
    }
  }

  async function reload() {
    if (submitting.current || busy) return;
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    const stamp = ++generation.current;
    const live = () =>
      mounted.current &&
      !request.signal.aborted &&
      generation.current === stamp;
    setBusy("reload");
    setError("");
    try {
      const incoming = callbackRef.current.onReload
        ? await callbackRef.current.onReload(request.signal)
        : currentQuote.current;
      if (!live()) return;
      if (
        !incoming ||
        (!callbackRef.current.onReload &&
          obsolete &&
          quoteVersion(incoming) === quoteVersion(savedRef.current))
      )
        throw new Error(
          "Fermez puis rouvrez le brouillon pour récupérer sa version actuelle.",
        );
      setSaved(incoming);
      savedRef.current = incoming;
      setValues(copyInput(repairQuoteInput(incoming)));
      setObsolete(false);
      setReloadConfirm(false);
      setNotice("La version actuelle du devis a été rechargée.");
    } catch (failure) {
      if (live()) setError((failure as Error).message);
    } finally {
      if (live()) setBusy(null);
    }
  }

  const amounts = saved?.amounts;
  const pdf = saved ? repairQuotePdfUrl(saved) : null;
  return (
    <div className="repair-quotes-editor">
      <div className="repair-quotes-editor-header">
        <div>
          <span className="repair-quotes-eyebrow">DEVIS DE RÉPARATION TVM</span>
          <h2>{saved?.reference || "Nouveau devis de réparation"}</h2>
          <p>
            Préparez les pièces et prestations, enregistrez le brouillon, puis
            émettez le devis après vérification.
          </p>
        </div>
        <span
          className={`repair-quotes-state repair-quotes-state-${saved?.state || "draft"}`}
        >
          {saved?.state === "issued" ? "Devis émis" : "Brouillon"}
        </span>
      </div>

      {obsolete && (
        <div className="repair-quotes-obsolete" role="alert">
          <AlertCircle size={19} />
          <div>
            <strong>Le devis a changé depuis le début de votre saisie.</strong>
            <p>
              Vos saisies locales sont conservées. Rechargez la version actuelle
              avant de poursuivre ; cette action abandonnera vos modifications
              non enregistrées.
            </p>
            {!reloadConfirm ? (
              <button
                type="button"
                className="button secondary small"
                onClick={() => setReloadConfirm(true)}
                disabled={Boolean(busy)}
              >
                <RefreshCw size={15} />
                Recharger le brouillon
              </button>
            ) : (
              <div className="repair-quotes-reload-confirm">
                <p>Abandonner les saisies locales et recharger le devis ?</p>
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => setReloadConfirm(false)}
                  disabled={Boolean(busy)}
                >
                  Conserver mes saisies
                </button>
                <button
                  type="button"
                  className="button primary small"
                  onClick={() => void reload()}
                  disabled={Boolean(busy)}
                >
                  {busy === "reload" && (
                    <LoaderCircle className="spin" size={15} />
                  )}
                  Confirmer le rechargement
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {readOnly && !obsolete && (
        <div className="repair-quotes-info">
          <FileCheck2 size={18} />
          <p>
            Ce devis est en lecture seule. Une nouvelle version se prépare
            depuis le dossier ou la liste des devis.
          </p>
        </div>
      )}

      <form onSubmit={(event) => void mutate("save", event)}>
        <fieldset
          className="repair-quotes-fieldset"
          disabled={Boolean(busy) || !editable}
        >
          <div className="repair-quotes-form-settings">
            <div className="field">
              <label htmlFor={`${id}-currency`}>Devise du devis</label>
              <select
                id={`${id}-currency`}
                className="input"
                value={values.currency}
                onChange={(event) =>
                  edit((previous) => ({
                    ...previous,
                    currency: event.target
                      .value as RepairQuoteInput["currency"],
                  }))
                }
              >
                {quoteCurrencies.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <small>
                Prix et remises : {currencyDigits(values.currency)} décimales au
                maximum.
              </small>
            </div>
            <div className="field">
              <label htmlFor={`${id}-vat`}>Taux de TVA du devis (%)</label>
              <input
                id={`${id}-vat`}
                className="input"
                type="text"
                inputMode="decimal"
                value={values.vat_rate}
                onChange={(event) =>
                  edit((previous) => ({
                    ...previous,
                    vat_rate: event.target.value,
                  }))
                }
                required
                placeholder="Taux applicable, 0 si applicable"
              />
              <small>
                Renseignez le taux applicable. Aucun taux n’est présumé.
              </small>
            </div>
          </div>
          <section
            className="repair-quotes-lines"
            aria-labelledby={`${id}-lines-heading`}
          >
            <div className="repair-quotes-lines-heading">
              <div>
                <h3 id={`${id}-lines-heading`}>Pièces et prestations</h3>
                <p>Les quantités et prix unitaires sont saisis hors taxe.</p>
              </div>
              {editable && (
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() =>
                    edit((previous) => ({
                      ...previous,
                      lines: [
                        ...previous.lines,
                        { description: "", quantity: "1", unit_ht: "" },
                      ],
                    }))
                  }
                  disabled={values.lines.length >= 100}
                >
                  <Plus size={15} />
                  Ajouter une ligne
                </button>
              )}
            </div>
            <div className="repair-quotes-line-labels" aria-hidden="true">
              <span>Description</span>
              <span>Quantité</span>
              <span>Prix unitaire HT</span>
              <span />
            </div>
            {values.lines.map((line, index) => (
              <div className="repair-quotes-line" key={index}>
                <div className="field repair-quotes-line-description">
                  <label htmlFor={`${id}-line-${index}-description`}>
                    Description de la ligne {index + 1}
                  </label>
                  <textarea
                    id={`${id}-line-${index}-description`}
                    className="input"
                    rows={2}
                    maxLength={2000}
                    value={line.description}
                    onChange={(event) =>
                      edit((previous) => ({
                        ...previous,
                        lines: previous.lines.map((item, row) =>
                          row === index
                            ? { ...item, description: event.target.value }
                            : item,
                        ),
                      }))
                    }
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor={`${id}-line-${index}-quantity`}>
                    Quantité de la ligne {index + 1}
                  </label>
                  <input
                    id={`${id}-line-${index}-quantity`}
                    className="input"
                    type="text"
                    inputMode="decimal"
                    value={line.quantity}
                    onChange={(event) =>
                      edit((previous) => ({
                        ...previous,
                        lines: previous.lines.map((item, row) =>
                          row === index
                            ? { ...item, quantity: event.target.value }
                            : item,
                        ),
                      }))
                    }
                    required
                  />
                </div>
                <div className="field">
                  <label htmlFor={`${id}-line-${index}-unit`}>
                    Prix unitaire HT de la ligne {index + 1}
                  </label>
                  <input
                    id={`${id}-line-${index}-unit`}
                    className="input"
                    type="text"
                    inputMode="decimal"
                    value={line.unit_ht}
                    onChange={(event) =>
                      edit((previous) => ({
                        ...previous,
                        lines: previous.lines.map((item, row) =>
                          row === index
                            ? { ...item, unit_ht: event.target.value }
                            : item,
                        ),
                      }))
                    }
                    required
                  />
                </div>
                {editable && (
                  <button
                    type="button"
                    className="repair-quotes-remove-line icon-button"
                    aria-label={`Supprimer la ligne ${index + 1}`}
                    onClick={() =>
                      edit((previous) => ({
                        ...previous,
                        lines: previous.lines.filter((_, row) => row !== index),
                      }))
                    }
                    disabled={values.lines.length === 1}
                  >
                    <Trash2 size={17} />
                  </button>
                )}
              </div>
            ))}
          </section>
          <div className="repair-quotes-form-settings repair-quotes-discount-settings">
            <div className="field">
              <label htmlFor={`${id}-discount-kind`}>Type de remise</label>
              <select
                id={`${id}-discount-kind`}
                className="input"
                value={values.discount_kind}
                onChange={(event) =>
                  edit((previous) => ({
                    ...previous,
                    discount_kind: event.target
                      .value as RepairQuoteInput["discount_kind"],
                    discount_value: event.target.value === "none" ? "0" : "",
                  }))
                }
              >
                <option value="none">Aucune remise</option>
                <option value="percent">Remise en pourcentage</option>
                <option value="fixed">Remise en montant HT</option>
              </select>
            </div>
            {values.discount_kind !== "none" && (
              <div className="field">
                <label htmlFor={`${id}-discount-value`}>
                  {values.discount_kind === "percent"
                    ? "Remise (%)"
                    : `Montant de remise HT (${values.currency})`}
                </label>
                <input
                  id={`${id}-discount-value`}
                  className="input"
                  type="text"
                  inputMode="decimal"
                  value={values.discount_value}
                  onChange={(event) =>
                    edit((previous) => ({
                      ...previous,
                      discount_value: event.target.value,
                    }))
                  }
                  required
                />
                <small>
                  {values.discount_kind === "percent"
                    ? "De 0 à 100 %, avec deux décimales au maximum."
                    : "Le serveur vérifie la remise par rapport au sous-total HT."}
                </small>
              </div>
            )}
          </div>
          <div className="repair-quotes-public-fields">
            <div className="field">
              <label htmlFor={`${id}-terms`}>
                Conditions / notes publiques
              </label>
              <textarea
                id={`${id}-terms`}
                className="input"
                rows={4}
                maxLength={10000}
                value={values.terms || ""}
                onChange={(event) =>
                  edit((previous) => ({
                    ...previous,
                    terms: event.target.value,
                  }))
                }
                aria-describedby={`${id}-terms-help`}
              />
              <small id={`${id}-terms-help`}>
                Ces informations figurent sur le devis destiné au client.
                Réservez les notes internes au suivi SAV.
              </small>
            </div>
            <div className="field">
              <label htmlFor={`${id}-valid-until`}>
                Valable jusqu’au (facultatif)
              </label>
              <input
                id={`${id}-valid-until`}
                className="input"
                type="date"
                value={values.valid_until || ""}
                onChange={(event) =>
                  edit((previous) => ({
                    ...previous,
                    valid_until: event.target.value || null,
                  }))
                }
              />
            </div>
          </div>
        </fieldset>

        <section
          className="repair-quotes-amounts"
          aria-labelledby={`${id}-amounts-heading`}
        >
          <div className="repair-quotes-amounts-heading">
            <h3 id={`${id}-amounts-heading`}>
              {dirty && saved
                ? "Totaux de la dernière sauvegarde"
                : "Totaux calculés par le serveur"}
            </h3>
            {saved && <span>{saved.currency}</span>}
          </div>
          {amounts ? (
            <>
              <dl>
                <div>
                  <dt>Sous-total HT</dt>
                  <dd>
                    {repairQuoteMoney(
                      amounts.subtotal_ht,
                      amounts.currency,
                      amounts.precision,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Remise HT</dt>
                  <dd>
                    {repairQuoteMoney(
                      amounts.discount_ht,
                      amounts.currency,
                      amounts.precision,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Net HT</dt>
                  <dd>
                    {repairQuoteMoney(
                      amounts.net_ht,
                      amounts.currency,
                      amounts.precision,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>TVA ({amounts.vat_rate.replace(".", ",")} %)</dt>
                  <dd>
                    {repairQuoteMoney(
                      amounts.vat_amount,
                      amounts.currency,
                      amounts.precision,
                    )}
                  </dd>
                </div>
                <div className="repair-quotes-total">
                  <dt>Total TTC</dt>
                  <dd>
                    {repairQuoteMoney(
                      amounts.total_ttc,
                      amounts.currency,
                      amounts.precision,
                    )}
                  </dd>
                </div>
              </dl>
              {dirty && (
                <p className="repair-quotes-amounts-note">
                  <Info size={15} />
                  Ces montants correspondent au dernier brouillon enregistré.
                  Enregistrez les modifications pour les actualiser.
                </p>
              )}
              {amounts.fully_discounted && (
                <p className="repair-quotes-amounts-note">
                  Le serveur indique une remise totale sur ce devis.
                </p>
              )}
            </>
          ) : (
            <p className="repair-quotes-amounts-placeholder">
              <Info size={18} />
              Les totaux seront disponibles après l’enregistrement du brouillon.
              Aucun total n’est calculé dans le navigateur.
            </p>
          )}
        </section>
        {error && (
          <div className="repair-quotes-error" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        {notice && (
          <div className="repair-quotes-notice" role="status">
            <CheckCircle2 size={17} />
            <span>{notice}</span>
          </div>
        )}
        <div className="repair-quotes-editor-actions">
          <div className="repair-quotes-editor-action-note">
            {saved?.state === "issued"
              ? "Le PDF correspond à la version émise."
              : "L’émission fige le contenu du devis et génère son PDF. Enregistrez d’abord toutes les modifications."}
          </div>
          <div className="repair-quotes-actions">
            {onClose && (
              <button
                type="button"
                className="button secondary"
                onClick={onClose}
                disabled={Boolean(busy)}
              >
                Fermer
              </button>
            )}
            {pdf && (
              <a
                className="button secondary"
                href={pdf}
                target="_blank"
                rel="noreferrer"
              >
                <Download size={17} />
                Télécharger le devis PDF
              </a>
            )}
            {editable && (
              <button
                type="submit"
                className="button secondary"
                disabled={Boolean(busy)}
              >
                {busy === "save" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Save size={17} />
                )}
                Enregistrer le brouillon
              </button>
            )}
            {saved?.state === "draft" && saved.can_issue && (
              <button
                type="button"
                className="button primary"
                onClick={() => void mutate("issue")}
                disabled={!canIssue}
              >
                {busy === "issue" ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <FileCheck2 size={17} />
                )}
                Émettre le devis
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
