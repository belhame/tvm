import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  BookOpen,
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Box,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Menu,
  MoreHorizontal,
  Package,
  Pencil,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Wrench,
  X,
  Zap,
  ScanLine,
  PlugZap,
  AlertCircle,
  Building2,
  CircleDot,
  LockKeyhole,
  Eye,
  Server,
  CheckCheck,
  Truck,
} from "lucide-react";
import {
  api,
  dateFR,
  initials,
  listResult,
  money,
  setCsrf,
  type RecordData,
  type User,
} from "./api";
import {
  resources,
  statuses,
  optionLabel,
  requestCategories,
  requestStatusLabels,
  interventionKinds,
  type Column,
  type Resource,
} from "./resources";
import Scanner from "./Scanner";
import SerialAnalysis from "./SerialAnalysis";
import Integrations from "./Integrations";
import EatonCatalogue from "./EatonCatalogue";
import CatalogueModelPicker from "./CatalogueModelPicker";
import RequestIntake from "./RequestIntake";
import RequestsWorkspace, {
  type RequestCategoryCount,
} from "./RequestsWorkspace";
import RequestDossier from "./RequestDossier";
import OperationTimeline from "./OperationTimeline";
import InterventionWorksheet from "./InterventionWorksheet";
import RequestReceptionFields from "./RequestReceptionFields";
import CallReference, { callIdentity, callPrimary } from "./CallReference";
import ClientsDirectory from "./ClientsDirectory";
import PreventiveProgress from "./PreventiveProgress";
import ExchangeWorkspace from "./ExchangeWorkspace";
import DispatchWorkspace from "./DispatchWorkspace";

