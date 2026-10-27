import "./DiagnosticAssistant.css";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ComponentType,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  Archive,
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  History,
  Info,
  Library,
  LoaderCircle,
  Plus,
  Search,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { api, dateFR, type RecordData, type User } from "./api";
import CallReference, { callIdentity } from "./CallReference";
import {
  documentKindLabels,
  knowledgeStateLabels,
  textStatusLabels,
  type DiagnosticInput,
  type DiagnosticResult,
  type DiagnosticSource,
  type DiagnosticStatus,
  type KnowledgeCase,
  type KnowledgeDocument,
} from "./diagnostics";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
type Props = {
  user: User;
  requests: RecordData[];
  equipment: RecordData[];
  interventions: RecordData[];
  Dialog: ComponentType<DialogProps>;
  initialRequestId?: number;
  initialInterventionId?: number;
};
type SourceSelection = { kind: "document" | "case"; id: number };
const allowedRoles = ["admin", "manager", "technician"];
const diagnosticTabs = [
  { key: "diagnostic", label: "Diagnostic", icon: Bot },
  { key: "library", label: "Bibliothèque", icon: Library },
  { key: "cases", label: "Retours validés", icon: CheckCircle2 },
  { key: "history", label: "Historique", icon: History },
];
function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{children}</span>
    </div>
  );
}
function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="diagnostic-notice">
      <Info size={18} />
      <div>{children}</div>
    </div>
  );
}
function Loading({ text = "Chargement…" }: { text?: string }) {
  return (
    <div className="diagnostic-loading" role="status">
      <LoaderCircle size={19} className="spin" />
      {text}
    </div>
  );
}
function StateBadge({ state }: { state: "draft" | "approved" | "archived" }) {
  return (
    <span className={`diagnostic-state diagnostic-state-${state}`}>
      {knowledgeStateLabels[state]}
    </span>
  );
}
const warningLabels: Record<string, string> = {
  personal_information_redacted: "Des coordonnées ou identifiants détectés ont été retirés de la saisie technique.",
  equipment_brand_model_from_record: "La marque et le modèle proviennent de l’équipement du dossier sélectionné.",
  board_reference_requires_confirmation: "Vérifiez la référence de la carte avant d’appliquer une procédure spécifique.",
  revision_requires_confirmation: "La révision de la carte reste à confirmer sur l’appareil.",
  generic_source_verify_board_and_revision_before_procedure: "Cette documentation concerne le modèle ; vérifiez sa correspondance avec la carte et sa révision avant toute procédure.",
  generic_manual_revision_differs_verify_applicability: "La version du manuel diffère de la révision renseignée. Vérifiez qu’il s’applique à votre appareil.",
  historical_sources_no_longer_current: "Une source de cette analyse n’est plus exploitable. Recherchez les références actuelles avant de poursuivre.",
};
function WarningList({ values = [] }: { values?: string[] }) {
  return values.length ? (
    <ul className="diagnostic-warnings">
      {values.map((text, i) => (
        <li key={i}>{warningLabels[text] || text}</li>
      ))}
    </ul>
  ) : null;
}
function safeDocumentUrl(value: string | undefined) {
  return value?.startsWith("/api/knowledge/documents/") &&
    !value.includes("\\") &&
    !value.includes("//")
    ? value
    : undefined;
}
function sourceSelection(source: DiagnosticSource): SourceSelection | null {
  const id = source.kind === "document" ? source.document_id : source.case_id;
  return typeof id === "number" && Number.isInteger(id) && id > 0
    ? { kind: source.kind, id }
    : null;
}
const resultLabels: Record<string, string> = {
  sources_found: "Sources approuvées trouvées",
  no_sources: "Aucune source approuvée correspondante",
  completed: "Analyse disponible · à vérifier par un technicien",
  abstained: "Analyse non produite · sources insuffisantes",
  requires_configuration: "IA à connecter · recherche documentaire disponible",
  provider_error: "Le fournisseur IA n’a pas répondu correctement",
  invalid_response: "Réponse IA écartée par le contrôle du serveur",
  sources_changed: "Les sources ont changé · relancez la recherche",
};

export default function DiagnosticAssistant(props: Props) {
  const { user, Dialog, initialInterventionId } = props;
  const [tab, setTab] = useState("diagnostic");
  const [source, setSource] = useState<SourceSelection | null>(null);
  const [version, setVersion] = useState(0);
  if (!allowedRoles.includes(user.role)) return null;
  return (
    <div className="diagnostic-assistant">
      <div className="page-heading">
        <div>
          <div className="eyebrow">EXPERTISE & DOCUMENTATION</div>
          <h1>Assistant diagnostic</h1>
          <p>
            Recherchez dans vos sources techniques approuvées et préparez un
            diagnostic à vérifier.
          </p>
        </div>
        <span className="diagnostic-security">
          <ShieldCheck size={17} />
          Espace interne TVM
        </span>
      </div>
      <div
        className="page-tabs diagnostic-tabs"
        role="group"
        aria-label="Vues de l’assistant diagnostic"
      >
        {diagnosticTabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={tab === key ? "active" : ""}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            <Icon size={17} />
            {label}
          </button>
        ))}
      </div>
      {tab === "diagnostic" ? (
        <DiagnosticForm {...props} onSource={setSource} />
      ) : tab === "library" ? (
        <DocumentLibrary
          user={user}
          Dialog={Dialog}
          onSource={setSource}
          refreshKey={version}
          onChanged={() => setVersion((v) => v + 1)}
        />
      ) : tab === "history" ? (
        <DiagnosticHistory Dialog={Dialog} onSource={setSource} />
      ) : (
        <CaseLibrary
          {...props}
          onSource={setSource}
          refreshKey={version}
          onChanged={() => setVersion((v) => v + 1)}
          initialInterventionId={initialInterventionId}
        />
      )}
      {source && (
        <KnowledgeDetail
          key={`${source.kind}:${source.id}`}
          selection={source}
          user={user}
          Dialog={Dialog}
          onClose={() => setSource(null)}
          onChanged={() => setVersion((v) => v + 1)}
        />
      )}
    </div>
  );
}

