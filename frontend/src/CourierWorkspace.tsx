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
  ArrowRight,
  Bell,
  CheckCircle2,
  Home,
  LoaderCircle,
  LogOut,
  MapPin,
  PackageCheck,
  Plus,
  RefreshCw,
  ScanLine,
  Truck,
  Undo2,
  UserRound,
  Zap,
} from "lucide-react";
import { api, dateFR, initials, listResult, type User } from "./api";
import CallReference from "./CallReference";
import CourierReception from "./CourierReception";
import SimpleSAVIntake from "./SimpleSAVIntake";
import { HandoffReceipt } from "./ClientPickups";
import NotificationCenter from "./NotificationCenter";
import CourierRouting from "./CourierRouting";
import {
  logisticsReference,
  pickupLabels,
  type LogisticsBootstrap,
  type OutboundJob,
  type Pickup,
} from "./logistics";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
const courierNavigation = [
  { key: "home", label: "Accueil", icon: Home },
  { key: "routes", label: "Tournées", icon: MapPin },
  { key: "receive", label: "Réception", icon: ScanLine },
  { key: "ready", label: "Prêts", icon: Truck },
  { key: "returns", label: "Retours", icon: Undo2 },
];
export default function CourierWorkspace({
  user,
  bootstrap,
  loading,
  error,
  page,
  onNavigate,
  onReload,
  onLogout,
  logoutBusy,
  Dialog,
  demo,
}: {
  user: User;
  bootstrap: LogisticsBootstrap | null;
  loading: boolean;
  error: string;
  page: string;
  onNavigate: (page: string) => void;
  onReload: () => Promise<void>;
  onLogout: () => Promise<void>;
  logoutBusy: boolean;
  Dialog: ComponentType<DialogProps>;
  demo: boolean;
}) {
  const external = (bootstrap?.user || user).courier_kind === "client";
  const canPickups = !external && bootstrap?.capabilities?.can_pickups === true;
  const canReceive =
    !external &&
    bootstrap?.capabilities?.can_receive === true &&
    bootstrap?.capabilities?.can_lookup === true;
  const navigation = courierNavigation.filter(
    (item) => item.key !== "receive" || canReceive,
  );
  const view = navigation.some((item) => `courier/${item.key}` === page)
    ? page.split("/")[1]
    : "home";
  const [pickups, setPickups] = useState<Pickup[]>([]);
  const [jobs, setJobs] = useState<OutboundJob[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listErrors, setListErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [selectedPickup, setSelectedPickup] = useState<Pickup | null>(null);
  const [selectedJob, setSelectedJob] = useState<OutboundJob | null>(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [simpleIntakeOpen, setSimpleIntakeOpen] = useState(false);
  const [busyPickup, setBusyPickup] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    const pending = new AbortController();
    setListLoading(true);
    setListErrors([]);
    const tasks = [
      {
        key: "outbound",
        read: () => api("logistics/outbound/", { signal: pending.signal }),
      },
      ...(canPickups
        ? [
            {
              key: "pickups",
              read: () => api("logistics/pickups/", { signal: pending.signal }),
            },
          ]
        : []),
    ];
    if (!canPickups) setPickups([]);
    void Promise.allSettled(
      tasks.map(async (task) => [task.key, await task.read()] as const),
    ).then((results) => {
      if (pending.signal.aborted) return;
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          if (result.value[0] === "pickups")
            setPickups(listResult(result.value[1]) as Pickup[]);
          else setJobs(listResult(result.value[1]) as OutboundJob[]);
        } else
          failures.push(
            result.reason instanceof Error
              ? result.reason.message
              : "Chargement de la tournée impossible.",
          );
      });
      setListErrors(failures);
      setListLoading(false);
    });
    return () => pending.abort();
  }, [revision, user.id, canPickups]);
  async function refreshed() {
    setRevision((value) => value + 1);
    await onReload();
  }
  async function collect(pickup: Pickup) {
    if (busyPickup !== null) return;
    const pending = new AbortController();
    controller.current = pending;
    setBusyPickup(pickup.id);
    setListErrors([]);
    try {
      const response = await api<Pickup>(
        `logistics/pickups/${pickup.id}/collect/`,
        { method: "POST", signal: pending.signal, body: "{}" },
      );
      if (!mounted.current || pending.signal.aborted) return;
      setPickups((rows) =>
        rows.map((row) => (row.id === response.id ? response : row)),
      );
      setNotice(
        "Prise en charge du transport enregistrée. La réception à l’atelier reste à confirmer.",
      );
      await onReload();
    } catch (error) {
      if (mounted.current && !pending.signal.aborted)
        setListErrors([
          error instanceof Error
            ? error.message
            : "La prise en charge n’a pas pu être confirmée.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setBusyPickup(null);
    }
  }
  const activePickups = pickups.filter(
    (pickup) => !["received", "cancelled"].includes(pickup.status),
  );
  const shownJobs = jobs.filter(
    (job) =>
      job.status !== "cancelled" &&
      (view === "ready"
        ? job.kind === "delivery"
        : view === "returns"
          ? job.kind === "return"
          : true),
  );
  function pickupCard(pickup: Pickup) {
    return (
      <article className="courier-job-card" key={`pickup:${pickup.id}`}>
        <div className="courier-job-kind">
          <MapPin size={16} />
          <span>Enlèvement</span>
          <span className={`logistics-status logistics-${pickup.status}`}>
            {pickupLabels[pickup.status]}
          </span>
        </div>
        <h3>{pickup.client.name}</h3>
        {pickup.pickup_scope === "end_customer" && (
          <div className="pickup-final-customer">
            <MapPin size={16} />
            <span>
              Client final : <strong>{pickup.end_customer_name}</strong>
            </span>
          </div>
        )}
        <strong className="courier-job-serial">{pickup.serial_number}</strong>
        <p>{pickup.model || "Modèle à identifier à la réception"}</p>
        <div className="courier-job-address">
          <MapPin size={16} />
          <span>{pickup.pickup_address}</span>
        </div>
        <div className="courier-job-contact">
          <UserRound size={16} />
          <span>
            {pickup.contact_name} ·{" "}
            <a href={`tel:${encodeURIComponent(pickup.contact_phone)}`}>
              {pickup.contact_phone}
            </a>
          </span>
        </div>
        {pickup.client_reference && (
          <small>N° d’appel client : {pickup.client_reference}</small>
        )}
        {pickup.collected_at && (
          <small>Pris en charge le {dateFR(pickup.collected_at, true)}</small>
        )}
        <div className="courier-job-actions">
          {pickup.can_collect && (
            <button
              type="button"
              className="button secondary"
              disabled={busyPickup !== null}
              onClick={() => void collect(pickup)}
            >
              {busyPickup === pickup.id ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <Truck size={17} />
              )}
              Prendre en charge l’enlèvement
            </button>
          )}
          {pickup.can_receive && canReceive && (
            <button
              type="button"
              className="button primary"
              onClick={() => {
                setSelectedPickup(pickup);
                onNavigate("courier/receive");
              }}
            >
              <PackageCheck size={17} />
              Réceptionner à l’atelier
            </button>
          )}
        </div>
      </article>
    );
  }
  function jobCard(job: OutboundJob) {
    return (
      <article className="courier-job-card" key={`job:${job.id}`}>
        <div className="courier-job-kind">
          {job.kind === "return" ? <Undo2 size={16} /> : <Truck size={16} />}
          <span>{job.kind === "return" ? "Retour client" : "Livraison"}</span>
          <span className={`logistics-status logistics-${job.status}`}>
            {job.status === "completed"
              ? "Remise enregistrée"
              : "Affectée à votre tournée"}
          </span>
        </div>
        <h3>{job.client.name}</h3>
        <strong className="courier-job-serial">{job.serial_number}</strong>
        <p>
          {job.brand} · {job.model}
        </p>
        <div className="courier-job-address">
          <MapPin size={16} />
          <span>
            {job.delivery_address ||
              "Adresse de livraison à préciser par le responsable"}
          </span>
        </div>
        <div className="courier-job-contact">
          <UserRound size={16} />
          <span>
            {job.contact_name || "Contact à préciser"}
            {job.contact_phone && (
              <>
                {" "}
                ·{" "}
                <a href={`tel:${encodeURIComponent(job.contact_phone)}`}>
                  {job.contact_phone}
                </a>
              </>
            )}
          </span>
        </div>
        <CallReference
          record={logisticsReference(job.call_number, job.client_reference)}
          role={user.role}
          compact
        />
        <CourierRouting record={job} />
        {job.status === "completed" ? (
          <HandoffReceipt job={job} />
        ) : (
          job.can_handoff && (
            <button
              type="button"
              className="button primary courier-handoff-button"
              aria-label={`Confirmer la remise ${job.call_number}`}
              onClick={() => setSelectedJob(job)}
            >
              <CheckCircle2 size={17} />
              Confirmer la remise au client
            </button>
          )
        )}
      </article>
    );
  }
  return (
    <div className="courier-app">
      <header className="courier-header">
        <div className="courier-brand">
          <span>
            <Zap size={23} fill="currentColor" />
          </span>
          <div>
            <strong>PowerCare</strong>
            <small>
              {external ? "Livreur de société cliente" : "Espace Livreur TVM"}
            </small>
          </div>
        </div>
        <div className="courier-header-actions">
          <button
            type="button"
            className="icon-button"
            aria-label="Notifications et rappels"
            onClick={() => setNotificationsOpen(true)}
          >
            <Bell size={20} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Se déconnecter"
            disabled={logoutBusy}
            onClick={() => void onLogout()}
          >
            {logoutBusy ? (
              <LoaderCircle size={19} className="spin" />
            ) : (
              <LogOut size={20} />
            )}
          </button>
        </div>
      </header>
      {demo && (
        <div className="courier-demo-note">
          Environnement de démonstration · Modifications enregistrées sur le
          serveur
        </div>
      )}
      <main className="courier-main">
        {external && (
          <div className="courier-company-scope">
            <UserRound size={18} />
            <span>
              {bootstrap?.clients[0]?.name || "Votre société"} · Uniquement vos
              transports affectés
            </span>
          </div>
        )}
        <div className="courier-page-heading">
          <div>
            <span className="eyebrow">VOTRE ESPACE LIVREUR</span>
            <h1>
              {view === "home"
                ? `Bonjour ${user.first_name || user.username}`
                : view === "routes"
                  ? "Mes tournées"
                  : view === "receive"
                    ? "Réception SAV"
                    : view === "ready"
                      ? "Prêts à livrer"
                      : "Retours au client"}
            </h1>
            <p>
              {view === "home"
                ? external
                  ? "Vos livraisons et retours pour votre société."
                  : "Votre matériel, vos transports et les réceptions du jour."
                : view === "receive"
                  ? "Le scan identifie le matériel ; seule votre confirmation enregistre son arrivée."
                  : "Vos missions affectées, avec confirmation de chaque étape."}
            </p>
          </div>
          <div className="courier-intake-heading-actions">
            {!external && bootstrap && (
              <button
                type="button"
                className="button primary"
                onClick={() => setSimpleIntakeOpen(true)}
              >
                <Plus size={17} />
                Nouvelle demande SAV
              </button>
            )}
            <button
              type="button"
              className="icon-button"
              aria-label="Actualiser mon espace livreur"
              disabled={loading || listLoading}
              onClick={() => void refreshed()}
            >
              <RefreshCw
                size={18}
                className={loading || listLoading ? "spin" : ""}
              />
            </button>
          </div>
        </div>
        {[error, ...listErrors].filter(Boolean).map((message, index) => (
          <div className="error-box" role="alert" key={index}>
            <AlertCircle size={18} />
            <span>{message}</span>
          </div>
        ))}
        {notice && (
          <div className="success-box" role="status">
            <CheckCircle2 size={18} />
            {notice}
          </div>
        )}
        {view === "home" ? (
          <>
            <div
              className={`courier-metrics ${!canPickups ? "courier-metrics-two" : ""}`}
            >
              {canPickups && (
                <button
                  type="button"
                  onClick={() => onNavigate("courier/routes")}
                >
                  <span>
                    <MapPin size={21} />
                  </span>
                  <strong className="metric-value">
                    {bootstrap?.metrics.pickups ?? "—"}
                  </strong>
                  <small>Enlèvements affectés</small>
                </button>
              )}
              <button type="button" onClick={() => onNavigate("courier/ready")}>
                <span>
                  <Truck size={21} />
                </span>
                <strong className="metric-value">
                  {bootstrap?.metrics.ready ?? "—"}
                </strong>
                <small>Prêts à livrer</small>
              </button>
              <button
                type="button"
                onClick={() => onNavigate("courier/returns")}
              >
                <span>
                  <Undo2 size={21} />
                </span>
                <strong className="metric-value">
                  {bootstrap?.metrics.returns ?? "—"}
                </strong>
                <small>Retours affectés</small>
              </button>
            </div>
            {canReceive && (
              <button
                type="button"
                className="courier-reception-shortcut"
                onClick={() => {
                  setSelectedPickup(null);
                  onNavigate("courier/receive");
                }}
              >
                <ScanLine size={29} />
                <div>
                  <strong>Réceptionner un onduleur</strong>
                  <span>Douchette USB, caméra, photo ou saisie manuelle</span>
                </div>
                <ArrowRight size={21} />
              </button>
            )}
            <div className="courier-section-heading">
              <h2>
                {canPickups
                  ? "Prochains enlèvements"
                  : "Mes prochaines remises"}
              </h2>
              <button
                type="button"
                className="text-button"
                onClick={() => onNavigate("courier/routes")}
              >
                Voir ma tournée
                <ArrowRight size={14} />
              </button>
            </div>
            {listLoading ? (
              <div className="loading-state">
                <LoaderCircle size={18} className="spin" />
                Chargement des missions…
              </div>
            ) : !canPickups ? (
              jobs.filter((job) => job.status === "assigned").length ? (
                <div className="courier-job-list">
                  {jobs
                    .filter((job) => job.status === "assigned")
                    .slice(0, 3)
                    .map(jobCard)}
                </div>
              ) : (
                <div className="courier-empty-state">
                  <Truck size={29} />
                  <h3>Aucun transport affecté</h3>
                  <p>
                    Votre société et l’équipe TVM peuvent préparer les
                    prochaines affectations.
                  </p>
                </div>
              )
            ) : activePickups.length ? (
              <div className="courier-job-list">
                {activePickups.slice(0, 3).map(pickupCard)}
              </div>
            ) : (
              <div className="courier-empty-state">
                <MapPin size={29} />
                <h3>Aucun enlèvement en cours</h3>
                <p>Les demandes affectées à votre compte apparaîtront ici.</p>
              </div>
            )}
          </>
        ) : view === "receive" ? (
          <CourierReception
            key={selectedPickup?.id || "walk-in"}
            clients={bootstrap?.clients || []}
            pickup={selectedPickup}
            onReceived={refreshed}
            onClearPickup={() => setSelectedPickup(null)}
          />
        ) : listLoading ? (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            Chargement de la tournée…
          </div>
        ) : (
          <>
            <div className="courier-section-heading">
              <h2>
                {view === "routes"
                  ? canPickups
                    ? "Enlèvements et remises"
                    : "Mes livraisons et retours"
                  : view === "ready"
                    ? "Livraisons affectées"
                    : "Retours affectés"}
              </h2>
              <span>
                {view === "routes"
                  ? activePickups.length + shownJobs.length
                  : shownJobs.length}{" "}
                mission(s)
              </span>
            </div>
            <div className="courier-job-list">
              {view === "routes" && activePickups.map(pickupCard)}
              {shownJobs.map(jobCard)}
            </div>
            {(view === "routes"
              ? activePickups.length + shownJobs.length
              : shownJobs.length) === 0 && (
              <div className="courier-empty-state">
                <Truck size={30} />
                <h3>Aucune mission dans cette vue</h3>
                <p>
                  Votre responsable peut affecter un transport à votre compte
                  livreur.
                </p>
              </div>
            )}
          </>
        )}
      </main>
      <nav
        className="courier-bottom-nav"
        aria-label="Navigation livreur"
        style={{
          gridTemplateColumns: `repeat(${navigation.length}, minmax(0, 1fr))`,
        }}
      >
        {navigation.map((item) => (
          <button
            type="button"
            key={item.key}
            className={view === item.key ? "active" : ""}
            aria-current={view === item.key ? "page" : undefined}
            onClick={() => onNavigate(`courier/${item.key}`)}
          >
            <item.icon size={21} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      {selectedJob && (
        <Dialog
          title="Confirmer la remise au client"
          subtitle={selectedJob.call_number}
          onClose={() => setSelectedJob(null)}
        >
          <HandoffForm
            job={selectedJob}
            onClose={() => setSelectedJob(null)}
            onSaved={async (job) => {
              setSelectedJob(job);
              setJobs((rows) =>
                rows.map((row) => (row.id === job.id ? job : row)),
              );
              await refreshed();
            }}
          />
        </Dialog>
      )}
      {simpleIntakeOpen && !external && (
        <Dialog
          title="Nouvelle demande SAV"
          subtitle="Client et numéro de série. Votre compte livreur est associé automatiquement."
          onClose={() => setSimpleIntakeOpen(false)}
          wide
        >
          <SimpleSAVIntake
            user={bootstrap?.user || user}
            onSaved={refreshed}
            onClose={() => setSimpleIntakeOpen(false)}
          />
        </Dialog>
      )}
      {notificationsOpen && (
        <Dialog
          title="Notifications et rappels"
          onClose={() => setNotificationsOpen(false)}
          wide
        >
          <div className="modal-content">
            <NotificationCenter key={user.id} user={user} />
          </div>
        </Dialog>
      )}
    </div>
  );
}

export function HandoffForm({
  job,
  onClose,
  onSaved,
}: {
  job: OutboundJob;
  onClose: () => void;
  onSaved: (job: OutboundJob) => Promise<void>;
}) {
  const id = useId();
  const [recipient, setRecipient] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      submitting.current ||
      !confirmed ||
      !recipient.trim() ||
      job.status === "completed"
    )
      return;
    const pending = new AbortController();
    controller.current = pending;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await api<OutboundJob>(
        `logistics/outbound/${job.id}/handoff/`,
        {
          method: "POST",
          signal: pending.signal,
          body: JSON.stringify({ recipient_name: recipient.trim() }),
        },
      );
      if (mounted.current && !pending.signal.aborted) await onSaved(result);
    } catch (failure) {
      if (mounted.current && !pending.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "La remise n’a pas pu être confirmée. Réessayez avec le même destinataire.",
        );
    } finally {
      if (mounted.current && !pending.signal.aborted) {
        setSaving(false);
        submitting.current = false;
      }
    }
  }
  return job.status === "completed" ? (
    <>
      <div className="modal-content">
        <HandoffReceipt job={job} />
      </div>
      <div className="modal-footer">
        <button type="button" className="button primary" onClick={onClose}>
          Fermer
        </button>
      </div>
    </>
  ) : (
    <form onSubmit={submit}>
      <div className="modal-content">
        <div className="handoff-equipment">
          <Truck size={24} />
          <div>
            <strong>{job.serial_number}</strong>
            <span>
              {job.model} · {job.client.name}
            </span>
          </div>
        </div>
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        <div className="form-field">
          <label htmlFor={id}>Nom du destinataire</label>
          <input
            id={id}
            className="input"
            required
            maxLength={150}
            value={recipient}
            disabled={saving}
            onChange={(event) => {
              setRecipient(event.target.value);
              setConfirmed(false);
            }}
          />
        </div>
        <label className="courier-physical-confirm">
          <input
            type="checkbox"
            required
            checked={confirmed}
            disabled={saving}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            Je confirme avoir remis physiquement cet onduleur au destinataire
            indiqué.
          </span>
        </label>
        <p className="handoff-server-note">
          La date, l’heure et le compte du livreur sont enregistrés par le
          serveur. Cette déclaration ne constitue pas une signature électronique
          du client.
        </p>
      </div>
      <div className="modal-footer">
        <button
          type="button"
          className="button secondary"
          disabled={saving}
          onClick={onClose}
        >
          Annuler
        </button>
        <button
          type="submit"
          className="button primary"
          disabled={!recipient.trim() || !confirmed || saving}
        >
          {saving ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <CheckCircle2 size={17} />
          )}
          Enregistrer la remise
        </button>
      </div>
    </form>
  );
}