type DataMap = Record<string, RecordData[]>;
type ModalState = {
  resource: string;
  record?: RecordData;
  values?: RecordData;
  readonly?: boolean;
};
const roleNames = {
  admin: "Administrateur",
  manager: "Responsable SAV",
  technician: "Technicien SAV",
  client: "Portail client",
};
const navGroups = [
  {
    label: "ESPACE DE TRAVAIL",
    items: [
      { id: "dashboard", label: "Tableau de bord", icon: LayoutDashboard },
      { id: "interventions", label: "Interventions", icon: Wrench },
      { id: "clients", label: "Clients", icon: Users },
      { id: "equipment", label: "Équipements", icon: Zap },
      { id: "requests", label: "Demandes SAV", icon: ClipboardList },
      { id: "exchange", label: "Échange", icon: Truck },
      {
        id: "exchange-billing",
        label: "Échanges à facturer",
        icon: FileCheck2,
      },
      { id: "commissioning", label: "Mise en service", icon: CheckCircle2 },
      { id: "preventive", label: "Préventive", icon: ShieldCheck },
      { id: "planning", label: "Planning", icon: CalendarDays },
      { id: "dispatch", label: "Livraisons & retours", icon: Truck },
      {
        id: "diagnostic-billing",
        label: "Diagnostics à facturer",
        icon: FileText,
      },
    ],
  },
  {
    label: "GESTION & SUIVI",
    items: [
      { id: "contracts", label: "Contrats & garanties", icon: ShieldCheck },
      { id: "stock", label: "Pièces & stock", icon: Package },
      { id: "delivery-notes", label: "Bons de livraison", icon: Truck },
      { id: "reports", label: "Rapports", icon: FileText },
      { id: "catalogue", label: "Catalogue Eaton", icon: BookOpen },
    ],
  },
  {
    label: "OUTILS",
    items: [
      { id: "scanner", label: "Scanner un équipement", icon: ScanLine },
      { id: "integrations", label: "WhatsApp & assistant IA", icon: PlugZap },
      { id: "users", label: "Comptes & accès", icon: Settings2 },
    ],
  },
];
const clientPages = new Set([
  "dashboard",
  "interventions",
  "equipment",
  "requests",
  "exchange",
  "dispatch",
  "contracts",
  "delivery-notes",
  "reports",
  "scanner",
]);
const operationFormSections: Record<string, string> = {
  kind: "Dossier et type d’opération",
  technician: "Planification et réalisation",
  contract: "Contrat et couverture",
  cabinet_serial: "Matériel et contact sur site",
  diagnosis: "Constats et travaux",
  conclusion: "Conclusion de la fiche",
};

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? "compact" : ""}`}>
      <span className="brand-symbol">
        <Zap fill="currentColor" strokeWidth={1.8} />
      </span>
      <div>
        <strong>
          Power<span>Care</span>
        </strong>
        <small>TVM · UPS Service Suite</small>
      </div>
    </div>
  );
}
function Badge({ value, label }: { value: any; label?: string }) {
  const key = String(value);
  return (
    <span className={`badge status-${key}`}>
      <span className="badge-dot" />
      {label || statuses[key] || key || "—"}
    </span>
  );
}
function canManage(user: User, resource: string, record?: RecordData) {
  if (user.role === "admin") return true;
  if (user.role === "manager") return resource !== "users";
  if (user.role === "technician")
    return resource === "requests"
      ? !record
      : resource === "interventions" &&
          (!record || record.technician === user.id);
  return false;
}
function Spinner() {
  return <LoaderCircle className="spin" size={18} />;
}
function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={18} />
      <span>{children}</span>
    </div>
  );
}
function Empty({
  title = "Aucun résultat",
  text = "Les éléments enregistrés apparaîtront ici.",
  action,
}: {
  title?: string;
  text?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <ClipboardList size={28} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const items = ref.current?.querySelectorAll<HTMLElement>(
          "button,input,select,textarea,a[href]",
        );
        if (!items?.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.body.style.overflow = old;
      document.removeEventListener("keydown", handler);
    };
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal ${wide ? "modal-wide" : ""}`}
      >
        <div className="modal-heading">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Fermer">
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (user: User, demo: boolean) => void }) {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      const session = await api("session/");
      setCsrf(session.csrfToken);
      onLogin(session.user, session.demo_mode);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story">
        <Logo />
        <div className="login-kicker">
          <span /> MAINTENANCE & SERVICE APRÈS-VENTE
        </div>
        <h1>
          La performance
          <br />
          de vos onduleurs.
          <br />
          <span>La sérénité en plus.</span>
        </h1>
        <p>
          Un espace partagé pour vos équipements, votre équipe et chaque étape
          du service client.
        </p>
        <div className="login-feature">
          <ShieldCheck /> Des accès sécurisés pour chaque rôle
        </div>
        <div className="login-feature">
          <Users /> Votre équipe et vos clients, connectés
        </div>
        <div className="login-feature">
          <FileCheck2 /> Un suivi complet, du signalement au rapport
        </div>
        <div className="login-illustration">
          <div className="ups-cabinet">
            <div className="ups-display">
              <Zap size={22} />
              <span>
                POWER<span>CARE</span>
              </span>
            </div>
            {[1, 2, 3, 4].map((n) => (
              <div key={n} className="ups-unit">
                <span />
                <i />
                <i />
                <i />
              </div>
            ))}
            <div className="ups-foot" />
          </div>
          <div className="signal-card">
            <div>
              <CheckCircle2 size={19} />
              <strong>Chaque intervention compte.</strong>
            </div>
            <p>Centralisez. Planifiez. Résolvez.</p>
          </div>
        </div>
        <div className="login-bottom">
          PowerCare by TVM <span>Votre énergie, notre engagement.</span>
        </div>
      </section>
      <section className="login-form-panel">
        <div className="login-form-box">
          <div className="login-lock">
            <LockKeyhole size={28} />
          </div>
          <h2>Bienvenue sur PowerCare</h2>
          <p>Connectez-vous à votre espace de travail.</p>
          <form onSubmit={submit}>
            {error && <ErrorBox>{error}</ErrorBox>}
            <label>
              Identifiant
              <input
                className="input"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Votre identifiant"
                autoFocus
              />
            </label>
            <label>
              Mot de passe
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Votre mot de passe"
              />
            </label>
            <button className="button primary login-submit" disabled={busy}>
              {busy ? (
                <Spinner />
              ) : (
                <>
                  Se connecter <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <div className="secure-note">
            <ShieldCheck size={16} /> Accès réservé aux utilisateurs autorisés
          </div>
          <div className="login-assistance">
            <CircleHelp size={17} />
            <span>
              Besoin d’un compte ? Contactez votre administrateur TVM.
            </span>
          </div>
        </div>
        <footer>
          © {new Date().getFullYear()} TVM · PowerCare{" "}
          <span>Gestion SAV des onduleurs</span>
        </footer>
      </section>
    </main>
  );
}

function EditForm({
  modal,
  data,
  user,
  onClose,
  onSaved,
}: {
  modal: ModalState;
  data: DataMap;
  user: User;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const formId = useId();
  const config = resources[modal.resource],
    editing = Boolean(modal.record),
    readonly = modal.readonly;
  const [values, setValues] = useState<RecordData>(() =>
    Object.fromEntries(
      config.fields.map((field) => {
        let val =
          modal.record?.[field.name] ??
          modal.values?.[field.name] ??
          (field.name === "technician" && user.role === "technician"
            ? user.id
            : undefined) ??
          field.default ??
          "";
        if (field.type === "datetime-local" && val) {
          const date = new Date(val);
          val = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
            .toISOString()
            .slice(0, 16);
        }
        if (typeof val === "boolean") val = String(val);
        return [field.name, val];
      }),
    ),
  );
  const originalValues = useRef(values);
  const [lines, setLines] = useState<RecordData[]>(
    modal.record?.lines?.map((x: RecordData) => ({
      part: x.part || "",
      description: x.description,
      quantity: x.quantity,
    })) || [{ part: "", description: "", quantity: 1 }],
  );
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [structuredData, setStructuredData] = useState<RecordData>(
    modal.record?.structured_data || {},
  );
  const [equipmentSection, setEquipmentSection] = useState("record");
  const sourceRequest = data.requests?.find(
    (row) => row.id === Number(values.service_request),
  );
  const sourceEquipment = data.equipment?.find(
    (row) => row.id === sourceRequest?.equipment,
  );
  const equipmentRequests = (data.requests || []).filter(
    (row) => row.equipment === modal.record?.id,
  );
  const equipmentRequestIds = new Set(equipmentRequests.map((row) => row.id));
  const canWriteEquipmentTimeline =
    user.role === "admin" ||
    user.role === "manager" ||
    (user.role === "technician" &&
      (equipmentRequests.some((row) => row.assigned_technician === user.id) ||
        (data.interventions || []).some(
          (row) =>
            equipmentRequestIds.has(row.service_request) &&
            row.technician === user.id,
        )));
  const canBackfillClosure =
    modal.resource === "requests" &&
    modal.record?.status === "closed" &&
    values.status === "closed" &&
    !modal.record.closed_at &&
    (user.role === "admin" || user.role === "manager");
  function updateField(name: string, entry: string | boolean) {
    setValues((previous) => ({
      ...previous,
      [name]: entry,
      ...(modal.resource === "users" && name === "role" && entry === "client"
        ? { can_validate_billing: "false" }
        : {}),
      ...(modal.resource === "interventions" && name === "service_request"
        ? { replacement_equipment: "", contract: "", extension_warranty: "" }
        : {}),
      ...(modal.resource === "interventions" &&
      name === "kind" &&
      entry !== "exchange"
        ? { replacement_equipment: "" }
        : {}),
    }));
  }
  function allowedOptions(name: string, resource: string) {
    return (data[resource] || []).filter((row) => {
      if (
        resource === "users" &&
        !["technician", "manager", "admin"].includes(row.role)
      )
        return false;
      if (
        resource === "equipment" &&
        name === "equipment" &&
        values.client &&
        Number(row.client) !== Number(values.client)
      )
        return false;
      if (modal.resource !== "interventions") return true;
      if (resource === "requests" && user.role === "technician")
        return (
          row.assigned_technician === user.id ||
          (data.interventions || []).some(
            (entry) =>
              entry.service_request === row.id && entry.technician === user.id,
          )
        );
      if (name === "replacement_equipment")
        return (
          sourceEquipment &&
          row.client === sourceEquipment.client &&
          row.id !== sourceEquipment.id
        );
      if (name === "contract")
        return (
          sourceEquipment &&
          row.client === sourceEquipment.client &&
          (!row.equipment || row.equipment === sourceEquipment.id)
        );
      if (name === "extension_warranty")
        return sourceEquipment && row.equipment === sourceEquipment.id;
      return true;
    });
  }
  if (modal.resource === "requests" && !editing && !readonly) {
    return (
      <Modal
        title={config.button}
        subtitle="Retrouvez le modèle, la garantie et l’historique depuis le numéro de série."
        onClose={onClose}
        wide
      >
        <RequestIntake
          user={user}
          equipment={data.equipment || []}
          clients={data.clients || []}
          initialEquipmentId={modal.values?.equipment}
          onSaved={onSaved}
          onClose={onClose}
        />
      </Modal>
    );
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const payload: RecordData = {};
      for (const field of config.fields) {
        if (
          field.managerOnly &&
          user.role !== "admin" &&
          user.role !== "manager"
        )
          continue;
        let value = values[field.name];
        if (field.name === "password" && !value) continue;
        if (field.name === "closed_at" && (!canBackfillClosure || !value))
          continue;
        if (field.type === "select" && field.resource)
          value = value === "" ? null : Number(value);
        else if (field.type === "number")
          value = value === "" ? (field.default ?? null) : Number(value);
        else if (field.type === "datetime-local")
          value =
            value &&
            modal.record?.[field.name] &&
            value === originalValues.current[field.name]
              ? modal.record[field.name]
              : value
                ? new Date(value).toISOString()
                : null;
        else if (field.type === "date") value = value || null;
        else if (
          ["is_active", "return_flag", "can_validate_billing"].includes(
            field.name,
          )
        )
          value = value === true || value === "true";
        payload[field.name] = value;
      }
      if (modal.resource === "interventions") {
        payload.structured_data = structuredData;
        if (payload.kind !== "exchange") payload.replacement_equipment = null;
      }
      if (modal.resource === "stock-movements") {
        if (payload.kind === "out")
          payload.quantity = -Math.abs(payload.quantity);
        else if (payload.kind === "in")
          payload.quantity = Math.abs(payload.quantity);
      }
      if (modal.resource === "users" && payload.role !== "client")
        payload.client = null;
      if (modal.resource === "users" && payload.role === "client")
        payload.can_validate_billing = false;
      if (modal.resource === "delivery-notes")
        payload.lines = lines
          .filter((l) => l.description.trim())
          .map((l) => ({
            part: l.part ? Number(l.part) : null,
            description: l.description,
            quantity: Number(l.quantity),
          }));
      await api(`${modal.resource}/${editing ? `${modal.record!.id}/` : ""}`, {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      await onSaved();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        readonly
          ? `Consulter ${config.singular}`
          : editing
            ? `Modifier ${config.singular}`
            : config.button
      }
      subtitle={
        modal.record && ["requests", "interventions"].includes(modal.resource)
          ? `${user.role === "client" ? callPrimary(modal.record, user.role, modal.resource === "interventions") : `N° d’appel TVM ${callIdentity(modal.record, modal.resource === "interventions").tvm || "non renseigné"}`}${modal.resource === "interventions" ? ` · Référence de visite ${modal.record.reference}` : ""}`
          : modal.record?.reference ||
            "Les données sont enregistrées dans la base partagée."
      }
      onClose={onClose}
      wide
    >
      {modal.resource === "equipment" && editing && (
        <div className="page-tabs" role="group" aria-label="Fiche équipement">
          <button
            type="button"
            aria-pressed={equipmentSection === "record"}
            className={equipmentSection === "record" ? "active" : ""}
            onClick={() => setEquipmentSection("record")}
          >
            Matériel
          </button>
          <button
            type="button"
            aria-pressed={equipmentSection === "timeline"}
            className={equipmentSection === "timeline" ? "active" : ""}
            onClick={() => setEquipmentSection("timeline")}
          >
            Historique des opérations
          </button>
        </div>
      )}
      {modal.resource === "equipment" &&
      editing &&
      equipmentSection === "timeline" ? (
        <div className="modal-content">
          <OperationTimeline
            equipmentId={modal.record!.id}
            user={user}
            canWrite={canWriteEquipmentTimeline}
            onChanged={onSaved}
          />
        </div>
      ) : (
        <form onSubmit={submit}>
          <div className="modal-content">
            {error && <ErrorBox>{error}</ErrorBox>}
            {modal.resource === "interventions" &&
              ["preventive", "commissioning"].includes(values.kind) && (
                <div className="operation-form-intro">
                  <span className="operation-form-icon">
                    {values.kind === "preventive" ? (
                      <ShieldCheck size={23} />
                    ) : (
                      <PlugZap size={23} />
                    )}
                  </span>
                  <div>
                    <strong>
                      {values.kind === "preventive"
                        ? "Une visite préventive, rattachée à son dossier SAV"
                        : "Une mise en service documentée, de l’installation aux essais"}
                    </strong>
                    <p>
                      {values.kind === "preventive"
                        ? "Planifiez chaque visite séparément. Terminer la fiche met à jour la progression du dossier ; les contrôles cochés et le compte rendu restent propres à cette visite."
                        : "Renseignez le site, le matériel et le contact, puis les contrôles réalisés. Pour terminer la fiche, indiquez la date réelle de l’opération."}
                    </p>
                  </div>
                </div>
              )}
            {modal.resource === "requests" && editing && (
              <PreventiveProgress record={modal.record!} />
            )}
            {modal.resource === "interventions" &&
              values.kind === "preventive" &&
              sourceRequest && <PreventiveProgress record={sourceRequest} />}
            <div className="form-grid">
              {config.fields
                .filter(
                  (field) =>
                    field.section !== "reception" &&
                    (!readonly || field.name !== "password") &&
                    (!field.managerOnly ||
                      user.role === "admin" ||
                      user.role === "manager") &&
                    (user.role !== "client" ||
                      (field.name !== "internal_notes" &&
                        !(
                          modal.resource === "clients" && field.name === "notes"
                        ))) &&
                    (!field.when ||
                      values[field.when.field] === field.when.value),
                )
                .map((field) => (
                  <Fragment key={field.name}>
                    {modal.resource === "interventions" &&
                      operationFormSections[field.name] && (
                        <div className="operation-form-section span-2">
                          <h3>{operationFormSections[field.name]}</h3>
                        </div>
                      )}
                    <div className={`form-field ${field.wide ? "span-2" : ""}`}>
                      <label htmlFor={`${formId}-${field.name}`}>
                        {field.label}
                        {field.required && (
                          <span className="required" aria-hidden="true">
                            {" "}
                            *
                          </span>
                        )}
                      </label>
                      {field.type === "select" ? (
                        <select
                          id={`${formId}-${field.name}`}
                          aria-describedby={
                            field.help
                              ? `${formId}-${field.name}-help`
                              : undefined
                          }
                          className="input"
                          disabled={
                            readonly ||
                            (modal.resource === "users" &&
                              field.name === "can_validate_billing" &&
                              values.role === "client") ||
                            (field.name === "technician" &&
                              user.role === "technician")
                          }
                          required={field.required}
                          value={values[field.name]}
                          onChange={(e) =>
                            updateField(field.name, e.target.value)
                          }
                        >
                          {!field.options?.some(([value]) => value === "") && (
                            <option value="">Sélectionner…</option>
                          )}
                          {field.options?.map(([value, label]) => (
                            <option
                              key={value}
                              value={value}
                              disabled={
                                modal.resource === "requests" &&
                                field.name === "status" &&
                                (([
                                  "ready_for_delivery",
                                  "return_to_client",
                                ].includes(value) &&
                                  modal.record?.status !== value) ||
                                  (value === "closed" &&
                                    modal.record?.status !== "closed" &&
                                    ((modal.record?.exchange &&
                                      !modal.record.exchange.can_close) ||
                                      (modal.record?.disposition
                                        ?.requires_diagnostic_billing &&
                                        !modal.record.disposition.can_close))))
                              }
                            >
                              {label}
                            </option>
                          ))}
                          {field.resource &&
                            allowedOptions(field.name, field.resource).map(
                              (row) => (
                                <option key={row.id} value={row.id}>
                                  {optionLabel(field.resource!, row)}
                                </option>
                              ),
                            )}
                        </select>
                      ) : field.type === "textarea" ? (
                        <textarea
                          id={`${formId}-${field.name}`}
                          aria-describedby={
                            field.help
                              ? `${formId}-${field.name}-help`
                              : undefined
                          }
                          className="input"
                          rows={3}
                          disabled={
                            readonly ||
                            (field.name === "technician" &&
                              user.role === "technician")
                          }
                          required={field.required}
                          maxLength={field.maxLength}
                          value={values[field.name]}
                          placeholder={field.placeholder}
                          onChange={(e) =>
                            updateField(field.name, e.target.value)
                          }
                        />
                      ) : (
                        <input
                          id={`${formId}-${field.name}`}
                          aria-describedby={
                            field.help
                              ? `${formId}-${field.name}-help`
                              : undefined
                          }
                          className="input"
                          disabled={readonly}
                          type={field.type || "text"}
                          step={
                            field.step ??
                            (field.type === "number"
                              ? [
                                  "quantity",
                                  "duration_minutes",
                                  "min_stock",
                                  "visits_per_year",
                                ].includes(field.name)
                                ? "1"
                                : "any"
                              : undefined)
                          }
                          min={field.min}
                          max={field.max}
                          maxLength={field.maxLength}
                          required={
                            field.required ||
                            (!editing && field.name === "password")
                          }
                          value={values[field.name]}
                          placeholder={field.placeholder}
                          autoComplete={
                            field.type === "password" ? "new-password" : "off"
                          }
                          onChange={(e) =>
                            updateField(field.name, e.target.value)
                          }
                        />
                      )}{" "}
                      {field.help && (
                        <small id={`${formId}-${field.name}-help`}>
                          {field.help}
                        </small>
                      )}
                    </div>
                    {modal.resource === "equipment" &&
                      field.name === "serial_number" && (
                        <div className="serial-analysis-field span-2">
                          <SerialAnalysis
                            serialNumber={String(values.serial_number || "")}
                            brand={String(values.brand || "")}
                          />
                        </div>
                      )}
                    {modal.resource === "equipment" &&
                      field.name === "model" &&
                      !readonly &&
                      (user.role === "admin" || user.role === "manager") && (
                        <div className="catalogue-picker-field span-2">
                          <CatalogueModelPicker
                            onSelect={({ model, brand }) =>
                              setValues((previous) => ({
                                ...previous,
                                model,
                                brand,
                              }))
                            }
                          />
                          <small>
                            Le choix remplit uniquement le modèle et la marque.
                            Enregistrez la fiche pour conserver ces
                            modifications.
                          </small>
                        </div>
                      )}
                  </Fragment>
                ))}
            </div>
            {modal.resource === "requests" && (
              <RequestReceptionFields
                value={values}
                callNumber={
                  modal.record ? callIdentity(modal.record).tvm : undefined
                }
                onChange={updateField}
                readonly={readonly}
                includeClosure
                canBackfillClosure={canBackfillClosure}
              />
            )}
            {modal.resource === "interventions" && (
              <>
                {sourceEquipment && (
                  <div className="request-dossier-card">
                    <dl className="request-dossier-facts">
                      <div>
                        <dt>N° d’appel TVM</dt>
                        <dd>
                          {sourceRequest
                            ? callIdentity(sourceRequest).tvm
                            : "Non renseigné"}
                        </dd>
                      </div>
                      <div>
                        <dt>N° d’appel client</dt>
                        <dd>
                          {sourceRequest
                            ? callIdentity(sourceRequest).client ||
                              "Non renseigné"
                            : "Non renseigné"}
                        </dd>
                      </div>
                      <div>
                        <dt>Ancien numéro de série</dt>
                        <dd>{sourceEquipment.serial_number}</dd>
                      </div>
                      <div>
                        <dt>Client propriétaire</dt>
                        <dd>{sourceEquipment.client_name}</dd>
                      </div>
                      <div>
                        <dt>Période du contrat lié</dt>
                        <dd>
                          {data.contracts?.find(
                            (row) => row.id === Number(values.contract),
                          )
                            ? `${dateFR(data.contracts.find((row) => row.id === Number(values.contract))?.starts_on)} → ${dateFR(data.contracts.find((row) => row.id === Number(values.contract))?.ends_on)}`
                            : "Aucun contrat lié"}
                        </dd>
                      </div>
                      <div>
                        <dt>Période de l’extension liée</dt>
                        <dd>
                          {data.warranties?.find(
                            (row) =>
                              row.id === Number(values.extension_warranty),
                          )
                            ? `${dateFR(data.warranties.find((row) => row.id === Number(values.extension_warranty))?.starts_on)} → ${dateFR(data.warranties.find((row) => row.id === Number(values.extension_warranty))?.ends_on)}`
                            : "Aucune extension liée"}
                        </dd>
                      </div>
                      {values.kind === "exchange" && (
                        <div>
                          <dt>Nouveau numéro de série</dt>
                          <dd>
                            {data.equipment?.find(
                              (row) =>
                                row.id === Number(values.replacement_equipment),
                            )?.serial_number || "À sélectionner"}
                          </dd>
                        </div>
                      )}
                    </dl>
                  </div>
                )}
                <InterventionWorksheet
                  kind={values.kind || "maintenance"}
                  value={structuredData}
                  onChange={setStructuredData}
                  readonly={readonly}
                />
              </>
            )}
            {modal.resource === "delivery-notes" && (
              <section className="delivery-lines">
                <div className="section-title">
                  <h3>Articles livrés</h3>
                  {!readonly && (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        setLines([
                          ...lines,
                          { part: "", description: "", quantity: 1 },
                        ])
                      }
                    >
                      <Plus size={15} /> Ajouter une ligne
                    </button>
                  )}
                </div>
                {lines.map((line, index) => (
                  <div className="delivery-line" key={index}>
                    <select
                      aria-label="Pièce du bon"
                      className="input"
                      disabled={readonly}
                      value={line.part}
                      onChange={(e) => {
                        const part = data.parts?.find(
                          (p) => p.id === Number(e.target.value),
                        );
                        setLines(
                          lines.map((l, i) =>
                            i === index
                              ? {
                                  ...l,
                                  part: e.target.value,
                                  description: part?.name || l.description,
                                }
                              : l,
                          ),
                        );
                      }}
                    >
                      <option value="">Article libre</option>
                      {data.parts?.map((p) => (
                        <option value={p.id} key={p.id}>
                          {p.sku}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="Désignation"
                      className="input"
                      disabled={readonly}
                      placeholder="Désignation de l’article"
                      value={line.description}
                      onChange={(e) =>
                        setLines(
                          lines.map((l, i) =>
                            i === index
                              ? { ...l, description: e.target.value }
                              : l,
                          ),
                        )
                      }
                    />
                    <input
                      aria-label="Quantité"
                      className="input"
                      disabled={readonly}
                      type="number"
                      min="1"
                      value={line.quantity}
                      onChange={(e) =>
                        setLines(
                          lines.map((l, i) =>
                            i === index
                              ? { ...l, quantity: e.target.value }
                              : l,
                          ),
                        )
                      }
                    />
                    {!readonly && (
                      <button
                        type="button"
                        className="icon-button"
                        aria-label="Retirer la ligne"
                        onClick={() =>
                          setLines(lines.filter((_, i) => i !== index))
                        }
                      >
                        <X size={15} />
                      </button>
                    )}
                  </div>
                ))}
                <small className="muted">
                  Le bon documente la livraison. Enregistrez séparément le
                  mouvement de stock pour éviter tout double débit.
                </small>
              </section>
            )}
          </div>
          <div className="modal-footer">
            <span className="form-secure">
              <Server size={14} /> Base serveur partagée
            </span>
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              {readonly ? "Fermer" : "Annuler"}
            </button>
            {!readonly && (
              <button className="button primary" disabled={busy}>
                {busy ? <Spinner /> : <Check size={17} />}{" "}
                {editing ? "Enregistrer les modifications" : "Enregistrer"}
              </button>
            )}
          </div>
        </form>
      )}
    </Modal>
  );
}

function RecordTable({
  resource,
  rows,
  onEdit,
  onIntervention,
  user,
  compact = false,
  kind,
}: {
  resource: string;
  rows: RecordData[];
  onEdit: (m: ModalState) => void;
  onIntervention: (r: RecordData) => void;
  user: User;
  compact?: boolean;
  kind?: string;
}) {
  const config = resources[resource];
  const baseColumns = compact ? config.columns.slice(0, 5) : config.columns;
  const columns: Column[] =
    kind === "preventive"
      ? [
          ...baseColumns.filter((column) => column.key !== "kind"),
          {
            key: "preventive_progress",
            label: "Visites préventives du dossier",
          },
        ]
      : kind === "commissioning"
        ? [
            ...baseColumns.filter(
              (column) => !["scheduled_at", "kind"].includes(column.key),
            ),
            { key: "performed_on", label: "Date réalisée", type: "date" },
            { key: "site", label: "Site / contact", secondary: "contact_name" },
          ]
        : baseColumns;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>
                {c.key === "call_number" && user.role === "client"
                  ? "Votre n° d’appel client / TVM"
                  : c.label}
              </th>
            ))}
            <th className="action-cell">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={resource === "interventions" ? "clickable-row" : ""}
              onClick={() => {
                if (resource === "interventions") onIntervention(row);
              }}
            >
              {columns.map((c, index) => {
                const val = row[c.key];
                return (
                  <td key={c.key}>
                    {c.key === "preventive_progress" ? (
                      <PreventiveProgress record={row} compact />
                    ) : c.key === "call_number" &&
                      (resource === "requests" ||
                        resource === "interventions") ? (
                      <CallReference
                        record={row}
                        role={user.role}
                        visit={resource === "interventions"}
                        compact
                      />
                    ) : c.type === "status" ? (
                      <Badge
                        value={val}
                        label={
                          c.key === "kind"
                            ? interventionKinds.find(
                                ([key]) => key === val,
                              )?.[1]
                            : resource === "requests" && c.key === "status"
                              ? requestStatusLabels[val]
                              : undefined
                        }
                      />
                    ) : c.type === "date" || c.type === "datetime" ? (
                      <span className="date-cell">
                        {dateFR(val, c.type === "datetime")}
                      </span>
                    ) : c.type === "money" ? (
                      money(val)
                    ) : c.type === "user" ? (
                      <span className="person-cell">
                        <span
                          className="avatar avatar-small"
                          style={{
                            background: `hsl(${(row.technician || 0) * 65 + 210} 65% 93%)`,
                            color: `hsl(${(row.technician || 0) * 65 + 210} 50% 25%)`,
                          }}
                        >
                          {initials(val || "NA")}
                        </span>
                        <span>{val || "Non assigné"}</span>
                      </span>
                    ) : c.type === "client" ? (
                      <span className="client-cell">
                        <span className="company-avatar">
                          <Building2 size={17} />
                        </span>
                        <span>
                          <strong>{val || "—"}</strong>
                          {c.secondary && <small>{row[c.secondary]}</small>}
                        </span>
                      </span>
                    ) : (
                      <div
                        className={`${index === 0 ? "primary-cell " : ""}${c.type === "serial" ? "serial-text" : ""}`}
                      >
                        <span
                          className={
                            resource === "parts" &&
                            c.key === "stock_quantity" &&
                            Number(val) <= Number(row.min_stock)
                              ? "stock-critical"
                              : resource === "parts" &&
                                  c.key === "stock_quantity"
                                ? "stock-ok"
                                : ""
                          }
                        >
                          {val ?? "—"}
                        </span>
                        {c.secondary && (
                          <small>{row[c.secondary] || "—"}</small>
                        )}
                      </div>
                    )}
                  </td>
                );
              })}
              <td className="action-cell">
                {resource !== "stock-movements" && (
                  <button
                    className="icon-button row-action"
                    title={
                      resource === "interventions"
                        ? "Ouvrir la visite de ce dossier"
                        : canManage(user, resource, row)
                          ? "Modifier"
                          : "Consulter"
                    }
                    aria-label={
                      resource === "interventions"
                        ? `Voir ${row.reference}`
                        : `${canManage(user, resource, row) ? "Modifier" : "Consulter"} ${row.name || row.reference || row.serial_number || config.singular}`
                    }
                    onClick={(e) => {
                      e.stopPropagation();
                      if (resource === "interventions") onIntervention(row);
                      else
                        onEdit({
                          resource,
                          record: row,
                          readonly: !canManage(user, resource, row),
                        });
                    }}
                  >
                    {resource === "interventions" ? (
                      <ChevronRight size={17} />
                    ) : canManage(user, resource, row) ? (
                      <Pencil size={15} />
                    ) : (
                      <Eye size={16} />
                    )}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResourcePage({
  resource,
  data,
  onEdit,
  onIntervention,
  user,
  loading,
  hideHeading = false,
  externalSearch = "",
  kind,
}: {
  resource: string;
  data: DataMap;
  onEdit: (m: ModalState) => void;
  onIntervention: (r: RecordData) => void;
  user: User;
  loading: boolean;
  hideHeading?: boolean;
  externalSearch?: string;
  kind?: string;
}) {
  const kindLabel = interventionKinds.find(([key]) => key === kind)?.[1];
  const config = kindLabel
    ? {
        ...resources[resource],
        title: kind === "exchange" ? "Échanges d’onduleurs" : kindLabel,
        description: `Les fiches ${kindLabel.toLowerCase()} enregistrées pour vos dossiers SAV.`,
        button: `Nouvelle fiche ${kindLabel.toLowerCase()}`,
      }
    : resources[resource];
  const [search, setSearch] = useState(externalSearch),
    [status, setStatus] = useState("all");
  useEffect(() => setSearch(externalSearch), [externalSearch]);
  const rows = (data[resource] || []).filter((row) => {
    const relatedClientName =
      resource === "users"
        ? data.clients?.find((client) => client.id === row.client)?.name || ""
        : "";
    return (
      [JSON.stringify(row), relatedClientName]
        .join(" ")
        .toLocaleLowerCase("fr")
        .includes(search.toLocaleLowerCase("fr")) &&
      (status === "all" || row.status === status)
    );
  });
  const statOptions = Array.from(
    new Set((data[resource] || []).map((r) => r.status).filter(Boolean)),
  );
  const readonly = !canManage(user, resource) || resource === "stock-movements";
  return (
    <>
      <div
        className={`page-heading ${hideHeading ? "section-page-heading" : ""}`}
      >
        <div>
          <div className="eyebrow">
            {user.role === "client"
              ? "VOTRE ESPACE CLIENT"
              : "VOTRE ESPACE DE TRAVAIL"}
          </div>
          <h1>{config.title}</h1>
          <p>{config.description}</p>
        </div>
        {canManage(user, resource) && (
          <button
            className="button primary"
            onClick={() =>
              onEdit({ resource, values: kind ? { kind } : undefined })
            }
          >
            <Plus size={18} />
            {config.button}
          </button>
        )}
      </div>
      {kind && ["preventive", "commissioning"].includes(kind) && (
        <div
          className="operation-list-summary"
          aria-label={`Synthèse ${kindLabel?.toLowerCase()}`}
        >
          <div>
            <span>
              {kind === "preventive"
                ? "Visites enregistrées"
                : "Fiches enregistrées"}
            </span>
            <strong>{rows.length}</strong>
          </div>
          <div>
            <span>Terminées</span>
            <strong>
              {rows.filter((row) => row.status === "completed").length}
            </strong>
          </div>
          <div>
            <span>Dossiers concernés</span>
            <strong>
              {new Set(rows.map((row) => row.service_request)).size}
            </strong>
          </div>
          <p>
            {kind === "preventive"
              ? "L’objectif de visites se définit sur le dossier SAV. Chaque fiche correspond à une visite ; les visites annulées restent visibles dans la liste."
              : "Consultez la date réelle de mise en service, le site, les contrôles et le rapport PDF de chaque opération."}
          </p>
        </div>
      )}
      <section className="card resource-card">
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label={`Rechercher dans ${config.title.toLowerCase()}`}
              placeholder={`Rechercher ${resource === "equipment" ? "un numéro de série, un modèle…" : resource === "clients" ? "un client, un contact…" : "une référence, un client…"}`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                aria-label="Effacer la recherche"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <div className="toolbar-right">
            {statOptions.length > 0 && (
              <div className="filter-select">
                <SlidersHorizontal size={15} />
                <select
                  aria-label="Filtrer par statut"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="all">Tous les statuts</option>
                  {statOptions.map((s) => (
                    <option key={s} value={s}>
                      {statuses[s] || s}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <span className="result-count">
              {rows.length} résultat{rows.length > 1 ? "s" : ""}
            </span>
          </div>
        </div>
        {loading && !data[resource]?.length ? (
          <div className="loading-state">
            <Spinner /> Chargement des données…
          </div>
        ) : rows.length ? (
          <RecordTable
            resource={resource}
            rows={rows}
            user={user}
            onEdit={
              readonly && resource === "stock-movements" ? () => {} : onEdit
            }
            onIntervention={onIntervention}
            kind={kind}
          />
        ) : (
          <Empty
            title={
              search
                ? "Aucun résultat pour cette recherche"
                : `Aucun ${config.singular} enregistré`
            }
            text={
              search
                ? "Essayez une autre référence ou un autre mot-clé."
                : `Commencez par ajouter votre premier ${config.singular}.`
            }
            action={
              canManage(user, resource) && !search ? (
                <button
                  className="button secondary"
                  onClick={() =>
                    onEdit({ resource, values: kind ? { kind } : undefined })
                  }
                >
                  <Plus size={16} />
                  {config.button}
                </button>
              ) : undefined
            }
          />
        )}
        <div className="table-footer">
          <span>
            <CheckCircle2 size={13} /> Données enregistrées sur le serveur
          </span>
          <span>
            {rows.length} élément{rows.length > 1 ? "s" : ""}
          </span>
        </div>
      </section>
    </>
  );
}

function Dashboard({
  dashboard,
  data,
  user,
  onNavigate,
  onEdit,
  onIntervention,
  loading,
}: {
  dashboard: RecordData;
  data: DataMap;
  user: User;
  onNavigate: (p: string) => void;
  onEdit: (m: ModalState) => void;
  onIntervention: (r: RecordData) => void;
  loading: boolean;
}) {
  const m = dashboard.metrics || {},
    client = user.role === "client";
  const metrics = client
    ? [
        {
          label: "Vos équipements",
          value: m.equipment_count,
          icon: Zap,
          color: "blue",
          sub: "Onduleurs suivis",
        },
        {
          label: "Demandes ouvertes",
          value: m.open_requests,
          icon: ClipboardList,
          color: "purple",
          sub: "Dossiers en cours de traitement",
        },
        {
          label: "Interventions en cours",
          value: m.active_interventions,
          icon: Wrench,
          color: "orange",
          sub: "Pour votre parc d’équipements",
        },
        {
          label: "Interventions terminées",
          value: m.completed_interventions,
          icon: CheckCheck,
          color: "green",
          sub: "Historique de maintenance",
        },
      ]
    : [
        {
          label: "Interventions en cours",
          value: m.active_interventions,
          icon: Wrench,
          color: "blue",
          sub: "Planifiées, en cours et en test",
        },
        {
          label: "Demandes ouvertes",
          value: m.open_requests,
          icon: ClipboardList,
          color: "purple",
          sub: "Dossiers SAV à suivre",
        },
        {
          label: "Stock critique",
          value: m.critical_stock,
          icon: Box,
          color: "orange",
          sub: "Références sous le seuil",
        },
        {
          label: "Équipements suivis",
          value: m.equipment_count,
          icon: Activity,
          color: "green",
          sub: `Sur ${m.client_count ?? 0} compte${m.client_count > 1 ? "s" : ""} client${m.client_count > 1 ? "s" : ""}`,
        },
      ];
  const activity = dashboard.activity || [],
    distribution = dashboard.status_distribution || [];
  const total = distribution.reduce(
      (a: number, r: RecordData) => a + Number(r.value),
      0,
    ),
    palette = ["#1764ff", "#7d9bff", "#48c8ee", "#21c98b", "#a1e7c8"];
  let cumulative = 0;
  const gradient = distribution
    .map((r: RecordData, i: number) => {
      const start = cumulative;
      cumulative += total ? (Number(r.value) / total) * 100 : 0;
      return `${palette[i % palette.length]} ${start}% ${cumulative}%`;
    })
    .join(",");
  const maxActivity = Math.max(
    1,
    ...activity.map((a: RecordData) =>
      Math.max(Number(a.interventions) || 0, Number(a.requests) || 0),
    ),
  );
  const recent = dashboard.recent_interventions || [];
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {client ? "VOTRE ESPACE CLIENT" : "MAINTENANCE & SAV"}
          </div>
          <h1>
            Tableau de bord <span className="heading-dot" />
          </h1>
          <p>
            {client
              ? "Bienvenue. Retrouvez le suivi de vos équipements et de vos dossiers."
              : "Vue d’ensemble de vos activités de maintenance UPS."}
          </p>
        </div>
        <div className="today-label">
          <CalendarDays size={17} />
          <div>
            <strong>Aujourd’hui</strong>
            <small>{dateFR(new Date().toISOString())}</small>
          </div>
        </div>
      </div>
      <div className="metric-grid">
        {metrics.map((metric, index) => (
          <button
            key={metric.label}
            className="metric-card"
            onClick={() =>
              onNavigate(
                client
                  ? ["equipment", "requests", "interventions", "reports"][index]
                  : ["interventions", "requests", "stock", "equipment"][index],
              )
            }
          >
            <div className={`metric-icon ${metric.color}`}>
              <metric.icon size={23} />
            </div>
            <div className="metric-content">
              <span>{metric.label}</span>
              <div className="metric-value">
                {loading && !dashboard.metrics ? "—" : (metric.value ?? 0)}
                <span className={`metric-note ${metric.color}`}>
                  {index === 2 && !client ? (
                    "À surveiller"
                  ) : (
                    <ArrowUpRight size={14} />
                  )}
                </span>
              </div>
              <small>{metric.sub}</small>
            </div>
            <ChevronRight className="metric-chevron" size={17} />
          </button>
        ))}
      </div>
      <div className="dashboard-main">
        <section className="card recent-card">
          <div className="card-heading">
            <div>
              <h2>Interventions récentes</h2>
              <p>Les derniers dossiers de votre activité</p>
            </div>
            <button
              className="text-button"
              onClick={() => onNavigate("interventions")}
            >
              Tout voir <ArrowRight size={15} />
            </button>
          </div>
          {recent.length ? (
            <RecordTable
              resource="interventions"
              rows={recent.slice(0, 6)}
              compact
              user={user}
              onEdit={onEdit}
              onIntervention={onIntervention}
            />
          ) : (
            <Empty
              title="Votre activité commence ici"
              text="Les interventions de votre équipe apparaîtront dans ce tableau."
              action={
                !client ? (
                  <button
                    className="button secondary"
                    onClick={() => onEdit({ resource: "interventions" })}
                  >
                    <Plus size={16} />
                    Planifier une intervention
                  </button>
                ) : undefined
              }
            />
          )}
          <div className="recent-bottom">
            <span className="live-dot" /> Données de votre espace partagé
            <span>
              {data.interventions?.length || 0} interventions au total
            </span>
          </div>
        </section>
        <div className="dashboard-charts">
          <section className="card activity-card">
            <div className="card-heading">
              <h2>Activité des 30 derniers jours</h2>
              <span className="chart-period">
                30 jours <ChevronDown size={12} />
              </span>
            </div>
            <div className="chart-legend">
              <span>
                <i style={{ background: "#1764ff" }} />
                Interventions
              </span>
              <span>
                <i style={{ background: "#b9ccff" }} />
                Demandes SAV
              </span>
            </div>
            <div className="bar-chart">
              <div className="chart-y-labels">
                {[maxActivity, Math.ceil(maxActivity / 2), 0].map((n, i) => (
                  <span key={i}>{n}</span>
                ))}
              </div>
              <div className="chart-bars">
                {activity.length ? (
                  activity.map((entry: RecordData, index: number) => (
                    <div
                      className="bar-group"
                      key={index}
                      title={`${entry.label} : ${entry.interventions || 0} intervention(s), ${entry.requests || 0} demande(s)`}
                    >
                      <div className="bars">
                        <i
                          style={{
                            height: `${(Number(entry.interventions) / maxActivity) * 100}%`,
                            minHeight: Number(entry.interventions) ? 3 : 0,
                          }}
                        />
                        <i
                          style={{
                            height: `${(Number(entry.requests) / maxActivity) * 100}%`,
                            minHeight: Number(entry.requests) ? 3 : 0,
                          }}
                        />
                      </div>
                      <span>
                        {index === 0 ||
                        index === activity.length - 1 ||
                        index % Math.max(1, Math.floor(activity.length / 4)) ===
                          0
                          ? entry.label
                          : ""}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="chart-empty">
                    Aucune activité sur la période
                  </div>
                )}
              </div>
            </div>
          </section>
          <section className="card distribution-card">
            <div className="card-heading">
              <h2>Répartition des statuts</h2>
              <CircleDot size={16} className="muted" />
            </div>
            <div className="distribution-content">
              <div
                className="donut"
                style={{
                  background: total ? `conic-gradient(${gradient})` : "#edf2fb",
                }}
              >
                <div>
                  <strong>{total}</strong>
                  <span>interventions</span>
                </div>
              </div>
              <div className="distribution-legend">
                {distribution.length ? (
                  distribution.map((r: RecordData, i: number) => (
                    <div key={r.name}>
                      <i style={{ background: palette[i % palette.length] }} />
                      <span>{statuses[r.name] || r.name}</span>
                      <strong>
                        {total
                          ? Math.round((Number(r.value) / total) * 100)
                          : 0}
                        %
                      </strong>
                    </div>
                  ))
                ) : (
                  <span className="muted">Aucune intervention</span>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
      <div className="dashboard-bottom">
        <section className="card upcoming-card">
          <div className="card-heading">
            <div>
              <h2>À venir</h2>
              <p>Vos prochaines interventions planifiées</p>
            </div>
            <button
              className="text-button"
              onClick={() => onNavigate("planning")}
            >
              Voir le planning <ArrowRight size={15} />
            </button>
          </div>
          {dashboard.upcoming?.length ? (
            <div className="upcoming-list">
              {dashboard.upcoming.slice(0, 3).map((r: RecordData) => (
                <button
                  key={r.id}
                  onClick={() => onIntervention(r)}
                  className="upcoming-item"
                >
                  <div className="upcoming-date">
                    <strong>
                      {r.scheduled_at
                        ? new Date(r.scheduled_at).getDate()
                        : "—"}
                    </strong>
                    <span>
                      {r.scheduled_at
                        ? new Date(r.scheduled_at).toLocaleDateString("fr-FR", {
                            month: "short",
                          })
                        : "À définir"}
                    </span>
                  </div>
                  <div>
                    <CallReference record={r} role={user.role} visit compact />
                    <span>
                      {r.client_name} ·{" "}
                      {r.equipment_model || r.equipment_serial}
                    </span>
                  </div>
                  <Badge value={r.status} />
                  <ChevronRight size={16} />
                </button>
              ))}
            </div>
          ) : (
            <div className="upcoming-empty">
              <CalendarDays size={23} />
              <span>
                Aucune intervention à venir. Votre planning est à jour.
              </span>
            </div>
          )}
        </section>
        <section className="powercare-note">
          <div className="note-orbit">
            <Zap size={28} fill="currentColor" />
          </div>
          <div>
            <span>VOTRE PARTENAIRE MAINTENANCE</span>
            <h2>
              Chaque équipement a une histoire.
              <br />
              Gardez-en le contrôle.
            </h2>
            <p>
              Un numéro de série, tous les dossiers.
              <br />
              Retrouvez le bon équipement en quelques secondes.
            </p>
            <button
              className="button secondary"
              onClick={() => onNavigate("scanner")}
            >
              <ScanLine size={17} />
              Scanner un équipement <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
    </>
  );
}

function InterventionDetail({
  record,
  user,
  data,
  onClose,
  onEdit,
  onSaved,
}: {
  record: RecordData;
  user: User;
  data: DataMap;
  onClose: () => void;
  onEdit: (m: ModalState) => void;
  onSaved: () => Promise<void>;
}) {
  const [tab, setTab] = useState("suivi"),
    [part, setPart] = useState(""),
    [quantity, setQuantity] = useState(1),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  const request = data.requests?.find((r) => r.id === record.service_request),
    equipment = data.equipment?.find((r) => r.id === request?.equipment);
  const steps = [
    {
      id: "scheduled",
      label: "Intervention planifiée",
      description: dateFR(record.scheduled_at, true),
    },
    {
      id: "in_progress",
      label: "Diagnostic et travaux",
      description: "Prise en charge par votre technicien",
    },
    {
      id: "testing",
      label: "Tests et validation",
      description: "Vérification de l’équipement",
    },
    {
      id: "completed",
      label: "Intervention terminée",
      description: record.completed_at
        ? dateFR(record.completed_at, true)
        : "Rapport et recommandations",
    },
  ];
  const activeIndex = steps.findIndex((s) => s.id === record.status);
  async function usePart(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    try {
      await api(`interventions/${record.id}/use-part/`, {
        method: "POST",
        body: JSON.stringify({ part: Number(part), quantity }),
      });
      await onSaved();
      setSuccess("Pièce affectée et sortie de stock enregistrée.");
      setPart("");
      setQuantity(1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Détail de l’intervention"
      subtitle="Toutes les informations utiles, au même endroit."
      onClose={onClose}
      wide
    >
      <div className="detail-content">
        <div className="detail-reference">
          <div>
            <span className="detail-tool">
              <Wrench size={21} />
            </span>
            <div>
              <CallReference record={record} role={user.role} visit />
              <p>{request?.subject || "Maintenance de votre onduleur"}</p>
            </div>
          </div>
          <Badge value={record.status} />
        </div>
        <div className="detail-info-grid">
          <div>
            <Building2 size={21} />
            <div>
              <span>Client</span>
              <strong>{record.client_name || "—"}</strong>
              <small>{equipment?.location || "Site non précisé"}</small>
            </div>
          </div>
          <div>
            <Zap size={21} />
            <div>
              <span>Équipement</span>
              <strong>
                {record.equipment_model || equipment?.model || "—"}
              </strong>
              <small>
                S/N :{" "}
                {record.equipment_serial || equipment?.serial_number || "—"}
              </small>
            </div>
          </div>
          <div>
            <CalendarDays size={21} />
            <div>
              <span>Planification</span>
              <strong>{dateFR(record.scheduled_at, true)}</strong>
              <small>
                {record.technician_name || "Technicien non assigné"}
              </small>
            </div>
          </div>
        </div>
        {record.kind === "preventive" && <PreventiveProgress record={record} />}
        <div className="tabs">
          <button
            className={tab === "suivi" ? "active" : ""}
            onClick={() => setTab("suivi")}
          >
            Suivi & diagnostic
          </button>
          {["preventive", "commissioning"].includes(record.kind) && (
            <button
              className={tab === "fiche" ? "active" : ""}
              onClick={() => setTab("fiche")}
            >
              Fiche de l’opération
            </button>
          )}
          <button
            className={tab === "documents" ? "active" : ""}
            onClick={() => setTab("documents")}
          >
            Documents
          </button>
          {canManage(user, "interventions", record) && (
            <button
              className={tab === "pieces" ? "active" : ""}
              onClick={() => setTab("pieces")}
            >
              Pièces utilisées
            </button>
          )}
        </div>
        {tab === "suivi" && (
          <div className="detail-body-grid">
            <section>
              <h3>Avancement de l’intervention</h3>
              <ol className="timeline">
                {steps.map((step, index) => (
                  <li
                    key={step.id}
                    className={
                      record.status === "cancelled"
                        ? ""
                        : index < activeIndex
                          ? "done"
                          : index === activeIndex
                            ? "current"
                            : ""
                    }
                  >
                    <span>
                      {index < activeIndex ? (
                        <Check size={14} />
                      ) : index === activeIndex ? (
                        <CircleDot size={14} />
                      ) : (
                        <CircleDot size={12} />
                      )}
                    </span>
                    <div>
                      <strong>{step.label}</strong>
                      <p>{step.description}</p>
                    </div>
                  </li>
                ))}
              </ol>
              {record.status === "cancelled" && <Badge value="cancelled" />}
            </section>
            <section className="diagnosis-section">
              <h3>Diagnostic & observations</h3>
              <p className={!record.diagnosis ? "muted" : ""}>
                {record.diagnosis ||
                  "Aucun diagnostic renseigné pour le moment."}
              </p>
              <h3>Travaux réalisés</h3>
              <p className={!record.work_done ? "muted" : ""}>
                {record.work_done ||
                  "Les travaux seront renseignés pendant l’intervention."}
              </p>
              <h3>Recommandations</h3>
              <p className={!record.recommendations ? "muted" : ""}>
                {record.recommendations ||
                  "Aucune recommandation complémentaire."}
              </p>
              {user.role !== "client" && record.internal_notes && (
                <div className="internal-note">
                  <LockKeyhole size={14} />
                  <div>
                    <strong>Note interne · équipe TVM uniquement</strong>
                    <p>{record.internal_notes}</p>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
        {tab === "documents" && (
          <div className="report-document">
            <div className="pdf-icon">
              <FileText size={30} />
              <span>PDF</span>
            </div>
            <div>
              <h3>Rapport d’intervention</h3>
              <p>
                Diagnostic, travaux et recommandations. Les notes internes sont
                exclues.
              </p>
              <small>
                {record.status === "completed"
                  ? "Intervention terminée"
                  : "L’intervention est en cours : le rapport reflète son état actuel."}
              </small>
            </div>
            <a
              className="button primary"
              href={`/api/interventions/${record.id}/report/`}
              target="_blank"
              rel="noreferrer"
            >
              <Download size={17} />
              Télécharger
            </a>
          </div>
        )}
        {tab === "fiche" && (
          <section className="operation-detail-sheet">
            <h3>
              {record.kind === "preventive"
                ? "Visite de maintenance préventive"
                : "Mise en service de l’onduleur"}
            </h3>
            <dl className="request-dossier-facts">
              <div>
                <dt>Date réelle de l’opération</dt>
                <dd>
                  {record.performed_on
                    ? dateFR(record.performed_on)
                    : "Non renseignée"}
                </dd>
              </div>
              <div>
                <dt>Site de l’opération</dt>
                <dd>{record.site || "Non renseigné"}</dd>
              </div>
              <div>
                <dt>Client final</dt>
                <dd>{record.end_customer || "Non renseigné"}</dd>
              </div>
              <div>
                <dt>Contact sur site</dt>
                <dd>{record.contact_name || "Non renseigné"}</dd>
              </div>
              <div>
                <dt>Téléphone du contact</dt>
                <dd>{record.contact_phone || "Non renseigné"}</dd>
              </div>
              <div>
                <dt>Armoire batteries</dt>
                <dd>{record.cabinet_serial || "Non renseignée"}</dd>
              </div>
              <div>
                <dt>Nombre de batteries</dt>
                <dd>{record.battery_count ?? "Non renseigné"}</dd>
              </div>
              <div>
                <dt>Contrat lié</dt>
                <dd>{record.contract_number || "Aucun contrat lié"}</dd>
              </div>
            </dl>
            <InterventionWorksheet
              kind={record.kind}
              value={record.structured_data || {}}
              onChange={() => {}}
              readonly
            />
            <div className="operation-detail-conclusion">
              <h3>Synthèse et conclusion</h3>
              <p>{record.summary || "Aucune synthèse renseignée."}</p>
              <strong>
                {statuses[record.conclusion] || "Conclusion non renseignée"}
              </strong>
              {record.conclusion_notes && <p>{record.conclusion_notes}</p>}
            </div>
            <a
              className="button secondary small"
              href={`/api/interventions/${record.id}/report/`}
              target="_blank"
              rel="noreferrer"
            >
              <Download size={16} />
              Télécharger le rapport PDF
            </a>
          </section>
        )}
        {tab === "pieces" && (
          <section>
            <h3>Affecter une pièce à cette intervention</h3>
            <p className="muted">
              La quantité est déduite du stock par une opération atomique et
              traçable.
            </p>
            {error && <ErrorBox>{error}</ErrorBox>}
            {success && (
              <div className="success-box">
                <CheckCircle2 size={17} />
                {success}
              </div>
            )}
            <form className="part-use-form" onSubmit={usePart}>
              <label>
                Pièce
                <select
                  className="input"
                  value={part}
                  onChange={(e) => setPart(e.target.value)}
                  required
                >
                  <option value="">Choisir une pièce…</option>
                  {data.parts?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {optionLabel("parts", p)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Quantité
                <input
                  className="input"
                  type="number"
                  value={quantity}
                  min="1"
                  step="1"
                  onChange={(e) => setQuantity(Number(e.target.value))}
                  required
                />
              </label>
              <button className="button primary" disabled={busy}>
                {busy ? <Spinner /> : <Plus size={16} />}Affecter
              </button>
            </form>
            <div className="part-history">
              <h3>Sorties de stock liées</h3>
              {data["stock-movements"]
                ?.filter((m) => m.intervention === record.id)
                .map((m) => (
                  <div key={m.id}>
                    <span>
                      <Package size={15} />
                      {m.part_name}
                    </span>
                    <strong>{Math.abs(m.quantity)}</strong>
                    <small>{dateFR(m.created_at, true)}</small>
                  </div>
                ))}
              {!data["stock-movements"]?.some(
                (m) => m.intervention === record.id,
              ) && <p className="muted">Aucune sortie de pièce enregistrée.</p>}
            </div>
          </section>
        )}
      </div>
      <div className="modal-footer">
        <button className="button secondary" onClick={onClose}>
          Fermer
        </button>
        <a
          className="button secondary"
          href={`/api/interventions/${record.id}/report/`}
          target="_blank"
          rel="noreferrer"
        >
          <FileText size={16} />
          Rapport PDF
        </a>
        {canManage(user, "interventions", record) && (
          <button
            className="button primary"
            onClick={() => {
              onClose();
              onEdit({ resource: "interventions", record });
            }}
          >
            <Pencil size={16} />
            Modifier l’intervention
          </button>
        )}
      </div>
    </Modal>
  );
}

function Planning({
  data,
  onIntervention,
  onEdit,
  user,
}: {
  data: DataMap;
  onIntervention: (r: RecordData) => void;
  onEdit: (m: ModalState) => void;
  user: User;
}) {
  const [weekOffset, setWeekOffset] = useState(0),
    [showAll, setShowAll] = useState(false);
  const start = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + weekOffset * 7);
    return d;
  }, [weekOffset]);
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });
  const unscheduled = (data.interventions || []).filter(
    (r) =>
      !r.scheduled_at && r.status !== "cancelled" && r.status !== "completed",
  );
  const rows = (data.interventions || [])
    .filter(
      (r) =>
        r.scheduled_at &&
        (showAll ||
          (new Date(r.scheduled_at) >= start &&
            new Date(r.scheduled_at) <
              new Date(start.getTime() + 7 * 86400000))),
    )
    .sort(
      (a, b) =>
        new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">ORGANISATION DE L’ÉQUIPE</div>
          <h1>Planning des interventions</h1>
          <p>
            Les rendez-vous réels de votre équipe, partagés avec tous les
            utilisateurs.
          </p>
        </div>
        {user.role !== "client" && (
          <button
            className="button primary"
            onClick={() => onEdit({ resource: "interventions" })}
          >
            <Plus size={18} />
            Planifier une intervention
          </button>
        )}
      </div>
      <section className="card planning-card">
        <div className="planning-toolbar">
          <div className="week-navigation">
            <button
              className="icon-button"
              aria-label="Semaine précédente"
              onClick={() => setWeekOffset(weekOffset - 1)}
            >
              <ChevronLeft size={19} />
            </button>
            <strong>
              {dateFR(days[0].toISOString())} — {dateFR(days[6].toISOString())}
            </strong>
            <button
              className="icon-button"
              aria-label="Semaine suivante"
              onClick={() => setWeekOffset(weekOffset + 1)}
            >
              <ChevronRight size={19} />
            </button>
            <button
              className="button secondary small"
              onClick={() => {
                setWeekOffset(0);
                setShowAll(false);
              }}
            >
              Aujourd’hui
            </button>
          </div>
          <button
            className={`button ${showAll ? "primary" : "secondary"} small`}
            onClick={() => setShowAll(!showAll)}
          >
            {showAll ? "Vue semaine" : "Toutes les dates"}
          </button>
        </div>
        {showAll ? (
          <div className="agenda-list">
            {rows.length ? (
              rows.map((r) => (
                <button
                  key={r.id}
                  className="agenda-item"
                  onClick={() => onIntervention(r)}
                >
                  <span>
                    <CalendarDays size={18} />
                    {dateFR(r.scheduled_at, true)}
                  </span>
                  <CallReference record={r} role={user.role} visit compact />
                  <span>{r.client_name}</span>
                  <span>{r.technician_name || "Non assigné"}</span>
                  <Badge value={r.status} />
                  <ChevronRight size={17} />
                </button>
              ))
            ) : (
              <Empty title="Aucune intervention planifiée" />
            )}
          </div>
        ) : (
          <div className="week-grid">
            {days.map((day) => {
              const dayRows = rows.filter(
                  (r) =>
                    new Date(r.scheduled_at).toDateString() ===
                    day.toDateString(),
                ),
                today = day.toDateString() === new Date().toDateString();
              return (
                <div
                  key={day.toISOString()}
                  className={`week-day ${today ? "today" : ""}`}
                >
                  <header>
                    <span>
                      {day.toLocaleDateString("fr-FR", { weekday: "short" })}
                    </span>
                    <strong>{day.getDate()}</strong>
                  </header>
                  <div>
                    {dayRows.map((r) => (
                      <button
                        key={r.id}
                        className={`calendar-event event-${r.status}`}
                        onClick={() => onIntervention(r)}
                      >
                        <time>
                          {new Date(r.scheduled_at).toLocaleTimeString(
                            "fr-FR",
                            { hour: "2-digit", minute: "2-digit" },
                          )}
                        </time>
                        <CallReference
                          record={r}
                          role={user.role}
                          visit
                          compact
                        />
                        <span>{r.client_name}</span>
                        <small>{r.technician_name || "Non assigné"}</small>
                      </button>
                    ))}
                    {!dayRows.length && <span className="day-empty">—</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
      {unscheduled.length > 0 && (
        <section className="card unscheduled-card">
          <div className="card-heading">
            <h2>
              À planifier{" "}
              <span className="count-pill">{unscheduled.length}</span>
            </h2>
          </div>
          {unscheduled.map((r) => (
            <button
              key={r.id}
              className="agenda-item"
              onClick={() => onIntervention(r)}
            >
              <Clock3 size={18} />
              <CallReference record={r} role={user.role} visit compact />
              <span>{r.client_name}</span>
              <Badge value={r.status} />
              <ChevronRight size={17} />
            </button>
          ))}
        </section>
      )}
    </>
  );
}

function Reports({
  data,
  user,
  onIntervention,
}: {
  data: DataMap;
  user: User;
  onIntervention: (r: RecordData) => void;
}) {
  const [search, setSearch] = useState("");
  const rows = (data.interventions || []).filter((r) =>
    JSON.stringify(r).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">DOCUMENTS & TRAÇABILITÉ</div>
          <h1>Rapports d’intervention</h1>
          <p>
            Des rapports PDF générés à partir des dossiers enregistrés, sans
            notes internes.
          </p>
        </div>
        <div className="heading-chip">
          <FileCheck2 size={17} />
          {rows.length} rapport{rows.length > 1 ? "s" : ""} disponible
          {rows.length > 1 ? "s" : ""}
        </div>
      </div>
      <section className="card">
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              value={search}
              aria-label="Rechercher un rapport"
              onChange={(e) => setSearch(e.target.value)}
              placeholder="N° d’appel TVM, n° d’appel client, référence de visite…"
            />
          </div>
        </div>
        {rows.length ? (
          <div className="report-list">
            {rows.map((r) => (
              <div className="report-row" key={r.id}>
                <div className="pdf-icon">
                  <FileText size={25} />
                  <span>PDF</span>
                </div>
                <button
                  className="report-title"
                  onClick={() => onIntervention(r)}
                >
                  <CallReference record={r} role={user.role} visit />
                  <span>
                    {r.client_name} · {r.equipment_model || r.equipment_serial}
                  </span>
                  <small>
                    {dateFR(r.completed_at || r.scheduled_at || r.created_at)}
                  </small>
                </button>
                <Badge value={r.status} />
                <a
                  className="button secondary small"
                  href={`/api/interventions/${r.id}/report/`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Download size={16} />
                  Télécharger
                </a>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="Aucun rapport disponible"
            text="Créez une intervention pour générer son rapport PDF."
          />
        )}
      </section>
      <p className="section-footnote">
        <CircleHelp size={15} />
        Un rapport d’intervention en cours reflète son état actuel. Son statut
        figure dans le document.
      </p>
    </>
  );
}

function GlobalSearch({
  query,
  user,
  onClose,
  onNavigate,
  onIntervention,
}: {
  query: string;
  user: User;
  onClose: () => void;
  onNavigate: (p: string, q?: string) => void;
  onIntervention: (r: RecordData) => void;
}) {
  const [results, setResults] = useState<RecordData>({}),
    [busy, setBusy] = useState(true),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    setResults({});
    api(`search/?q=${encodeURIComponent(query)}`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setResults(value);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [query]);
  return (
    <Modal
      title="Recherche globale"
      subtitle={`Résultats autorisés pour « ${query} »`}
      onClose={onClose}
      wide
    >
      <div className="modal-content">
        {error && <ErrorBox>{error}</ErrorBox>}
        {busy ? (
          <div className="loading-state">
            <Spinner />
            Recherche en cours…
          </div>
        ) : Object.values(results).some((v) => Array.isArray(v) && v.length) ? (
          Object.entries(results)
            .filter(([, rows]) => Array.isArray(rows) && rows.length)
            .map(([resource, rows]) => (
              <section key={resource} className="search-results">
                <h3>{resources[resource]?.title || resource}</h3>
                {(rows as RecordData[]).map((row) => (
                  <button
                    key={row.id}
                    onClick={() => {
                      onClose();
                      if (resource === "interventions") onIntervention(row);
                      else
                        onNavigate(
                          resource,
                          row.serial_number || row.name || row.reference || "",
                        );
                    }}
                  >
                    <span className="result-icon">
                      {resource === "equipment" ? (
                        <Zap size={19} />
                      ) : resource === "clients" ? (
                        <Building2 size={19} />
                      ) : (
                        <ClipboardList size={19} />
                      )}
                    </span>
                    <div>
                      {resource === "requests" ||
                      resource === "interventions" ? (
                        <CallReference
                          record={row}
                          role={user.role}
                          visit={resource === "interventions"}
                          compact
                        />
                      ) : (
                        <strong>
                          {row.name || row.serial_number || row.reference}
                        </strong>
                      )}
                      <span>
                        {row.model ||
                          row.subject ||
                          row.client_name ||
                          row.contact_name}
                      </span>
                    </div>
                    <ChevronRight size={17} />
                  </button>
                ))}
              </section>
            ))
        ) : (
          <Empty
            title="Aucun dossier correspondant"
            text="Vérifiez la référence ou le numéro de série. Seules les données auxquelles vous avez accès sont recherchées."
          />
        )}
      </div>
    </Modal>
  );
}

export default function App() {
  const sessionGeneration = useRef(0),
    reloadGeneration = useRef(0),
    activeUserId = useRef<number | null>(null);
  const [user, setUser] = useState<User | null>(null),
    [initialized, setInitialized] = useState(false),
    [demo, setDemo] = useState(false),
    [sessionError, setSessionError] = useState("");
  const [page, setPage] = useState(
      () => window.location.hash.slice(1) || "dashboard",
    ),
    [mobileMenu, setMobileMenu] = useState(false),
    [data, setData] = useState<DataMap>({}),
    [dashboard, setDashboard] = useState<RecordData>({}),
    [loading, setLoading] = useState(false),
    [loadError, setLoadError] = useState(""),
    [modal, setModal] = useState<ModalState | null>(null),
    [detail, setDetail] = useState<RecordData | null>(null),
    [requestDetail, setRequestDetail] = useState<RecordData | null>(null),
    [requestCounts, setRequestCounts] = useState<RequestCategoryCount[] | null>(
      null,
    ),
    [query, setQuery] = useState(""),
    [searchQuery, setSearchQuery] = useState(""),
    [externalSearch, setExternalSearch] = useState(""),
    [contractTab, setContractTab] = useState("contracts"),
    [stockTab, setStockTab] = useState("parts"),
    [logoutBusy, setLogoutBusy] = useState(false),
    [toast, setToast] = useState("");
  useEffect(() => {
    api("session/")
      .then((s) => {
        setCsrf(s.csrfToken);
        activeUserId.current = s.user?.id ?? null;
        setUser(s.user);
        setDemo(Boolean(s.demo_mode));
      })
      .catch((err) => setSessionError(err.message))
      .finally(() => setInitialized(true));
  }, []);
  const reload = useCallback(async () => {
    if (!user || activeUserId.current !== user.id) return;
    const sessionStamp = sessionGeneration.current,
      requestStamp = ++reloadGeneration.current;
    const current = () =>
      sessionGeneration.current === sessionStamp &&
      reloadGeneration.current === requestStamp &&
      activeUserId.current === user.id;
    setLoading(true);
    setLoadError("");
    const client = user.role === "client";
    const names = client
      ? [
          "clients",
          "equipment",
          "requests",
          "interventions",
          "contracts",
          "warranties",
          "delivery-notes",
        ]
      : [
          "clients",
          "equipment",
          "requests",
          "interventions",
          "parts",
          "stock-movements",
          "contracts",
          "warranties",
          "delivery-notes",
          "users",
        ];
    const results = await Promise.allSettled(
      names.map(
        async (name) => [name, listResult(await api(`${name}/`))] as const,
      ),
    );
    const failures: string[] = [];
    const fresh: DataMap = {};
    results.forEach((result, index) => {
      if (result.status === "fulfilled")
        fresh[result.value[0]] = result.value[1];
      else
        failures.push(
          `${resources[names[index]]?.title || names[index]} : ${result.reason.message}`,
        );
    });
    if (!current()) return;
    setData((old) => ({ ...old, ...fresh }));
    try {
      const nextDashboard = await api("dashboard/");
      if (!current()) return;
      setDashboard(nextDashboard);
    } catch (err) {
      if (!current()) return;
      failures.push(`Tableau de bord : ${(err as Error).message}`);
    }
    if (!current()) return;
    setLoadError(failures.join(" · "));
    setLoading(false);
  }, [user]);
  useEffect(() => {
    void reload();
  }, [reload]);
  useEffect(() => {
    const listener = () => {
      setPage(window.location.hash.slice(1) || "dashboard");
      setExternalSearch("");
    };
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);
  function navigate(target: string, search = "") {
    if (user?.role === "client" && !clientPages.has(target.split("/")[0]))
      target = "dashboard";
    if (target === "users" && user?.role !== "admin") target = "dashboard";
    setPage(target);
    window.history.replaceState(null, "", `#${target}`);
    setExternalSearch(search);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function changeSession(nextUser: User | null, nextDemo = false) {
    activeUserId.current = nextUser?.id ?? null;
    sessionGeneration.current += 1;
    reloadGeneration.current += 1;
    setData({});
    setDashboard({});
    setDetail(null);
    setRequestDetail(null);
    setRequestCounts(null);
    setModal(null);
    setSearchQuery("");
    setQuery("");
    setExternalSearch("");
    setLoadError("");
    setToast("");
    setLoading(false);
    setUser(nextUser);
    setDemo(nextDemo);
    setPage("dashboard");
    window.history.replaceState(null, "", "#dashboard");
  }
  async function saved() {
    await reload();
    setToast("Enregistrement effectué dans la base partagée.");
  }
  async function logout() {
    setLogoutBusy(true);
    try {
      await api("logout/", { method: "POST", body: "{}" });
      changeSession(null);
      const s = await api("session/");
      setCsrf(s.csrfToken);
    } catch (err) {
      setLoadError((err as Error).message);
    } finally {
      setLogoutBusy(false);
    }
  }
  function openModal(value: ModalState) {
    if (value.resource === "requests" && value.record) {
      setRequestDetail(value.record);
      return;
    }
    setModal(value);
  }
  const closeModal = useCallback(() => setModal(null), []),
    closeDetail = useCallback(() => setDetail(null), []),
    closeRequestDetail = useCallback(() => setRequestDetail(null), []),
    closeSearch = useCallback(() => setSearchQuery(""), []);
  if (!initialized)
    return (
      <div className="app-loading">
        <Logo />
        <Spinner />
        <p>Connexion à votre espace sécurisé…</p>
      </div>
    );
  if (!user)
    return (
      <>
        {sessionError && (
          <div className="connection-banner">
            <AlertCircle size={16} />
            Connexion au serveur impossible : {sessionError}
            <button onClick={() => window.location.reload()}>Réessayer</button>
          </div>
        )}
        <Login
          onLogin={(u, d) => {
            changeSession(u, d);
            setSessionError("");
          }}
        />
      </>
    );
  const basePage = page.startsWith("requests/") ? "requests" : page;
  const requestCategory = requestCategories.some(
    (entry) => entry.key === page.split("/")[1],
  )
    ? page.split("/")[1]
    : "all";
  const allowedPage =
    (user.role === "client" && !clientPages.has(basePage)) ||
    (["exchange-billing", "diagnostic-billing"].includes(basePage) &&
      !(
        user.role !== "client" &&
        (user.role === "admin" || user.can_validate_billing === true)
      )) ||
    (basePage === "users" && user.role !== "admin")
      ? "dashboard"
      : basePage;
  const common = {
    data,
    onEdit: openModal,
    onIntervention: setDetail,
    user,
    loading,
  };
  const currentDetail = detail
    ? data.interventions?.find((r) => r.id === detail.id) || detail
    : null;
  const currentRequestDetail = requestDetail
    ? data.requests?.find((row) => row.id === requestDetail.id) || requestDetail
    : null;
  return (
    <div className="app-shell">
      {mobileMenu && (
        <div className="sidebar-scrim" onClick={() => setMobileMenu(false)} />
      )}
      <aside className={`sidebar ${mobileMenu ? "open" : ""}`}>
        <div className="sidebar-brand">
          <Logo />
          <button
            className="icon-button mobile-close"
            aria-label="Fermer le menu"
            onClick={() => setMobileMenu(false)}
          >
            <X size={19} />
          </button>
        </div>
        <nav aria-label="Navigation principale">
          {navGroups.map((group) => {
            const items = group.items.filter(
              (item) =>
                (user.role !== "client" || clientPages.has(item.id)) &&
                (!["exchange-billing", "diagnostic-billing"].includes(
                  item.id,
                ) ||
                  (user.role !== "client" &&
                    (user.role === "admin" ||
                      user.can_validate_billing === true))) &&
                (item.id !== "users" || user.role === "admin"),
            );
            return items.length ? (
              <div className="nav-group" key={group.label}>
                <div className="nav-label">{group.label}</div>
                {items.map((item) => (
                  <Fragment key={item.id}>
                    <button
                      className={`nav-item ${allowedPage === item.id ? "active" : ""}`}
                      aria-label={item.label}
                      aria-expanded={
                        item.id === "requests"
                          ? allowedPage === "requests"
                          : undefined
                      }
                      onClick={() => navigate(item.id)}
                    >
                      <item.icon size={18} />
                      <span>{item.label}</span>
                      {item.id === "requests" &&
                        Number(dashboard.metrics?.open_requests) > 0 && (
                          <b>{dashboard.metrics.open_requests}</b>
                        )}
                      {allowedPage === item.id && (
                        <span className="nav-active-dot" />
                      )}
                    </button>
                    {item.id === "requests" && allowedPage === "requests" && (
                      <div
                        className="nav-submenu"
                        aria-label="Catégories des demandes"
                      >
                        {requestCategories.map((entry) => (
                          <button
                            type="button"
                            key={entry.key}
                            aria-label={`Demandes : ${entry.label}`}
                            className={`nav-subitem ${requestCategory === entry.key ? "active" : ""}`}
                            onClick={() => navigate(`requests/${entry.key}`)}
                          >
                            <span>{entry.label}</span>
                            <span className="nav-subcount">
                              {requestCounts?.find(
                                (row) => row.key === entry.key,
                              )?.count ?? "—"}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </Fragment>
                ))}
              </div>
            ) : null;
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-help">
            <span>
              <ShieldCheck size={18} />
            </span>
            <div>
              <strong>
                {user.role === "client"
                  ? "Votre espace personnel"
                  : "Tout votre SAV, ensemble"}
              </strong>
              <small>
                {user.role === "client"
                  ? "Vos dossiers restent confidentiels."
                  : "Une base partagée, une équipe."}
              </small>
            </div>
          </div>
          <div className="sidebar-user">
            <span className="avatar">
              {initials(
                `${user.first_name} ${user.last_name}`.trim() || user.username,
              )}
            </span>
            <div>
              <strong>
                {`${user.first_name} ${user.last_name}`.trim() || user.username}
              </strong>
              <small>{roleNames[user.role]}</small>
            </div>
            <button
              className="icon-button"
              onClick={logout}
              disabled={logoutBusy}
              title="Se déconnecter"
              aria-label="Se déconnecter"
            >
              {logoutBusy ? <Spinner /> : <LogOut size={17} />}
            </button>
          </div>
        </div>
      </aside>
      <div className="main-wrap">
        <header className="topbar">
          <button
            className="icon-button menu-toggle"
            aria-label="Ouvrir le menu"
            onClick={() => setMobileMenu(true)}
          >
            <Menu size={21} />
          </button>
          <form
            className="global-search"
            onSubmit={(e) => {
              e.preventDefault();
              if (query.trim()) setSearchQuery(query.trim());
            }}
          >
            <Search size={18} />
            <input
              aria-label="Recherche globale"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                user.role === "client"
                  ? "Rechercher votre n° d’appel client, un n° TVM, une série…"
                  : "Rechercher un n° d’appel TVM, un n° d’appel client, une série…"
              }
            />
            <kbd>↵</kbd>
          </form>
          <div className="topbar-actions">
            <span className="workspace-status">
              <i />
              Espace partagé
            </span>
            <button
              className="icon-button top-notification"
              aria-label="Voir les demandes ouvertes"
              title="Demandes ouvertes"
              onClick={() => navigate("requests")}
            >
              <Bell size={19} />
              {Number(dashboard.metrics?.open_requests) > 0 && <span />}
            </button>
            <button
              className="icon-button help-button"
              aria-label="Aide et intégrations"
              onClick={() =>
                navigate(user.role === "client" ? "reports" : "integrations")
              }
            >
              <CircleHelp size={19} />
            </button>
            <span className="topbar-divider" />
            <span className="topbar-avatar avatar">
              {initials(
                `${user.first_name} ${user.last_name}`.trim() || user.username,
              )}
            </span>
          </div>
        </header>
        {demo && (
          <div className="demo-banner">
            <span>
              <CircleDot size={14} />
              <strong>Environnement de démonstration</strong> · Les
              modifications sont enregistrées sur le serveur.
            </span>
            <span>TVM / PowerCare</span>
          </div>
        )}
        <main className="main-content">
          {loadError && (
            <div className="load-error">
              <ErrorBox>{loadError}</ErrorBox>
              <button
                className="button secondary small"
                onClick={() => void reload()}
              >
                Réessayer
              </button>
            </div>
          )}
          {allowedPage === "dashboard" ? (
            <Dashboard
              {...common}
              dashboard={dashboard}
              onNavigate={navigate}
            />
          ) : allowedPage === "clients" ? (
            <ClientsDirectory
              key={`${user.id}:${user.role}`}
              user={user}
              clients={data.clients || []}
              refreshKey={data.clients}
              initialSearch={externalSearch}
              onEdit={openModal}
              onChanged={saved}
              onNavigate={navigate}
              Dialog={Modal}
            />
          ) : allowedPage === "requests" ? (
            <RequestsWorkspace
              category={requestCategory}
              user={user}
              onCategoryChange={(key) => navigate(`requests/${key}`)}
              onOpen={setRequestDetail}
              onCreate={() => openModal({ resource: "requests" })}
              onCountsChange={setRequestCounts}
              refreshKey={data.requests}
              initialSearch={externalSearch}
            />
          ) : ["dispatch", "diagnostic-billing"].includes(allowedPage) ? (
            <DispatchWorkspace
              key={`${allowedPage}:${user.id}:${user.role}`}
              user={user}
              equipment={data.equipment || []}
              refreshKey={data.requests}
              onChanged={saved}
              onOpenRequest={setRequestDetail}
              Dialog={Modal}
              billing={allowedPage === "diagnostic-billing"}
              initialSearch={externalSearch}
              onOpenBilling={() => navigate("diagnostic-billing")}
            />
          ) : ["exchange", "exchange-billing"].includes(allowedPage) ? (
            <ExchangeWorkspace
              key={`${allowedPage}:${user.id}:${user.role}`}
              user={user}
              equipment={data.equipment || []}
              interventions={data.interventions || []}
              refreshKey={data.requests}
              onChanged={saved}
              onOpenRequest={setRequestDetail}
              onIntervention={setDetail}
              Dialog={Modal}
              billing={allowedPage === "exchange-billing"}
              initialSearch={externalSearch}
            />
          ) : ["commissioning", "preventive"].includes(allowedPage) ? (
            <ResourcePage
              {...common}
              resource="interventions"
              kind={allowedPage}
              data={{
                ...data,
                interventions: (data.interventions || []).filter(
                  (row) => row.kind === allowedPage,
                ),
              }}
            />
          ) : allowedPage === "planning" ? (
            <Planning {...common} />
          ) : allowedPage === "reports" ? (
            <Reports data={data} user={user} onIntervention={setDetail} />
          ) : allowedPage === "contracts" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">COUVERTURE & ENGAGEMENTS</div>
                  <h1>Contrats & garanties</h1>
                  <p>
                    Gardez une vision claire de la couverture de votre parc
                    d’onduleurs.
                  </p>
                </div>
              </div>
              <div className="page-tabs">
                <button
                  className={contractTab === "contracts" ? "active" : ""}
                  onClick={() => setContractTab("contracts")}
                >
                  <FileCheck2 size={17} />
                  Contrats <span>{data.contracts?.length || 0}</span>
                </button>
                <button
                  className={contractTab === "warranties" ? "active" : ""}
                  onClick={() => setContractTab("warranties")}
                >
                  <ShieldCheck size={17} />
                  Garanties <span>{data.warranties?.length || 0}</span>
                </button>
              </div>
              <ResourcePage
                key={contractTab}
                resource={contractTab}
                {...common}
                hideHeading
              />
            </>
          ) : allowedPage === "stock" ? (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">LOGISTIQUE & DISPONIBILITÉ</div>
                  <h1>Gestion du stock</h1>
                  <p>
                    Les bonnes pièces, au bon moment. Des mouvements tracés et
                    un stock partagé.
                  </p>
                </div>
                <button
                  className="button primary"
                  onClick={() => openModal({ resource: "stock-movements" })}
                  disabled={!canManage(user, "stock-movements")}
                >
                  <ArrowDownLeft size={18} />
                  Entrée / sortie de stock
                </button>
              </div>
              <div className="stock-summary">
                <div className="card">
                  <span className="metric-icon blue">
                    <Package size={22} />
                  </span>
                  <div>
                    <span>Références en catalogue</span>
                    <strong>{data.parts?.length || 0}</strong>
                  </div>
                </div>
                <div className="card">
                  <span className="metric-icon orange">
                    <AlertCircle size={22} />
                  </span>
                  <div>
                    <span>Stock critique</span>
                    <strong>
                      {data.parts?.filter(
                        (p) => Number(p.stock_quantity) <= Number(p.min_stock),
                      ).length || 0}
                    </strong>
                  </div>
                </div>
                <div className="card">
                  <span className="metric-icon green">
                    <Box size={22} />
                  </span>
                  <div>
                    <span>Valeur indicative du stock</span>
                    <strong>
                      {money(
                        data.parts?.reduce(
                          (sum, p) =>
                            sum +
                            Number(p.stock_quantity) * Number(p.unit_price),
                          0,
                        ) || 0,
                      )}
                    </strong>
                  </div>
                </div>
              </div>
              <div className="page-tabs">
                <button
                  className={stockTab === "parts" ? "active" : ""}
                  onClick={() => setStockTab("parts")}
                >
                  Pièces détachées <span>{data.parts?.length || 0}</span>
                </button>
                <button
                  className={stockTab === "stock-movements" ? "active" : ""}
                  onClick={() => setStockTab("stock-movements")}
                >
                  Historique des mouvements{" "}
                  <span>{data["stock-movements"]?.length || 0}</span>
                </button>
              </div>
              <ResourcePage
                key={stockTab}
                resource={stockTab}
                {...common}
                hideHeading
              />
            </>
          ) : allowedPage === "scanner" ? (
            <Scanner
              onEquipment={(id) =>
                navigate(
                  "equipment",
                  data.equipment?.find((e) => e.id === id)?.serial_number || "",
                )
              }
            />
          ) : allowedPage === "catalogue" ? (
            <EatonCatalogue user={user} />
          ) : allowedPage === "integrations" ? (
            <Integrations />
          ) : resources[allowedPage] ? (
            <ResourcePage
              key={allowedPage}
              resource={allowedPage}
              {...common}
              externalSearch={externalSearch}
            />
          ) : (
            <Empty
              title="Cette page n’existe pas"
              action={
                <button
                  className="button primary"
                  onClick={() => navigate("dashboard")}
                >
                  Retour au tableau de bord
                </button>
              }
            />
          )}
          <footer className="app-footer">
            <span>
              PowerCare <b>by TVM</b> <i>·</i> UPS Service Suite
            </span>
            <span>
              <ShieldCheck size={12} />
              Votre activité, en toute confiance
            </span>
          </footer>
        </main>
      </div>
      {currentRequestDetail && (
        <Modal
          title="Dossier SAV"
          subtitle={
            user.role === "client"
              ? callPrimary(currentRequestDetail, user.role)
              : `N° d’appel TVM ${callIdentity(currentRequestDetail).tvm || "non renseigné"}`
          }
          onClose={closeRequestDetail}
          wide
        >
          <RequestDossier
            key={currentRequestDetail.id}
            record={currentRequestDetail}
            data={data}
            user={user}
            onChanged={reload}
            onOpenExchange={() => {
              setRequestDetail(null);
              navigate("exchange", currentRequestDetail.reference);
            }}
            onOpenDispatch={() => {
              setRequestDetail(null);
              navigate("dispatch", currentRequestDetail.reference);
            }}
            onEditRequest={(freshRecord) => {
              setRequestDetail(null);
              setModal({ resource: "requests", record: freshRecord });
            }}
            onCreateIntervention={(kind) => {
              setRequestDetail(null);
              setModal({
                resource: "interventions",
                values: { service_request: currentRequestDetail.id, kind },
              });
            }}
            onOpenIntervention={(entry) => {
              setRequestDetail(null);
              setDetail(entry);
            }}
            onEditIntervention={(entry) => {
              setRequestDetail(null);
              setModal({ resource: "interventions", record: entry });
            }}
          />
        </Modal>
      )}
      {modal && (
        <EditForm
          modal={modal}
          data={data}
          user={user}
          onClose={closeModal}
          onSaved={saved}
        />
      )}{" "}
      {currentDetail && (
        <InterventionDetail
          record={currentDetail}
          user={user}
          data={data}
          onClose={closeDetail}
          onEdit={openModal}
          onSaved={saved}
        />
      )}{" "}
      {searchQuery && (
        <GlobalSearch
          query={searchQuery}
          user={user}
          onClose={closeSearch}
          onNavigate={navigate}
          onIntervention={setDetail}
        />
      )}{" "}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={19} />
          {toast}
          <button
            onClick={() => setToast("")}
            aria-label="Fermer la notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