function DiagnosticForm({
  user,
  requests,
  equipment,
  initialRequestId,
  onSource,
}: Props & { onSource: (source: SourceSelection) => void }) {
  const prefix = useId();
  const [requestId, setRequestId] = useState(
    initialRequestId ? String(initialRequestId) : "",
  );
  const [brand, setBrand] = useState("Eaton");
  const [model, setModel] = useState("");
  const [symptoms, setSymptoms] = useState("");
  const [faultCode, setFaultCode] = useState("");
  const [measurements, setMeasurements] = useState("");
  const [boardReference, setBoardReference] = useState("");
  const [revision, setRevision] = useState("");
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState<DiagnosticStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"search" | "analyze" | null>(null);
  const action = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const requestKey = useRef<{ signature: string; key: string } | null>(null);
  const selectedRequest = requests.find(
    (item) => String(item.id) === requestId,
  );
  const selectedEquipment = equipment.find(
    (item) => item.id === selectedRequest?.equipment,
  );
  const authoritativeBrand =
    selectedEquipment?.brand || selectedRequest?.equipment_brand || "";
  const authoritativeModel =
    selectedEquipment?.model || selectedRequest?.equipment_model || "";
  const technicalInput = JSON.stringify({
    requestId,
    brand: selectedRequest ? authoritativeBrand : brand,
    model: selectedRequest ? authoritativeModel : model,
    symptoms,
    faultCode,
    measurements,
    boardReference,
    revision,
  });
  useEffect(() => {
    const controller = new AbortController();
    api<DiagnosticStatus>("diagnostics/status/", { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setStatus(response);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setStatusError(failure.message);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    generation.current += 1;
    action.current?.abort();
    setResult(null);
    setError("");
    setBusy(null);
    setConsent(false);
    requestKey.current = null;
  }, [technicalInput]);
  useEffect(
    () => () => {
      generation.current += 1;
      action.current?.abort();
    },
    [],
  );
  async function run(mode: "search" | "analyze", event?: FormEvent) {
    event?.preventDefault();
    if (mode === "analyze" && !consent) return;
    const input: DiagnosticInput = {
      brand: (selectedRequest ? authoritativeBrand : brand).trim(),
      model: (selectedRequest ? authoritativeModel : model).trim(),
      symptoms: symptoms.trim(),
      fault_code: faultCode.trim(),
      measurements: measurements.trim(),
      board_reference: boardReference.trim(),
      revision: revision.trim(),
      ...(selectedRequest ? { service_request: selectedRequest.id } : {}),
    };
    if (
      !input.brand ||
      !input.model ||
      ![input.symptoms, input.fault_code, input.measurements].some(Boolean)
    ) {
      setError(
        "Renseignez la marque, le modèle et au moins des symptômes, un code défaut ou des mesures.",
      );
      return;
    }
    action.current?.abort();
    const controller = new AbortController();
    action.current = controller;
    const stamp = ++generation.current;
    setBusy(mode);
    setError("");
    setResult(null);
    const signature = JSON.stringify(input);
    if (!requestKey.current || requestKey.current.signature !== signature)
      requestKey.current = { signature, key: crypto.randomUUID() };
    try {
      const response = await api<DiagnosticResult>(
        `diagnostics/${mode === "search" ? "search" : "analyze"}/`,
        {
          method: "POST",
          body: JSON.stringify({
            ...input,
            ...(mode === "analyze"
              ? { request_key: requestKey.current.key }
              : {}),
          }),
          signal: controller.signal,
        },
      );
      if (!controller.signal.aborted && stamp === generation.current)
        setResult(response);
    } catch (failure) {
      if (!controller.signal.aborted && stamp === generation.current)
        setError((failure as Error).message);
    } finally {
      if (!controller.signal.aborted && stamp === generation.current)
        setBusy(null);
    }
  }
  const configured =
    status?.configured === true || status?.provider_configured === true;
  return (
    <div className="diagnostic-layout">
      <section className="card diagnostic-input-card">
        <div className="diagnostic-section-heading">
          <span className="diagnostic-icon">
            <Bot size={22} />
          </span>
          <div>
            <h2>Décrire le problème technique</h2>
            <p>Une recherche précise commence par le bon modèle.</p>
          </div>
        </div>
        <form onSubmit={(event) => void run("search", event)}>
          <div className="form-grid">
            <div className="field full">
              <label htmlFor={`${prefix}-request`}>
                Dossier SAV lié (facultatif)
              </label>
              <select
                id={`${prefix}-request`}
                className="input"
                value={requestId}
                onChange={(event) => setRequestId(event.target.value)}
              >
                <option value="">
                  Sans dossier · recherche technique uniquement
                </option>
                {requests.map((item) => (
                  <option key={item.id} value={item.id}>
                    {callIdentity(item).tvm || `Dossier ${item.id}`} ·{" "}
                    {item.equipment_model ||
                      equipment.find((unit) => unit.id === item.equipment)
                        ?.model ||
                      "Modèle non renseigné"}
                  </option>
                ))}
              </select>
              <small>
                Le dossier fixe la marque et le modèle. Son descriptif, ses
                coordonnées et son numéro de série ne sont pas recopiés.
              </small>
            </div>
            <div className="field">
              <label htmlFor={`${prefix}-brand`}>Marque</label>
              <input
                id={`${prefix}-brand`}
                className="input"
                value={selectedRequest ? authoritativeBrand : brand}
                onChange={(event) => setBrand(event.target.value)}
                readOnly={Boolean(selectedRequest)}
                required
                maxLength={100}
              />
            </div>
            <div className="field">
              <label htmlFor={`${prefix}-model`}>Modèle</label>
              <input
                id={`${prefix}-model`}
                className="input"
                value={selectedRequest ? authoritativeModel : model}
                onChange={(event) => setModel(event.target.value)}
                readOnly={Boolean(selectedRequest)}
                required
                maxLength={120}
                placeholder="Référence exacte du modèle"
              />
            </div>
            <div className="field">
              <label htmlFor={`${prefix}-board`}>
                Référence de carte (facultative)
              </label>
              <input
                id={`${prefix}-board`}
                className="input"
                value={boardReference}
                onChange={(event) => setBoardReference(event.target.value)}
                maxLength={120}
              />
            </div>
            <div className="field">
              <label htmlFor={`${prefix}-revision`}>
                Révision de carte (facultative)
              </label>
              <input
                id={`${prefix}-revision`}
                className="input"
                value={revision}
                onChange={(event) => setRevision(event.target.value)}
                maxLength={80}
              />
            </div>
            <div className="field full">
              <label htmlFor={`${prefix}-symptoms`}>Symptômes</label>
              <textarea
                id={`${prefix}-symptoms`}
                className="input"
                aria-describedby={`${prefix}-technical-help`}
                value={symptoms}
                onChange={(event) => setSymptoms(event.target.value)}
                maxLength={6000}
                rows={5}
                placeholder="Décrivez uniquement les signes observés sur l’onduleur…"
              />
              <small id={`${prefix}-technical-help`}>
                Renseignez au moins des symptômes, un code défaut ou des
                mesures.
              </small>
            </div>
            <div className="field full">
              <label htmlFor={`${prefix}-fault`}>
                Code défaut (facultatif)
              </label>
              <input
                id={`${prefix}-fault`}
                className="input"
                value={faultCode}
                onChange={(event) => setFaultCode(event.target.value)}
                maxLength={120}
              />
            </div>
            <div className="field full">
              <label htmlFor={`${prefix}-measures`}>Mesures (facultatif)</label>
              <textarea
                id={`${prefix}-measures`}
                className="input"
                value={measurements}
                onChange={(event) => setMeasurements(event.target.value)}
                maxLength={6000}
                rows={3}
                placeholder="Tensions, températures, conditions et tests déjà réalisés…"
              />
            </div>
          </div>
          <Notice>
            Ne saisissez ni nom de client, coordonnées, mot de passe ou numéro
            de série dans les champs techniques.
          </Notice>
          {error && <ErrorMessage>{error}</ErrorMessage>}
          <button
            type="submit"
            className="button primary diagnostic-search"
            disabled={Boolean(busy)}
          >
            {busy === "search" ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <Search size={17} />
            )}
            Rechercher les sources
          </button>
          <div className="diagnostic-ai-consent">
            <label className="diagnostic-checkbox">
              <input
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>
                J’autorise le partage de cette saisie technique et des extraits
                approuvés avec le fournisseur IA configuré.
              </span>
            </label>
            <button
              type="button"
              className="button secondary"
              onClick={() => void run("analyze")}
              disabled={!consent || Boolean(busy)}
            >
              {busy === "analyze" ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <Bot size={17} />
              )}
              Analyser avec IA
            </button>
            <small>
              L’analyse ne modifie aucun équipement, dossier ou intervention.
            </small>
          </div>
        </form>
      </section>
      <div className="diagnostic-results-column">
        <section className="card diagnostic-availability">
          <div>
            <span
              className={`diagnostic-state ${configured ? "diagnostic-state-approved" : "diagnostic-state-draft"}`}
            >
              {status
                ? configured
                  ? status.enabled === false
                    ? "IA configurée · désactivée"
                    : "IA activée par configuration · non testée"
                  : "IA à connecter"
                : "État IA non vérifié"}
            </span>
            <h2>Des réponses fondées sur vos sources</h2>
            <p>
              La recherche utilise les manuels, procédures et retours approuvés
              du modèle exact. Elle fonctionne sans clé IA.
            </p>
            {status?.message && <p>{status.message}</p>}
          </div>
          {statusError && <ErrorMessage>{statusError}</ErrorMessage>}
          <p className="diagnostic-vision-note">
            <FileText size={17} />
            Les PDF et TXT sont indexés par leur texte. Un schéma numérisé reste
            consultable ; ses images ne sont pas interprétées par l’IA.
          </p>
        </section>
        {busy ? (
          <section className="card diagnostic-result-card">
            <Loading
              text={
                busy === "search"
                  ? "Recherche des sources approuvées…"
                  : "Demande envoyée au serveur d’analyse…"
              }
            />
          </section>
        ) : result ? (
          <>
            <DiagnosticResultView result={result} onSource={onSource} />
            {!["sources_found", "no_sources"].includes(result.status) && (
              <button
                className="button secondary"
                onClick={() => {
                  requestKey.current = null;
                  setResult(null);
                  setConsent(false);
                }}
              >
                Préparer une nouvelle analyse
              </button>
            )}
          </>
        ) : (
          <section className="card diagnostic-empty">
            <BookOpen size={32} />
            <h2>Votre recherche commence ici</h2>
            <p>
              Renseignez le modèle et les symptômes, puis recherchez les
              références disponibles.
            </p>
            <span>Aucun diagnostic généré automatiquement.</span>
          </section>
        )}
        <div className="diagnostic-safety">
          <ShieldCheck size={19} />
          <p>
            Les hypothèses restent à confirmer par un technicien qualifié.
            Respectez les procédures du constructeur et les règles de
            consignation électrique avant toute intervention.
          </p>
        </div>
      </div>
    </div>
  );
}

