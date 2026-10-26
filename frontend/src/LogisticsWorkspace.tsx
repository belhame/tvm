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
  CheckCircle2,
  LoaderCircle,
  MapPin,
  PackageCheck,
  Search,
  Truck,
  Users,
} from "lucide-react";
import { api, dateFR, listResult, type RecordData, type User } from "./api";
import CallReference from "./CallReference";
import CourierReception from "./CourierReception";
import { HandoffReceipt } from "./ClientPickups";
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
type Destination = {
  delivery_address: string;
  contact_name: string;
  contact_phone: string;
};
export default function LogisticsWorkspace({
  user,
  clients,
  Dialog,
}: {
  user: User;
  clients: RecordData[];
  Dialog: ComponentType<DialogProps>;
}) {
  const id = useId();
  const [bootstrap, setBootstrap] = useState<LogisticsBootstrap | null>(null);
  const [pickups, setPickups] = useState<Pickup[]>([]);
  const [jobs, setJobs] = useState<OutboundJob[]>([]);
  const [candidates, setCandidates] = useState<RecordData[]>([]);
  const [tab, setTab] = useState("pickups");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [destinations, setDestinations] = useState<Record<string, Destination>>(
    {},
  );
  const [cancellation, setCancellation] = useState<OutboundJob | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [receptionOpen, setReceptionOpen] = useState(false);
  const [receivePickup, setReceivePickup] = useState<Pickup | null>(null);
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
    setLoading(true);
    setErrors([]);
    const endpoints = [
      "logistics/bootstrap/",
      "logistics/pickups/",
      "logistics/outbound/",
      "logistics/dispatch-candidates/",
    ];
    void Promise.allSettled(
      endpoints.map((endpoint) => api(endpoint, { signal: pending.signal })),
    ).then((results) => {
      if (pending.signal.aborted) return;
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "rejected")
          failures.push(
            result.reason instanceof Error
              ? result.reason.message
              : "Chargement de la logistique impossible.",
          );
        else if (index === 0) setBootstrap(result.value);
        else if (index === 1) setPickups(listResult(result.value) as Pickup[]);
        else if (index === 2)
          setJobs(listResult(result.value) as OutboundJob[]);
        else setCandidates(listResult(result.value));
      });
      setErrors(failures);
      setLoading(false);
    });
    return () => pending.abort();
  }, [revision, user.id]);
  function destination(record: RecordData): Destination {
    const key = String(record.id);
    if (destinations[key]) return destinations[key];
    const client = clients.find((item) => item.id === record.client?.id);
    return {
      delivery_address:
        record.delivery_address ??
        [client?.address, client?.postal_code, client?.city, client?.country]
          .filter(Boolean)
          .join(", "),
      contact_name: record.contact_name ?? client?.contact_name ?? "",
      contact_phone: record.contact_phone ?? client?.phone ?? "",
    };
  }
  async function cancelTransport(event: FormEvent) {
    event.preventDefault();
    if (!cancellation || !cancelReason.trim() || busy) return;
    const pending = new AbortController();
    controller.current = pending;
    setBusy(`cancel:${cancellation.id}`);
    setErrors([]);
    try {
      await api(`logistics/outbound/${cancellation.id}/cancel/`, {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({ reason: cancelReason.trim() }),
      });
      if (mounted.current && !pending.signal.aborted) {
        setCancellation(null);
        setCancelReason("");
        setNotice(
          "Transport annulé. Son affectation est libérée ; le dossier SAV conserve son état.",
        );
        setRevision((value) => value + 1);
      }
    } catch (failure) {
      if (mounted.current && !pending.signal.aborted)
        setErrors([
          failure instanceof Error
            ? failure.message
            : "L’annulation n’a pas pu être confirmée.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setBusy("");
    }
  }
  async function assign(
    kind: "pickup" | "outbound" | "candidate",
    record: RecordData,
  ) {
    const key = `${kind}:${record.id}`;
    const courier = assignments[key] ?? String(record.assigned_courier || "");
    if (!courier || busy) return;
    const pending = new AbortController();
    controller.current = pending;
    setBusy(key);
    setNotice("");
    setErrors([]);
    const path =
      kind === "candidate"
        ? "logistics/outbound/"
        : kind === "pickup"
          ? `logistics/pickups/${record.id}/assign/`
          : `logistics/outbound/${record.id}/assign/`;
    try {
      await api(path, {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({
          courier: Number(courier),
          ...(kind === "candidate"
            ? {
                service_request: record.service_request || record.id,
                ...destination(record),
              }
            : {}),
        }),
      });
      if (mounted.current && !pending.signal.aborted) {
        setNotice(
          "Affectation du transport enregistrée. Le livreur retrouve cette mission dans son espace.",
        );
        setRevision((value) => value + 1);
      }
    } catch (failure) {
      if (mounted.current && !pending.signal.aborted)
        setErrors([
          failure instanceof Error
            ? failure.message
            : "L’affectation n’a pas pu être confirmée.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setBusy("");
    }
  }
  function assignment(
    kind: "pickup" | "outbound" | "candidate",
    record: RecordData,
  ) {
    const key = `${kind}:${record.id}`;
    const value = assignments[key] ?? String(record.assigned_courier || "");
    const target = destination(record);
    return (
      <div className="logistics-assignment">
        <label className="sr-only" htmlFor={`${id}-${key}`}>
          Livreur pour{" "}
          {kind === "pickup"
            ? `l’enlèvement ${record.id}`
            : `le dossier ${record.call_number || record.reference}`}
        </label>
        <select
          id={`${id}-${key}`}
          className="input"
          value={value}
          disabled={!!busy}
          onChange={(event) =>
            setAssignments((current) => ({
              ...current,
              [key]: event.target.value,
            }))
          }
        >
          <option value="">Choisir le livreur…</option>
          {bootstrap?.couriers.map((courier) => (
            <option value={courier.id} key={courier.id}>
              {courier.name}
            </option>
          ))}
        </select>
        {kind === "candidate" && (
          <div className="logistics-delivery-fields">
            {(
              [
                ["delivery_address", "Adresse de livraison"],
                ["contact_name", "Contact de livraison"],
                ["contact_phone", "Téléphone de livraison"],
              ] as const
            ).map(([field, label]) => (
              <div className="form-field" key={field}>
                <label htmlFor={`${id}-${key}-${field}`}>{label}</label>
                {field === "delivery_address" ? (
                  <textarea
                    id={`${id}-${key}-${field}`}
                    className="input"
                    rows={2}
                    maxLength={4000}
                    disabled={!!busy}
                    value={target[field]}
                    onChange={(event) =>
                      setDestinations((current) => ({
                        ...current,
                        [String(record.id)]: {
                          ...target,
                          [field]: event.target.value,
                        },
                      }))
                    }
                  />
                ) : (
                  <input
                    id={`${id}-${key}-${field}`}
                    className="input"
                    type={field === "contact_phone" ? "tel" : "text"}
                    maxLength={field === "contact_phone" ? 40 : 150}
                    disabled={!!busy}
                    value={target[field]}
                    onChange={(event) =>
                      setDestinations((current) => ({
                        ...current,
                        [String(record.id)]: {
                          ...target,
                          [field]: event.target.value,
                        },
                      }))
                    }
                  />
                )}
              </div>
            ))}
            <small>
              Vérifiez la destination et le contact pour rendre la mission
              utilisable par le livreur.
            </small>
          </div>
        )}
        <button
          type="button"
          className="button primary small"
          disabled={!value || !!busy}
          onClick={() => {
            if (!assignments[key] && value) {
              setAssignments((current) => ({ ...current, [key]: value }));
            }
            void assign(kind, record);
          }}
        >
          {busy === key ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <ArrowRight size={15} />
          )}
          {kind === "candidate"
            ? "Affecter le transport"
            : "Enregistrer l’affectation"}
        </button>
      </div>
    );
  }
  const filteredPickups = pickups.filter((row) =>
    JSON.stringify(row)
      .toLocaleLowerCase("fr")
      .includes(query.toLocaleLowerCase("fr")),
  );
  const filteredJobs = jobs.filter((row) =>
    JSON.stringify(row)
      .toLocaleLowerCase("fr")
      .includes(query.toLocaleLowerCase("fr")),
  );
  const alreadyAssigned = new Set(
    jobs
      .filter((job) => job.status !== "cancelled")
      .map((job) => job.service_request),
  );
  const available = candidates.filter(
    (row) =>
      !alreadyAssigned.has(row.service_request || row.id) &&
      JSON.stringify(row)
        .toLocaleLowerCase("fr")
        .includes(query.toLocaleLowerCase("fr")),
  );
  return (
    <div className="logistics-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">ENLÈVEMENTS & TOURNÉES</div>
          <h1>Logistique</h1>
          <p>
            Affectez les enlèvements, les livraisons et les retours aux comptes
            livreurs.
          </p>
        </div>
        <button
          type="button"
          className="button primary"
          onClick={() => {
            setReceivePickup(null);
            setReceptionOpen(true);
          }}
        >
          <PackageCheck size={18} />
          Réception atelier
        </button>
      </div>
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={18} />
          {notice}
        </div>
      )}
      {errors.map((error, index) => (
        <div className="error-box" role="alert" key={index}>
          <AlertCircle size={18} />
          <span>{error}</span>
          <button
            type="button"
            className="button secondary small"
            onClick={() => setRevision((value) => value + 1)}
          >
            Réessayer
          </button>
        </div>
      ))}
      <div className="logistics-summary">
        <div>
          <MapPin size={21} />
          <strong>
            {loading
              ? "—"
              : pickups.filter(
                  (row) => !["received", "cancelled"].includes(row.status),
                ).length}
          </strong>
          <span>Enlèvements en cours</span>
        </div>
        <div>
          <Truck size={21} />
          <strong>
            {loading
              ? "—"
              : candidates.filter(
                  (row) => !alreadyAssigned.has(row.service_request || row.id),
                ).length}
          </strong>
          <span>Transports à affecter</span>
        </div>
        <div>
          <Users size={21} />
          <strong>{bootstrap?.couriers.length ?? "—"}</strong>
          <span>Livreurs disponibles</span>
        </div>
      </div>
      <section className="card logistics-resource-card">
        <div className="resource-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label="Rechercher dans la logistique"
              placeholder="Client, numéro de série, n° TVM ou n° d’appel client…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>
        <div
          className="page-tabs logistics-page-tabs"
          role="group"
          aria-label="Files logistiques"
        >
          <button
            type="button"
            className={tab === "pickups" ? "active" : ""}
            aria-pressed={tab === "pickups"}
            onClick={() => setTab("pickups")}
          >
            Enlèvements <span>{pickups.length}</span>
          </button>
          <button
            type="button"
            className={tab === "candidates" ? "active" : ""}
            aria-pressed={tab === "candidates"}
            onClick={() => setTab("candidates")}
          >
            Livraisons et retours à affecter{" "}
            <span>
              {
                candidates.filter(
                  (row) => !alreadyAssigned.has(row.service_request || row.id),
                ).length
              }
            </span>
          </button>
          <button
            type="button"
            className={tab === "jobs" ? "active" : ""}
            aria-pressed={tab === "jobs"}
            onClick={() => setTab("jobs")}
          >
            Transports affectés <span>{jobs.length}</span>
          </button>
        </div>
        {loading ? (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            Chargement de la logistique…
          </div>
        ) : !bootstrap?.couriers.length ? (
          <div className="logistics-no-courier">
            <Users size={23} />
            <strong>Aucun compte livreur disponible</strong>
            <p>
              Un administrateur peut créer un compte avec le rôle Livreur dans
              Comptes & accès. Aucun compte n’est créé automatiquement.
            </p>
          </div>
        ) : null}
        {!loading && tab === "pickups" && (
          <div className="table-scroll">
            <table className="logistics-pickups-table">
              <thead>
                <tr>
                  <th>Client / matériel</th>
                  <th>État</th>
                  <th>Collecte et contact</th>
                  <th>Livreur</th>
                  <th>Réception</th>
                </tr>
              </thead>
              <tbody>
                {filteredPickups.map((pickup) => (
                  <tr key={pickup.id}>
                    <td>
                      <div className="primary-cell">
                        <span>{pickup.client.name}</span>
                        <small>
                          {pickup.serial_number} · {pickup.model}
                        </small>
                      </div>
                      {pickup.client_reference && (
                        <small>
                          N° d’appel client : {pickup.client_reference}
                        </small>
                      )}
                    </td>
                    <td>
                      <span
                        className={`logistics-status logistics-${pickup.status}`}
                      >
                        {pickupLabels[pickup.status]}
                      </span>
                    </td>
                    <td>
                      <div className="logistics-address-cell">
                        <span>{pickup.pickup_address}</span>
                        <small>
                          {pickup.contact_name} · {pickup.contact_phone}
                        </small>
                        <small>
                          Demandé le {dateFR(pickup.requested_at, true)}
                        </small>
                      </div>
                    </td>
                    <td>
                      {pickup.can_assign
                        ? assignment("pickup", pickup)
                        : pickup.assigned_courier_name || "Non affecté"}
                    </td>
                    <td>
                      {pickup.received_at ? (
                        <div className="primary-cell">
                          <span>{dateFR(pickup.received_at, true)}</span>
                          <small>{pickup.call_number}</small>
                        </div>
                      ) : pickup.can_receive ? (
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={() => {
                            setReceivePickup(pickup);
                            setReceptionOpen(true);
                          }}
                        >
                          Réceptionner cet enlèvement
                        </button>
                      ) : (
                        "En attente de réception"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!filteredPickups.length && (
              <div className="empty-state">
                <h3>Aucun enlèvement dans cette vue</h3>
                <p>
                  Les demandes créées depuis le portail client apparaissent ici.
                </p>
              </div>
            )}
          </div>
        )}
        {!loading && tab === "candidates" && (
          <div className="table-scroll">
            <table className="logistics-candidates-table">
              <thead>
                <tr>
                  <th>N° d’appel TVM / client</th>
                  <th>Client</th>
                  <th>Matériel à transporter</th>
                  <th>Transport</th>
                  <th>Affectation</th>
                </tr>
              </thead>
              <tbody>
                {available.map((candidate) => (
                  <tr key={candidate.id}>
                    <td>
                      <CallReference
                        record={candidate}
                        role={user.role}
                        compact
                      />
                    </td>
                    <td>{candidate.client?.name || candidate.client_name}</td>
                    <td>
                      <div className="primary-cell">
                        <span>
                          {candidate.serial_number ||
                            candidate.equipment_serial ||
                            "Matériel résolu à l’affectation"}
                        </span>
                        <small>
                          {candidate.model || candidate.equipment_model}
                        </small>
                      </div>
                    </td>
                    <td>
                      {candidate.kind === "return" ||
                      candidate.status === "return_to_client"
                        ? "Retour client"
                        : "Livraison"}
                    </td>
                    <td>{assignment("candidate", candidate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!available.length && (
              <div className="empty-state">
                <h3>Aucun nouveau transport à affecter</h3>
                <p>
                  Seuls les dossiers réellement prêts ou déclarés à retourner au
                  client alimentent cette file.
                </p>
              </div>
            )}
          </div>
        )}
        {!loading && tab === "jobs" && (
          <div className="logistics-outbound-list">
            {filteredJobs.map((job) => (
              <article key={job.id} className="logistics-outbound-card">
                <div>
                  <span className="logistics-status">
                    {job.kind === "return" ? "Retour client" : "Livraison"} ·{" "}
                    {job.status === "completed"
                      ? "Remis"
                      : job.status === "cancelled"
                        ? "Annulé"
                        : "Affecté"}
                  </span>
                  <h3>{job.client.name}</h3>
                  <p>
                    {job.serial_number} · {job.model}
                  </p>
                  <p>
                    {job.delivery_address ||
                      "Adresse de livraison non renseignée"}
                    <br />
                    {job.contact_name || "Contact non renseigné"}
                    {job.contact_phone ? ` · ${job.contact_phone}` : ""}
                  </p>
                  <CallReference
                    record={logisticsReference(
                      job.call_number,
                      job.client_reference,
                    )}
                    role={user.role}
                    compact
                  />
                </div>
                {job.status === "completed" ? (
                  <HandoffReceipt job={job} />
                ) : job.can_assign ? (
                  assignment("outbound", job)
                ) : (
                  <p>{job.assigned_courier_name}</p>
                )}
                {job.blocking_reason && (
                  <p className="logistics-job-blocking">
                    {job.blocking_reason}
                  </p>
                )}
                {job.can_cancel && (
                  <button
                    type="button"
                    className="button secondary small logistics-cancel-transport"
                    disabled={!!busy}
                    onClick={() => {
                      setCancellation(job);
                      setCancelReason("");
                    }}
                  >
                    Annuler ce transport
                  </button>
                )}
              </article>
            ))}
            {!filteredJobs.length && (
              <div className="empty-state">
                <h3>Aucun transport affecté</h3>
                <p>
                  Sélectionnez un dossier dans Livraisons et retours à affecter.
                </p>
              </div>
            )}
          </div>
        )}
      </section>
      {receptionOpen && (
        <Dialog
          title="Réception atelier"
          subtitle="Le scan prépare la réception ; la confirmation enregistre l’arrivée réelle."
          onClose={() => setReceptionOpen(false)}
          wide
        >
          <div className="modal-content">
            <CourierReception
              key={receivePickup?.id || "walk-in"}
              pickup={receivePickup}
              clients={bootstrap?.clients || []}
              onClearPickup={() => setReceivePickup(null)}
              onReceived={async () => {
                setRevision((value) => value + 1);
              }}
            />
          </div>
        </Dialog>
      )}
      {cancellation && (
        <Dialog
          title="Annuler le transport"
          subtitle={cancellation.call_number}
          onClose={() => {
            if (!busy) setCancellation(null);
          }}
        >
          <form onSubmit={cancelTransport}>
            <div className="modal-content">
              <p className="logistics-cancel-explanation">
                L’affectation du transport sera libérée. Le dossier SAV et ses
                validations financières restent conservés.
              </p>
              <div className="form-field">
                <label htmlFor={`${id}-cancel`}>
                  Motif d’annulation du transport
                </label>
                <textarea
                  id={`${id}-cancel`}
                  className="input"
                  required
                  maxLength={4000}
                  rows={3}
                  disabled={!!busy}
                  value={cancelReason}
                  onChange={(event) => setCancelReason(event.target.value)}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="button secondary"
                disabled={!!busy}
                onClick={() => setCancellation(null)}
              >
                Conserver le transport
              </button>
              <button
                type="submit"
                className="button primary"
                disabled={!cancelReason.trim() || !!busy}
              >
                {busy && <LoaderCircle size={16} className="spin" />}Confirmer
                l’annulation du transport
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </div>
  );
}
