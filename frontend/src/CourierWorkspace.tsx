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
  CheckCircle2,
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
import { api, dateFR, type User } from "./api";
import CallReference from "./CallReference";
import CourierReception from "./CourierReception";
import SimpleSAVIntake from "./SimpleSAVIntake";
import { HandoffReceipt } from "./ClientPickups";
import NotificationCenter from "./NotificationCenter";
import CourierRouting from "./CourierRouting";
import CourierReadyQueue from "./CourierReadyQueue";
import CourierDeliveryNotes from "./CourierDeliveryNotes";
import CourierMissionAcceptance from "./CourierMissionAcceptance";
import CourierNotificationBell from "./CourierNotificationBell";
import CourierHubNavigation from "./CourierHubNavigation";
import { readCourierCollection } from "./courierHub";
import {
  logisticsReference,
  isCurrentMissionAccepted,
  pickupLabels,
  type LogisticsBootstrap,
  type OutboundJob,
  type Pickup,
  type ReadyQueueItem,
} from "./logistics";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
const courierNavigation = [
  { key: "home", label: "À livrer", icon: Truck },
  { key: "routes", label: "À récupérer", icon: MapPin },
  { key: "receive", label: "Réception", icon: ScanLine },
  { key: "ready", label: "Prêts", icon: Truck },
  { key: "returns", label: "Historique", icon: CheckCircle2 },
];
export default function CourierWorkspace({
  user,
  bootstrap: suppliedBootstrap,
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
  const bootstrap = suppliedBootstrap?.user.id === user.id &&
    suppliedBootstrap.user.client === user.client &&
    (!user.courier_kind || suppliedBootstrap.user.courier_kind === user.courier_kind)
    ? suppliedBootstrap : null;
  const currentUser = bootstrap?.user.id === user.id ? bootstrap.user : user;
  const external = currentUser.courier_kind === "client";
  const canReadyQueue =
    !external && bootstrap?.capabilities?.can_ready_queue === true;
  const canPrepareBL = !external && Boolean(bootstrap);
  const canPickups = !external && bootstrap?.capabilities?.can_pickups === true;
  const canReceive =
    !external &&
    bootstrap?.capabilities?.can_receive === true &&
    bootstrap?.capabilities?.can_lookup === true;
  const navigation = courierNavigation.filter(
    (item) => (item.key !== "receive" || canReceive) &&
      (item.key !== "routes" || canPickups) &&
      (item.key !== "ready" || canReadyQueue),
  );
  const view = navigation.some((item) => `courier/${item.key}` === page)
    ? page.split("/")[1]
    : "home";
  const [pickups, setPickups] = useState<Pickup[]>([]);
  const [jobs, setJobs] = useState<OutboundJob[]>([]);
  const [readyRows, setReadyRows] = useState<ReadyQueueItem[]>([]);
  const [failedLists, setFailedLists] = useState<string[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listErrors, setListErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [selectedPickup, setSelectedPickup] = useState<Pickup | null>(null);
  const [selectedJob, setSelectedJob] = useState<OutboundJob | null>(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [simpleIntakeOpen, setSimpleIntakeOpen] = useState(false);
  const [busyPickup, setBusyPickup] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [readyTab, setReadyTab] = useState<"shared" | "missions" | "notes">(
    "missions",
  );
  const [acceptingJob, setAcceptingJob] = useState<OutboundJob | null>(null);
  const [noteJobIds, setNoteJobIds] = useState<number[]>([]);
  const [historyTab, setHistoryTab] = useState<"deliveries" | "pickups">("deliveries");
  const listController = useRef<AbortController | null>(null);
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
    controller.current?.abort();
    setPickups([]);
    setJobs([]);
    setReadyRows([]);
    setSelectedPickup(null);
    setSelectedJob(null);
    setAcceptingJob(null);
    setSimpleIntakeOpen(false);
    setBusyPickup(null);
    setNotice("");
  }, [user.id, external, user.client]);
  useEffect(() => {
    const pending = new AbortController();
    listController.current = pending;
    setListLoading(true);
    setListErrors([]);
    setFailedLists([]);
    const tasks = [
      {
        key: "outbound",
        read: () => readCourierCollection<OutboundJob>("logistics/outbound/", pending.signal),
      },
      ...(canPickups
        ? [
            {
              key: "pickups",
              read: () => readCourierCollection<Pickup>("logistics/pickups/", pending.signal),
            },
          ]
        : []),
      ...(canReadyQueue ? [{
        key: "ready",
        read: () => readCourierCollection<ReadyQueueItem>("logistics/ready-queue/", pending.signal),
      }] : []),
    ];
    if (!canPickups) setPickups([]);
    if (!canReadyQueue) setReadyRows([]);
    void Promise.allSettled(
      tasks.map(async (task) => [task.key, await task.read()] as const),
    ).then((results) => {
      if (pending.signal.aborted) return;
      const failures: string[] = [];
      const failed: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          if (result.value[0] === "pickups")
            setPickups(result.value[1] as Pickup[]);
          else if (result.value[0] === "ready") setReadyRows(result.value[1] as ReadyQueueItem[]);
          else setJobs(result.value[1] as OutboundJob[]);
        } else {
          failed.push(tasks[index].key);
          failures.push(
            result.reason instanceof Error
              ? result.reason.message
              : "Chargement de la tournée impossible.",
          );
        }
      });
      setListErrors(failures);
      setFailedLists(failed);
      setListLoading(false);
    });
    return () => pending.abort();
  }, [revision, view, user.id, external, user.client, canPickups, canReadyQueue]);
  useEffect(() => {
    const poll = () => {
      if (document.visibilityState === "visible")
        setRevision((value) => value + 1);
    };
    const timer = window.setInterval(poll, 30000);
    document.addEventListener("visibilitychange", poll);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [user.id]);
  function navigateWorkspace(target: string) {
    if (target === `courier/${view}`) setRevision((value) => value + 1);
    onNavigate(target);
  }
  async function missionChanged(job: OutboundJob) {
    listController.current?.abort();
    setJobs((rows) =>
      rows.some((row) => row.id === job.id)
        ? rows.map((row) => (row.id === job.id ? job : row))
        : [...rows, job],
    );
    setReadyRows((rows) => rows.map((row) => row.id === job.service_request ? {
      ...row, job: job.id, assigned_courier: job.assigned_courier,
      assigned_courier_name: job.assigned_courier_name,
      routing_status: "reserved", can_claim: false,
      expected_revision: job.assignment_revision ?? row.expected_revision,
      accepted: job.accepted, accepted_at: job.accepted_at,
      accepted_revision: job.accepted_revision,
      assignment_revision: job.assignment_revision,
    } : row));
    await refreshed();
  }
  async function refreshed() {
    setRevision((value) => value + 1);
    try {
      await onReload();
    } catch (failure) {
      if (mounted.current)
        setListErrors([
          (failure as Error).message ||
            "L’actualisation de l’espace livreur a échoué.",
        ]);
    }
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
  const ownPickups = canPickups ? pickups.filter((pickup) => pickup.assigned_courier === user.id) : [];
  const activePickups = ownPickups.filter((pickup) => !["received", "cancelled"].includes(pickup.status));
  const ownJobs = jobs.filter((job) => job.assigned_courier === user.id &&
    (!external || job.client.id === currentUser.client));
  const activeJobs = ownJobs.filter((job) => job.status === "assigned" && job.active !== false && !job.handed_over_at)
    .sort((first, second) => Number(isCurrentMissionAccepted(first)) - Number(isCurrentMissionAccepted(second)) || first.id - second.id);
  const historicalJobs = ownJobs.filter((job) => job.status === "completed");
  const historicalPickups = ownPickups.filter((pickup) => ["received", "cancelled"].includes(pickup.status));
  const availableReady = canReadyQueue ? readyRows.filter((row) => row.routing_status === "available" && row.can_claim) : [];
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
                navigateWorkspace("courier/receive");
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
        {job.status === "assigned" && (
          <div
            className={`courier-mission-status ${isCurrentMissionAccepted(job) ? "mission-accepted" : "mission-awaiting"}`}
          >
            <CheckCircle2 size={15} />
            {isCurrentMissionAccepted(job)
              ? "Mission acceptée"
              : "Affectée · acceptation à confirmer"}
          </div>
        )}
        {job.can_accept && (
          <button
            type="button"
            className="button primary"
            onClick={() => setAcceptingJob(job)}
          >
            Accepter la mission
          </button>
        )}
        {canPrepareBL &&
          job.status === "assigned" &&
          job.can_handoff &&
          isCurrentMissionAccepted(job) && (
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setNoteJobIds([job.id]);
                setReadyTab("notes");
                navigateWorkspace("courier/ready");
              }}
            >
              Préparer le BL
            </button>
          )}
        {job.status === "completed" ? (
          <HandoffReceipt job={job} />
        ) : (
          job.can_handoff &&
          isCurrentMissionAccepted(job) && (
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
  function ownMissions() {
    if (listLoading)
      return (
        <div className="loading-state">
          <LoaderCircle className="spin" size={18} />
          Chargement de la tournée…
        </div>
      );
    const pickupView = view === "routes" || (view === "returns" && historyTab === "pickups");
    const shownPickups = view === "returns" ? historicalPickups : activePickups;
    const shownJobs = view === "returns" ? historicalJobs : activeJobs;
    const count = pickupView ? shownPickups.length : shownJobs.length;
    return (
      <>
        <div className="courier-section-heading">
          <h2>
            {view === "returns" ? pickupView ? "Enlèvements terminés" : "Remises effectuées" : pickupView ? "Mes enlèvements" : "Mes livraisons"}
          </h2>
          <span>{failedLists.includes(pickupView ? "pickups" : "outbound") ? "Nombre indisponible" : `${count} mission(s)`}</span>
        </div>
        {view !== "returns" && (
          <p className="courier-hub-missions-description">
            {pickupView ? "Vos collectes chez les clients et leurs clients finaux. La prise en charge du transport ne confirme pas l’arrivée à l’atelier."
              : "Livraisons et retours client affectés à votre compte. Acceptez la mission avant de confirmer la remise physique."}
          </p>
        )}
        <div className="courier-job-list">
          {pickupView ? shownPickups.map(pickupCard) : shownJobs.map(jobCard)}
        </div>
        {count === 0 && !failedLists.includes(pickupView ? "pickups" : "outbound") && (
          <div className="courier-empty-state">
            <Truck size={30} />
            <h3>Aucune mission dans cette vue</h3>
            <p>{view === "returns" ? "Les opérations terminées apparaissent dans cet historique." : "Les transports affectés à votre compte apparaissent ici."}</p>
          </div>
        )}
      </>
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
          <CourierNotificationBell
            userId={user.id}
            onClick={() => setNotificationsOpen(true)}
          />
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
        <CourierHubNavigation
          deliveries={activeJobs.length}
          available={availableReady.length}
          awaitingAcceptance={activeJobs.filter((job) => !isCurrentMissionAccepted(job)).length}
          pickups={activePickups.length}
          pickupsInTransit={activePickups.filter((pickup) => pickup.status === "collected").length}
          loading={listLoading}
          sharedLoading={listLoading}
          hasDeliveryError={failedLists.includes("outbound")}
          hasPickupError={failedLists.includes("pickups")}
          hasSharedError={failedLists.includes("ready")}
          canPickups={canPickups}
          canReadyQueue={canReadyQueue}
          view={view}
          onDeliveries={() => {
            setReadyTab("missions");
            navigateWorkspace("courier/home");
          }}
          onPickups={() => navigateWorkspace("courier/routes")}
        />
        <div className="courier-page-heading">
          <div>
            <span className="eyebrow">VOTRE ESPACE LIVREUR</span>
            <h1>
              {view === "home"
                ? "À livrer"
                : view === "routes"
                  ? "À récupérer"
                  : view === "receive"
                    ? "Réception SAV"
                    : view === "ready"
                      ? "Prêts à livrer"
                      : "Historique des transports"}
            </h1>
            <p>
              {view === "home"
                ? external
                  ? "Vos livraisons et retours pour votre société."
                  : "Vos livraisons et retours, puis les onduleurs disponibles de tous les clients."
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
        {canPrepareBL && view !== "receive" && (
          <div className="courier-hub-secondary-actions">
            <button
              type="button"
              className="button secondary small"
              onClick={() => {
                setNoteJobIds([]);
                setReadyTab("notes");
                navigateWorkspace("courier/ready");
              }}
            >
              <PackageCheck size={16} />
              Préparer un bon de livraison
            </button>
          </div>
        )}
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
        {view === "receive" ? (
          <CourierReception
            key={selectedPickup?.id || "walk-in"}
            clients={bootstrap?.clients || []}
            pickup={selectedPickup}
            onReceived={refreshed}
            onClearPickup={() => setSelectedPickup(null)}
          />
        ) : (view === "ready" || view === "home") && (canReadyQueue || canPrepareBL) ? (
          <>
            <div
              className="courier-ready-tabs"
              role="group"
              aria-label="Vues des livraisons"
            >
              {canReadyQueue && (
                <button
                  type="button"
                  aria-pressed={readyTab === "shared"}
                  className={readyTab === "shared" ? "active" : ""}
                  onClick={() => {
                    setReadyTab("shared");
                    setRevision((value) => value + 1);
                  }}
                >
                  File partagée
                </button>
              )}
              <button
                type="button"
                aria-pressed={
                  readyTab === "missions" ||
                  (readyTab === "shared" && !canReadyQueue)
                }
                className={
                  readyTab === "missions" ||
                  (readyTab === "shared" && !canReadyQueue)
                    ? "active"
                    : ""
                }
                onClick={() => {
                  setReadyTab("missions");
                  setRevision((value) => value + 1);
                }}
              >
                Mes livraisons
              </button>
              {canPrepareBL && (
                <button
                  type="button"
                  aria-pressed={readyTab === "notes"}
                  className={readyTab === "notes" ? "active" : ""}
                  onClick={() => {
                    setNoteJobIds([]);
                    setReadyTab("notes");
                  }}
                >
                  Bons de livraison
                </button>
              )}
            </div>
            {readyTab === "shared" && canReadyQueue ? (
              <CourierReadyQueue
                user={bootstrap?.user || user}
                jobs={jobs}
                Dialog={Dialog}
                rows={readyRows}
                loading={listLoading}
                error={failedLists.includes("ready") ? "La file des prêts n’a pas pu être actualisée." : ""}
                onReload={refreshed}
                onChanged={missionChanged}
                onAccept={setAcceptingJob}
              />
            ) : readyTab === "notes" && canPrepareBL ? (
              <CourierDeliveryNotes
                user={bootstrap?.user || user}
                jobs={jobs}
                Dialog={Dialog}
                initialJobIds={noteJobIds}
                refreshKey={revision}
              />
            ) : (
              <>
                <section className="courier-hub-in-progress" aria-label="Livraisons en cours">
                  {ownMissions()}
                </section>
                {view === "home" && canReadyQueue && (
                  <CourierReadyQueue
                    key="home-available"
                    user={currentUser}
                    jobs={jobs}
                    Dialog={Dialog}
                    rows={readyRows}
                    loading={listLoading}
                    error={failedLists.includes("ready") ? "La file des prêts n’a pas pu être actualisée." : ""}
                    onReload={refreshed}
                    initialFilter="available"
                    onChanged={missionChanged}
                    onAccept={setAcceptingJob}
                  />
                )}
              </>
            )}
          </>
        ) : view === "returns" ? (
          <>
            <div className="courier-ready-tabs" role="group" aria-label="Historique des transports">
              <button type="button" aria-pressed={historyTab === "deliveries"} className={historyTab === "deliveries" ? "active" : ""} onClick={() => setHistoryTab("deliveries")}>
                Livraisons et retours
              </button>
              {canPickups && <button type="button" aria-pressed={historyTab === "pickups"} className={historyTab === "pickups" ? "active" : ""} onClick={() => setHistoryTab("pickups")}>
                Enlèvements
              </button>}
            </div>
            {ownMissions()}
          </>
        ) : (
          ownMissions()
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
            onClick={() => {
              if (item.key === "ready") setReadyTab("shared");
              if (item.key === "home") setReadyTab("missions");
              navigateWorkspace(`courier/${item.key}`);
            }}
          >
            <item.icon size={21} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      {acceptingJob && (
        <CourierMissionAcceptance
          job={acceptingJob}
          currentJob={jobs.find((job) => job.id === acceptingJob.id)}
          user={user}
          Dialog={Dialog}
          onClose={() => setAcceptingJob(null)}
          onRefresh={refreshed}
          onSaved={async (job) => {
            await missionChanged(job);
            setAcceptingJob(null);
            setNotice(
              "Mission acceptée. Préparez le transport puis confirmez séparément la remise au client.",
            );
          }}
        />
      )}
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
            <NotificationCenter
              key={user.id}
              user={user}
              onOpenReady={() => {
                setNotificationsOpen(false);
                setReadyTab("shared");
                navigateWorkspace("courier/ready");
                void refreshed();
              }}
              onOpenMissions={() => {
                setNotificationsOpen(false);
                setReadyTab("missions");
                navigateWorkspace("courier/home");
                void refreshed();
              }}
            />
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
          body: JSON.stringify({
            recipient_name: recipient.trim(),
            ...(typeof job.assignment_revision === "number"
              ? { expected_revision: job.assignment_revision }
              : {}),
          }),
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