function DiagnosticResultView({
  result,
  onSource,
}: {
  result: DiagnosticResult;
  onSource: (source: SourceSelection) => void;
}) {
  const citation = (ids: (string | number)[] = []) => (
    <div className="diagnostic-citations">
      {ids.map((id) => {
        const index = result.sources.findIndex(
          (entry) => String(entry.id) === String(id),
        );
        return index >= 0 ? (
          <a
            key={id}
            href={`#diagnostic-source-${index}`}
            onClick={(event) => {
              event.preventDefault();
              document
                .getElementById(`diagnostic-source-${index}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
              document.getElementById(`diagnostic-source-${index}`)?.focus();
            }}
          >
            [{index + 1}] {result.sources[index].title}
            {result.sources[index].available === false
              ? " · source obsolète"
              : ""}
          </a>
        ) : (
          <span key={id}>Citation indisponible</span>
        );
      })}
    </div>
  );
  return (
    <section
      className="card diagnostic-result-card"
      aria-label="Résultats du diagnostic"
    >
      <div
        className="diagnostic-result-heading"
        role="status"
        aria-live="polite"
      >
        <Search size={19} />
        <h2>{resultLabels[result.status] || result.status}</h2>
      </div>
      <WarningList values={result.warnings} />
      {result.sources.some((source) => source.available === false) && (
        <WarningList
          values={[
            "Cette source n’est plus approuvée ou exploitable ; refaites l’analyse.",
          ]}
        />
      )}
      {result.output && (
        <div className="diagnostic-output">
          <h3>Synthèse technique</h3>
          <p>{result.output.summary}</p>
          {result.output.hypotheses?.length > 0 && (
            <>
              <h3>Hypothèses à vérifier</h3>
              <ol>
                {result.output.hypotheses.map((item, i) => (
                  <li key={i}>
                    <strong>{item.title}</strong>
                    <p>{item.explanation}</p>
                    {citation(item.source_ids)}
                  </li>
                ))}
              </ol>
            </>
          )}
          {result.output.checks?.length > 0 && (
            <>
              <h3>Contrôles recommandés</h3>
              <ol>
                {result.output.checks.map((item, i) => (
                  <li key={i}>
                    <p>{item.instructions}</p>
                    {citation(item.source_ids)}
                  </li>
                ))}
              </ol>
            </>
          )}
          {result.output.missing_information?.length > 0 && (
            <>
              <h3>Informations manquantes</h3>
              <ul>
                {result.output.missing_information.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {result.output.uncertainties?.length > 0 && (
            <>
              <h3>Limites et incertitudes</h3>
              <ul>
                {result.output.uncertainties.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      <div className="diagnostic-sources-heading">
        <h3>
          {result.sources.some((source) => source.available === false)
            ? "Sources de cette analyse"
            : "Sources approuvées"}
        </h3>
        <span>
          {result.sources.length} référence
          {result.sources.length > 1 ? "s" : ""}
        </span>
      </div>
      {result.sources.length ? (
        <div className="diagnostic-sources">
          {result.sources.map((source, index) => {
            const selection = sourceSelection(source);
            const download = safeDocumentUrl(source.download_url || source.url);
            return (
              <article
                key={`${source.id}:${index}`}
                id={`diagnostic-source-${index}`}
                tabIndex={-1}
                className="diagnostic-source"
              >
                <div>
                  <span className="diagnostic-source-number">{index + 1}</span>
                  <div>
                    <h4>{source.title}</h4>
                    <p>
                      {source.available === false
                        ? "Source obsolète · hors des prochaines recherches"
                        : source.kind === "case"
                          ? "Retour d’intervention approuvé"
                          : "Document technique approuvé"}
                      {source.page ? ` · page ${source.page}` : ""}
                      {source.revision ? ` · révision ${source.revision}` : ""}
                    </p>
                  </div>
                </div>
                <blockquote>{source.excerpt}</blockquote>
                {selection ? (
                  <button
                    className="text-button"
                    onClick={() => onSource(selection)}
                  >
                    Consulter la source <ChevronRight size={15} />
                  </button>
                ) : download ? (
                  <a
                    className="text-button"
                    href={`${download}${source.page ? `#page=${source.page}` : ""}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ouvrir le document <Download size={15} />
                  </a>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="diagnostic-no-results">
          Ajoutez puis faites approuver une source correspondant exactement au
          modèle. Aucun diagnostic n’est inventé en son absence.
        </p>
      )}
    </section>
  );
}

function DocumentLibrary({
  user,
  Dialog,
  onSource,
  refreshKey,
  onChanged,
}: {
  user: User;
  Dialog: ComponentType<DialogProps>;
  onSource: (source: SourceSelection) => void;
  refreshKey: number;
  onChanged: () => void;
}) {
  const prefix = useId();
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [rows, setRows] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [upload, setUpload] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const timer = window.setTimeout(
      () => {
        const params = new URLSearchParams();
        if (query.trim()) params.set("q", query.trim());
        if (state) params.set("state", state);
        api<KnowledgeDocument[]>(`knowledge/documents/?${params}`, {
          signal: controller.signal,
        })
          .then((response) => {
            if (!controller.signal.aborted) setRows(response);
          })
          .catch((failure: Error) => {
            if (!controller.signal.aborted) setError(failure.message);
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, state, refreshKey]);
  return (
    <section className="card diagnostic-library">
      <div className="diagnostic-library-heading">
        <div>
          <h2>Bibliothèque technique</h2>
          <p>
            Manuels, schémas et procédures privés, soumis à validation humaine.
          </p>
        </div>
        <button className="button primary" onClick={() => setUpload(true)}>
          <Upload size={17} />
          Ajouter un document
        </button>
      </div>
      <Notice>
        PDF ou TXT, 10 Mio maximum. Le texte extrait peut être recherché après
        approbation. Les documents scannés sans texte restent téléchargeables,
        sans interprétation des images.
      </Notice>
      <div className="diagnostic-toolbar">
        <div className="field">
          <label htmlFor={`${prefix}-search`}>
            Rechercher dans la bibliothèque
          </label>
          <input
            id={`${prefix}-search`}
            className="input"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={200}
            placeholder="Titre, modèle ou référence de carte…"
          />
        </div>
        <div className="field">
          <label htmlFor={`${prefix}-state`}>État des documents</label>
          <select
            id={`${prefix}-state`}
            className="input"
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            <option value="">Tous les états</option>
            <option value="draft">Brouillon</option>
            <option value="approved">Approuvé</option>
            <option value="archived">Archivé</option>
          </select>
        </div>
      </div>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {loading ? (
        <Loading />
      ) : rows.length ? (
        <div className="diagnostic-document-grid">
          {rows.map((document) => (
            <button
              key={document.id}
              className="diagnostic-document-card"
              onClick={() => onSource({ kind: "document", id: document.id })}
            >
              <div className="diagnostic-document-top">
                <span className="diagnostic-document-icon">
                  <FileText size={23} />
                </span>
                <StateBadge state={document.state} />
              </div>
              <h3>{document.title}</h3>
              <p>
                {document.brand} · <strong>{document.model}</strong>
              </p>
              <dl>
                <div>
                  <dt>Type</dt>
                  <dd>{documentKindLabels[document.kind]}</dd>
                </div>
                <div>
                  <dt>Carte / révision</dt>
                  <dd>
                    {[document.board_reference, document.revision]
                      .filter(Boolean)
                      .join(" · ") || "Non renseignées"}
                  </dd>
                </div>
                <div>
                  <dt>Indexation</dt>
                  <dd>
                    {textStatusLabels[document.text_status]} ·{" "}
                    {document.chunk_count} extrait
                    {document.chunk_count > 1 ? "s" : ""}
                  </dd>
                </div>
              </dl>
              <span className="diagnostic-document-footer">
                Consulter le document <ArrowRight size={16} />
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="diagnostic-empty">
          <Library size={29} />
          <h3>Aucun document dans cette sélection</h3>
          <p>Ajoutez une source technique pour constituer la bibliothèque.</p>
        </div>
      )}
      {upload && (
        <Dialog
          title="Ajouter un document technique"
          subtitle="Le document sera enregistré en brouillon."
          onClose={() => setUpload(false)}
          wide
        >
          <DocumentUpload
            onSaved={() => {
              setUpload(false);
              onChanged();
            }}
            onClose={() => setUpload(false)}
          />
        </Dialog>
      )}
    </section>
  );
}

function DocumentUpload({
  onSaved,
  onClose,
}: {
  onSaved: () => void;
  onClose: () => void;
}) {
  const prefix = useId();
  const [file, setFile] = useState<File | null>(null);
  const [values, setValues] = useState({
    title: "",
    brand: "Eaton",
    model: "",
    board_reference: "",
    revision: "",
    kind: "manual",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!file) {
      setError("Choisissez un fichier PDF ou TXT.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("Le fichier dépasse la limite de 10 Mio.");
      return;
    }
    if (!/\.(pdf|txt)$/i.test(file.name)) {
      setError("Seuls les fichiers PDF et TXT sont acceptés.");
      return;
    }
    const body = new FormData();
    body.set("file", file);
    Object.entries(values).forEach(([key, value]) =>
      body.set(key, value.trim()),
    );
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    try {
      await api("knowledge/documents/", {
        method: "POST",
        body,
        signal: request.signal,
      });
      if (!request.signal.aborted) onSaved();
    } catch (failure) {
      if (!request.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }
  return (
    <form onSubmit={(event) => void submit(event)}>
      <div className="diagnostic-modal-body">
        <div className="form-grid">
          <div className="field full">
            <label htmlFor={`${prefix}-file`}>Fichier PDF ou TXT</label>
            <input
              id={`${prefix}-file`}
              className="input diagnostic-file-input"
              type="file"
              accept=".pdf,.txt,application/pdf,text/plain"
              required
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            <small>
              10 Mio maximum. Un PDF image sans texte ne sera pas indexé.
            </small>
          </div>
          {[
            ["title", "Titre du document", 200],
            ["brand", "Marque du document", 100],
            ["model", "Modèle du document", 120],
            ["board_reference", "Référence de carte", 120],
            ["revision", "Révision", 80],
          ].map(([key, label, max]) => (
            <div
              className={`field ${key === "title" ? "full" : ""}`}
              key={String(key)}
            >
              <label htmlFor={`${prefix}-${key}`}>{String(label)}</label>
              <input
                id={`${prefix}-${key}`}
                className="input"
                value={values[key as keyof typeof values]}
                onChange={(event) =>
                  setValues((old) => ({
                    ...old,
                    [String(key)]: event.target.value,
                  }))
                }
                required={["title", "brand", "model"].includes(String(key))}
                maxLength={Number(max)}
              />
            </div>
          ))}
          <div className="field">
            <label htmlFor={`${prefix}-kind`}>Type de document</label>
            <select
              id={`${prefix}-kind`}
              className="input"
              value={values.kind}
              onChange={(event) =>
                setValues((old) => ({ ...old, kind: event.target.value }))
              }
            >
              {Object.entries(documentKindLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <Notice>
          Importez des documents techniques autorisés. Évitez les données
          clients, numéros de série et informations confidentielles inutiles à
          une procédure générique.
        </Notice>
        {error && <ErrorMessage>{error}</ErrorMessage>}
      </div>
      <div className="modal-footer">
        <button type="button" className="button secondary" onClick={onClose}>
          Annuler
        </button>
        <button className="button primary" disabled={busy}>
          {busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <Upload size={17} />
          )}
          Enregistrer le brouillon
        </button>
      </div>
    </form>
  );
}

function CaseLibrary({
  user,
  interventions,
  equipment,
  requests,
  Dialog,
  initialInterventionId,
  onSource,
  refreshKey,
  onChanged,
}: Props & {
  onSource: (source: SourceSelection) => void;
  refreshKey: number;
  onChanged: () => void;
}) {
  const prefix = useId();
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [rows, setRows] = useState<KnowledgeCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [create, setCreate] = useState(false);
  const eligible = interventions.filter(
    (item) =>
      item.status === "completed" &&
      (user.role !== "technician" || item.technician === user.id),
  );
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const timer = window.setTimeout(
      () => {
        const params = new URLSearchParams();
        if (query.trim()) params.set("q", query.trim());
        if (state) params.set("state", state);
        api<KnowledgeCase[]>(`knowledge/cases/?${params}`, {
          signal: controller.signal,
        })
          .then((response) => {
            if (!controller.signal.aborted) setRows(response);
          })
          .catch((failure: Error) => {
            if (!controller.signal.aborted) setError(failure.message);
          })
          .finally(() => {
            if (!controller.signal.aborted) setLoading(false);
          });
      },
      query ? 200 : 0,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, state, refreshKey]);
  return (
    <section className="card diagnostic-library">
      <div className="diagnostic-library-heading">
        <div>
          <h2>Retours d’expérience</h2>
          <p>
            Des réparations documentées, proposées après une intervention
            terminée.
          </p>
        </div>
        <button className="button primary" onClick={() => setCreate(true)}>
          <Plus size={17} />
          Proposer un retour
        </button>
      </div>
      <Notice>
        Une contribution reste en brouillon jusqu’à son approbation par un
        responsable. Renseignez des faits techniques, sans identité ni
        coordonnées de client.
      </Notice>
      <div className="diagnostic-toolbar">
        <div className="field">
          <label htmlFor={`${prefix}-search`}>
            Rechercher dans les retours
          </label>
          <input
            id={`${prefix}-search`}
            className="input"
            type="search"
            maxLength={200}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Modèle, panne ou réparation…"
          />
        </div>
        <div className="field">
          <label htmlFor={`${prefix}-state`}>État des retours</label>
          <select
            id={`${prefix}-state`}
            className="input"
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            <option value="">Tous les états</option>
            <option value="draft">Brouillon</option>
            <option value="approved">Approuvé</option>
            <option value="archived">Archivé</option>
          </select>
        </div>
      </div>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {loading ? (
        <Loading />
      ) : rows.length ? (
        <div className="diagnostic-case-list">
          {rows.map((item) => (
            <button
              key={item.id}
              className="diagnostic-case-row"
              onClick={() => onSource({ kind: "case", id: item.id })}
            >
              <div>
                <StateBadge state={item.state} />
                <h3>
                  {item.brand} · {item.model}
                </h3>
                <p>{item.symptoms}</p>
                <small>
                  {item.source_intervention_reference} · proposé le{" "}
                  {dateFR(item.created_at)}
                </small>
              </div>
              <ChevronRight size={19} />
            </button>
          ))}
        </div>
      ) : (
        <div className="diagnostic-empty">
          <CheckCircle2 size={29} />
          <h3>Aucun retour dans cette sélection</h3>
          <p>
            Documentez une intervention terminée pour enrichir les diagnostics
            futurs.
          </p>
        </div>
      )}
      {create && (
        <Dialog
          title="Proposer un retour d’intervention"
          subtitle="Une validation humaine sera nécessaire avant sa réutilisation."
          onClose={() => setCreate(false)}
          wide
        >
          <CaseContribution
            interventions={eligible}
            equipment={equipment}
            requests={requests}
            initialInterventionId={initialInterventionId}
            onClose={() => setCreate(false)}
            onSaved={() => {
              setCreate(false);
              onChanged();
            }}
          />
        </Dialog>
      )}
    </section>
  );
}

function CaseContribution({
  interventions,
  equipment,
  requests,
  initialInterventionId,
  onSaved,
  onClose,
}: Pick<
  Props,
  "interventions" | "equipment" | "requests" | "initialInterventionId"
> & { onSaved: () => void; onClose: () => void }) {
  const prefix = useId();
  const [interventionId, setInterventionId] = useState(
    interventions.some((item) => item.id === initialInterventionId)
      ? String(initialInterventionId)
      : "",
  );
  const [values, setValues] = useState({
    symptoms: "",
    fault_code: "",
    measurements: "",
    confirmed_cause: "",
    repair: "",
    outcome: "",
    board_reference: "",
    revision: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const selected = interventions.find(
    (item) => String(item.id) === interventionId,
  );
  const request = requests.find(
    (item) => item.id === selected?.service_request,
  );
  const unit = equipment.find((item) => item.id === request?.equipment);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setError("");
    try {
      await api("knowledge/cases/", {
        method: "POST",
        body: JSON.stringify({
          intervention: Number(interventionId),
          ...Object.fromEntries(
            Object.entries(values).map(([key, value]) => [key, value.trim()]),
          ),
        }),
        signal: request.signal,
      });
      if (!request.signal.aborted) onSaved();
    } catch (failure) {
      if (!request.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }
  return (
    <form onSubmit={(event) => void submit(event)}>
      <div className="diagnostic-modal-body">
        <div className="form-grid">
          <div className="field full">
            <label htmlFor={`${prefix}-intervention`}>
              Intervention terminée
            </label>
            <select
              id={`${prefix}-intervention`}
              className="input"
              value={interventionId}
              onChange={(event) => setInterventionId(event.target.value)}
              required
            >
              <option value="">Choisir une intervention terminée…</option>
              {interventions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.reference} ·{" "}
                  {item.equipment_model || "Modèle non renseigné"}
                </option>
              ))}
            </select>
            <small>
              Un technicien peut proposer uniquement ses propres interventions
              terminées.
            </small>
          </div>
          {selected && (
            <div className="diagnostic-model-authority full">
              <ShieldCheck size={18} />
              <span>
                Modèle issu de l’intervention :{" "}
                <strong>
                  {unit?.brand || ""}{" "}
                  {selected.equipment_model || unit?.model || "Non renseigné"}
                </strong>
                . Aucun diagnostic ou renseignement client n’est recopié.
              </span>
            </div>
          )}
          {[
            ["symptoms", "Symptômes constatés", 6000, true],
            ["fault_code", "Code défaut du retour", 120, false],
            ["measurements", "Mesures effectuées", 6000, false],
            ["confirmed_cause", "Cause confirmée", 6000, true],
            ["repair", "Réparation effectuée", 6000, true],
            ["outcome", "Résultat", 4000, true],
            ["board_reference", "Référence de carte du retour", 120, false],
            ["revision", "Révision de carte du retour", 80, false],
          ].map(([key, label, max, required]) => (
            <div key={String(key)} className="field full">
              <label htmlFor={`${prefix}-${key}`}>{String(label)}</label>
              {Number(max) > 120 ? (
                <textarea
                  id={`${prefix}-${key}`}
                  className="input"
                  rows={3}
                  maxLength={Number(max)}
                  required={Boolean(required)}
                  value={values[key as keyof typeof values]}
                  onChange={(event) =>
                    setValues((old) => ({
                      ...old,
                      [String(key)]: event.target.value,
                    }))
                  }
                />
              ) : (
                <input
                  id={`${prefix}-${key}`}
                  className="input"
                  maxLength={Number(max)}
                  value={values[key as keyof typeof values]}
                  onChange={(event) =>
                    setValues((old) => ({
                      ...old,
                      [String(key)]: event.target.value,
                    }))
                  }
                />
              )}
            </div>
          ))}
        </div>
        {!interventions.length && (
          <Notice>
            Aucune intervention terminée éligible. Terminez et documentez une
            intervention avant de proposer un retour.
          </Notice>
        )}
        {error && <ErrorMessage>{error}</ErrorMessage>}
      </div>
      <div className="modal-footer">
        <button type="button" className="button secondary" onClick={onClose}>
          Annuler
        </button>
        <button className="button primary" disabled={busy || !interventionId}>
          {busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <Plus size={17} />
          )}
          Enregistrer le retour brouillon
        </button>
      </div>
    </form>
  );
}

function KnowledgeDetail({
  selection,
  user,
  Dialog,
  onClose,
  onChanged,
}: {
  selection: SourceSelection;
  user: User;
  Dialog: ComponentType<DialogProps>;
  onClose: () => void;
  onChanged: () => void;
}) {
  type DocumentDetail = KnowledgeDocument & {
    chunks?: {
      id: number;
      page: number;
      ordinal: number;
      text: string;
      source_id: string;
    }[];
  };
  const [record, setRecord] = useState<DocumentDetail | KnowledgeCase | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [reload, setReload] = useState(0);
  const action = useRef<AbortController | null>(null);
  const path = `knowledge/${selection.kind === "document" ? "documents" : "cases"}/${selection.id}/`;
  const canManage = user.role === "admin" || user.role === "manager";
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<DocumentDetail | KnowledgeCase>(path, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) setRecord(response);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, reload]);
  useEffect(() => () => action.current?.abort(), []);
  async function update(mode: "approve" | "archive") {
    const controller = new AbortController();
    action.current = controller;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`${path}${mode}/`, {
        method: "POST",
        body: "{}",
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setNotice(
          mode === "approve"
            ? "Source approuvée. Elle peut être utilisée par la recherche technique."
            : "Source archivée. Elle est retirée des prochaines recherches.",
        );
        setReload((value) => value + 1);
        setConfirmArchive(false);
        onChanged();
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  const document =
    selection.kind === "document" ? (record as DocumentDetail | null) : null;
  const technicalCase =
    selection.kind === "case" ? (record as KnowledgeCase | null) : null;
  const download =
    safeDocumentUrl(document?.download_url) ||
    (document
      ? `/api/knowledge/documents/${document.id}/download/`
      : undefined);
  return (
    <Dialog
      title={
        document?.title ||
        (technicalCase
          ? `Retour technique · ${technicalCase.model}`
          : "Consulter la source")
      }
      subtitle="Source privée · bibliothèque technique TVM"
      onClose={onClose}
      wide
    >
      <div className="diagnostic-modal-body">
        {loading ? (
          <Loading />
        ) : (
          record && (
            <>
              <div className="diagnostic-detail-meta">
                <StateBadge state={record.state} />
                <strong>
                  {record.brand} · {record.model}
                </strong>
                {record.board_reference && (
                  <span>Carte : {record.board_reference}</span>
                )}
                {record.revision && <span>Révision : {record.revision}</span>}
              </div>
              <p className="diagnostic-detail-origin">
                Ajouté le {dateFR(record.created_at, true)} par{" "}
                {record.created_by_name || "l’équipe TVM"}
                {record.approved_at
                  ? ` · approuvé le ${dateFR(record.approved_at, true)} par ${record.approved_by_name || "un responsable"}`
                  : ""}
              </p>
              <WarningList values={record.warnings} />
              {document && (
                <>
                  <dl className="diagnostic-document-facts">
                    <div>
                      <dt>Fichier</dt>
                      <dd>{document.original_name}</dd>
                    </div>
                    <div>
                      <dt>Type</dt>
                      <dd>{documentKindLabels[document.kind]}</dd>
                    </div>
                    <div>
                      <dt>Texte</dt>
                      <dd>{textStatusLabels[document.text_status]}</dd>
                    </div>
                    <div>
                      <dt>Pages / extraits</dt>
                      <dd>
                        {document.pages} / {document.chunk_count}
                      </dd>
                    </div>
                  </dl>
                  <h3>Texte extrait</h3>
                  {document.chunks?.length ? (
                    <div className="diagnostic-extracted-text">
                      {document.chunks.map((chunk) => (
                        <article key={chunk.id}>
                          <strong>
                            Page {chunk.page} · extrait {chunk.ordinal}
                          </strong>
                          <pre>{chunk.text}</pre>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <Notice>
                      Aucun texte indexable disponible. Consultez le fichier
                      original ; les images et schémas ne sont pas interprétés
                      par l’assistant.
                    </Notice>
                  )}
                </>
              )}
              {technicalCase && (
                <div className="diagnostic-case-detail">
                  <p className="diagnostic-case-reference">
                    Réf. de visite source :{" "}
                    {technicalCase.source_intervention_reference}
                  </p>
                  {[
                    ["Symptômes constatés", technicalCase.symptoms],
                    ["Code défaut", technicalCase.fault_code],
                    ["Mesures effectuées", technicalCase.measurements],
                    ["Cause confirmée", technicalCase.confirmed_cause],
                    ["Réparation effectuée", technicalCase.repair],
                    ["Résultat", technicalCase.outcome],
                  ].map(([label, text]) =>
                    text ? (
                      <section key={label}>
                        <h3>{label}</h3>
                        <p>{text}</p>
                      </section>
                    ) : null,
                  )}
                  {technicalCase.state === "approved" &&
                    !technicalCase.eligible_for_retrieval && (
                      <Notice>
                        Ce retour est approuvé mais n’est pas éligible à la
                        recherche. Consultez les avertissements de la source.
                      </Notice>
                    )}
                </div>
              )}
              {confirmArchive && (
                <div className="diagnostic-archive-confirm">
                  <p>
                    Archiver cette source la retire des recherches futures. Les
                    analyses déjà enregistrées gardent leur traçabilité.
                  </p>
                  <button
                    className="button secondary"
                    onClick={() => setConfirmArchive(false)}
                    disabled={busy}
                  >
                    Conserver la source
                  </button>
                  <button
                    className="button danger"
                    onClick={() => void update("archive")}
                    disabled={busy}
                  >
                    Confirmer l’archivage
                  </button>
                </div>
              )}
            </>
          )
        )}
        {error && <ErrorMessage>{error}</ErrorMessage>}
        {notice && (
          <div className="success-box" role="status">
            <CheckCircle2 size={17} />
            {notice}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose}>
          Fermer
        </button>
        {download && (
          <a
            className="button secondary"
            href={download}
            target="_blank"
            rel="noreferrer"
          >
            <Download size={17} />
            Télécharger le document
          </a>
        )}
        {record && canManage && record.state === "draft" && (
          <button
            className="button primary"
            onClick={() => void update("approve")}
            disabled={busy}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <CheckCircle2 size={17} />
            )}
            Approuver la source
          </button>
        )}
        {record &&
          canManage &&
          record.state !== "archived" &&
          !confirmArchive && (
            <button
              className="button secondary"
              onClick={() => setConfirmArchive(true)}
              disabled={busy}
            >
              <Archive size={17} />
              Archiver la source
            </button>
          )}
      </div>
    </Dialog>
  );
}

function DiagnosticHistory({
  Dialog,
  onSource,
}: {
  Dialog: ComponentType<DialogProps>;
  onSource: (source: SourceSelection) => void;
}) {
  const [rows, setRows] = useState<DiagnosticResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<DiagnosticResult | null>(null);
  const [detailError, setDetailError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<{ results: DiagnosticResult[] }>("diagnostics/runs/", {
      signal: controller.signal,
    })
      .then((response) => {
        if (!controller.signal.aborted) setRows(response.results);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (selectedId === null) return;
    const controller = new AbortController();
    setDetail(null);
    setDetailError("");
    api<DiagnosticResult>(`diagnostics/runs/${selectedId}/`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!controller.signal.aborted) setDetail(response);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setDetailError(failure.message);
      });
    return () => controller.abort();
  }, [selectedId]);
  return (
    <section className="card diagnostic-library">
      <div className="diagnostic-library-heading">
        <div>
          <h2>Historique des analyses</h2>
          <p>
            Analyses enregistrées sur le serveur, dans le périmètre de votre
            compte.
          </p>
        </div>
      </div>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {loading ? (
        <Loading />
      ) : rows.length ? (
        <div className="diagnostic-history-list">
          {rows.map((run) => (
            <button
              key={run.id}
              className="diagnostic-history-row"
              onClick={() => setSelectedId(run.id || null)}
            >
              <span className="diagnostic-document-icon">
                <History size={20} />
              </span>
              <div>
                <h3>
                  {run.input?.brand} {run.input?.model || "Analyse technique"}
                </h3>
                <p>{resultLabels[run.status] || run.status}</p>
                <small>
                  {run.created_at
                    ? dateFR(run.created_at, true)
                    : "Date non disponible"}{" "}
                  · {run.sources?.length || 0} source
                  {run.sources?.length > 1 ? "s" : ""}
                </small>
              </div>
              <ChevronRight size={18} />
            </button>
          ))}
        </div>
      ) : (
        <div className="diagnostic-empty">
          <History size={29} />
          <h3>Aucune analyse enregistrée</h3>
          <p>
            Les recherches documentaires seules ne déclenchent pas le
            fournisseur IA.
          </p>
        </div>
      )}
      {selectedId !== null && (
        <Dialog
          title="Analyse technique enregistrée"
          subtitle={
            detail?.created_at ? dateFR(detail.created_at, true) : undefined
          }
          onClose={() => setSelectedId(null)}
          wide
        >
          <div className="diagnostic-modal-body">
            {detailError ? (
              <ErrorMessage>{detailError}</ErrorMessage>
            ) : !detail ? (
              <Loading />
            ) : (
              <>
                <dl className="diagnostic-history-input">
                  <div>
                    <dt>Marque / modèle</dt>
                    <dd>
                      {detail.input?.brand} {detail.input?.model}
                    </dd>
                  </div>
                  <div>
                    <dt>Symptômes saisis</dt>
                    <dd>{detail.input?.symptoms || "Non renseignés"}</dd>
                  </div>
                  {detail.input?.fault_code && (
                    <div>
                      <dt>Code défaut</dt>
                      <dd>{detail.input.fault_code}</dd>
                    </div>
                  )}
                  {detail.input?.measurements && (
                    <div>
                      <dt>Mesures saisies</dt>
                      <dd>{detail.input.measurements}</dd>
                    </div>
                  )}
                </dl>
                <DiagnosticResultView
                  result={detail}
                  onSource={(source) => {
                    setSelectedId(null);
                    onSource(source);
                  }}
                />
              </>
            )}
          </div>
          <div className="modal-footer">
            <button
              className="button secondary"
              onClick={() => setSelectedId(null)}
            >
              Fermer
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
