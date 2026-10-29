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
  CheckCircle2,
  Info,
  LoaderCircle,
  RefreshCw,
  Search,
  Truck,
  UserCheck,
} from "lucide-react";
import { api, type User } from "./api";
import CallReference from "./CallReference";
import {
  isCurrentMissionAccepted,
  type OutboundJob,
  type ReadyQueueItem,
} from "./logistics";
import "./CourierReadyQueue.css";

type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
export default function CourierReadyQueue({
  user,
  jobs,
  Dialog,
  rows,
  loading,
  error,
  onReload,
  initialFilter = "all",
  onChanged,
  onAccept,
}: {
  user: User;
  jobs: OutboundJob[];
  Dialog: ComponentType<DialogProps>;
  rows: ReadyQueueItem[];
  loading: boolean;
  error: string;
  onReload: () => Promise<void>;
  initialFilter?: "all" | "available";
  onChanged: (job: OutboundJob) => Promise<void>;
  onAccept: (job: OutboundJob) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [client, setClient] = useState("");
  const [filter, setFilter] = useState<string>(initialFilter);
  const [selected, setSelected] = useState<ReadyQueueItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const writeController = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const canRead = user.role === "courier" && user.courier_kind !== "client";
  async function load() {
    if (canRead) await onReload();
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      writeController.current?.abort();
    };
  }, [user.id, canRead]);
  const current = selected ? rows.find((row) => row.id === selected.id) : null;
  const stale = Boolean(
    selected &&
      (!current ||
        !current.can_claim ||
        current.expected_revision !== selected.expected_revision ||
        current.equipment !== selected.equipment ||
        current.serial_number !== selected.serial_number ||
        current.assigned_courier !== selected.assigned_courier),
  );
  async function claim() {
    if (
      !selected ||
      stale ||
      saving ||
      submitting.current ||
      !canRead ||
      !selected.can_claim ||
      selected.routing_status !== "available"
    )
      return;
    submitting.current = true;
    const request = new AbortController();
    writeController.current = request;
    setSaving(true);
    setSaveError("");
    setNotice("");
    try {
      const job = await api<OutboundJob>(
        `logistics/ready-queue/${selected.id}/claim/`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_revision: selected.expected_revision,
          }),
          signal: request.signal,
        },
      );
      if (!mounted.current || request.signal.aborted) return;
      setSelected(null);
      setNotice(
        "Livraison prise en charge et mission acceptée. La remise au client reste à confirmer séparément.",
      );
      try {
        await onChanged(job);
      } catch {
        if (mounted.current && !request.signal.aborted)
          setNotice(
            "La livraison est prise en charge. Actualisez vos missions pour recharger les autres informations.",
          );
      }
    } catch (failure) {
      if (mounted.current && !request.signal.aborted) {
        setSaveError((failure as Error).message);
        await load();
      }
    } finally {
      submitting.current = false;
      if (mounted.current && !request.signal.aborted) setSaving(false);
    }
  }
  if (!canRead) return null;
  const clients = [
    ...new Map(rows.map((row) => [row.client.id, row.client])).values(),
  ].sort((a, b) => a.name.localeCompare(b.name, "fr"));
  const shown = rows.filter(
    (row) =>
      (!client || row.client.id === Number(client)) &&
      [
        row.call_number,
        row.client_reference,
        row.client.name,
        row.serial_number,
        row.brand,
        row.model,
      ]
        .join(" ")
        .toLocaleLowerCase("fr")
        .includes(query.toLocaleLowerCase("fr")) &&
      (filter === "all" ||
        (filter === "available" && row.routing_status === "available") ||
        (filter === "mine" && row.assigned_courier === user.id) ||
        (filter === "reserved" && row.routing_status === "reserved")),
  );
  return (
    <section className="courier-ready-queue">
      <div className="courier-ready-heading">
        <div>
          <h2>File partagée des prêts à livrer</h2>
          <p>
            Les onduleurs prêts de tous les clients. Une mission déjà affectée
            reste réservée à son livreur.
          </p>
        </div>
        <button
          type="button"
          className="button secondary small"
          onClick={() => void load()}
          disabled={loading || saving}
        >
          <RefreshCw size={16} className={loading ? "spin" : ""} />
          Actualiser la file
        </button>
      </div>
      <div className="courier-ready-filters">
        <div className="field">
          <label htmlFor={`${id}-query`}>
            Rechercher dans les prêts à livrer
          </label>
          <div className="courier-ready-search">
            <Search size={17} />
            <input
              id={`${id}-query`}
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={200}
              placeholder="N° SAV, n° client, série, modèle…"
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor={`${id}-client`}>Client des prêts à livrer</label>
          <select
            id={`${id}-client`}
            className="input"
            value={client}
            onChange={(event) => setClient(event.target.value)}
          >
            <option value="">Tous les clients</option>
            {clients.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-filter`}>Disponibilité des livraisons</label>
          <select
            id={`${id}-filter`}
            className="input"
            value={filter}
            onChange={(event) => setFilter(event.target.value as typeof filter)}
          >
            <option value="all">Tous les prêts</option>
            <option value="available">Disponibles</option>
            <option value="mine">Mes missions</option>
            <option value="reserved">Déjà affectés</option>
          </select>
        </div>
      </div>
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={17} />
          {error}
        </div>
      )}
      {notice && (
        <div className="success-box" role="status">
          <CheckCircle2 size={17} />
          {notice}
        </div>
      )}
      {error && !rows.length ? null : loading && !rows.length ? (
        <div className="loading-state" role="status">
          <LoaderCircle className="spin" size={20} />
          Chargement des onduleurs prêts…
        </div>
      ) : !shown.length ? (
        <div className="courier-empty-state">
          <Truck size={29} />
          <h3>Aucun onduleur dans cette sélection</h3>
          <p>Les équipements réellement prêts apparaîtront dans cette file.</p>
        </div>
      ) : (
        <>
          <p className="courier-ready-count">
            {shown.length} onduleur{shown.length > 1 ? "s" : ""} prêt
            {shown.length > 1 ? "s" : ""}
          </p>
          <div className="courier-ready-grid">
            {shown.map((row) => {
              const ownJob = jobs.find(
                (job) => job.id === row.job && job.assigned_courier === user.id,
              );
              const mine = row.assigned_courier === user.id;
              const accepted = ownJob
                ? isCurrentMissionAccepted(ownJob)
                : row.accepted === true;
              return (
                <article key={row.id} className="courier-ready-card">
                  <div className="courier-ready-card-heading">
                    <h3>{row.client.name}</h3>
                    <span
                      className={`courier-ready-badge ${row.routing_status === "available" ? "ready-available" : mine ? "ready-mine" : "ready-reserved"}`}
                    >
                      {row.routing_status === "available"
                        ? "Disponible"
                        : mine
                          ? "Ma mission"
                          : "Affecté"}
                    </span>
                  </div>
                  <strong className="courier-ready-serial">
                    {row.serial_number}
                  </strong>
                  <p>
                    {row.brand} · {row.model || "Modèle non renseigné"}
                  </p>
                  <CallReference record={row} role={user.role} compact />
                  <div className="courier-ready-assignee">
                    <Truck size={16} />
                    <span>
                      {row.routing_status === "available"
                        ? "Aucun livreur affecté"
                        : `Affecté à ${row.assigned_courier_name || "un livreur"}`}
                      {row.routing_status === "reserved" && (
                        <small>
                          {accepted
                            ? "Mission acceptée"
                            : "Acceptation à confirmer"}
                        </small>
                      )}
                    </span>
                  </div>
                  {row.can_claim && row.routing_status === "available" && (
                    <button
                      className="button primary"
                      type="button"
                      disabled={saving}
                      onClick={() => {
                        setSelected(row);
                        setSaveError("");
                      }}
                    >
                      <UserCheck size={17} />
                      Prendre la livraison
                    </button>
                  )}
                  {mine && ownJob?.can_accept && (
                    <button
                      className="button primary"
                      type="button"
                      onClick={() => onAccept(ownJob)}
                    >
                      Accepter la mission
                    </button>
                  )}
                  {mine && accepted && (
                    <p className="courier-ready-accepted">
                      <CheckCircle2 size={15} />
                      Mission acceptée · disponible dans vos livraisons
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </>
      )}
      {selected && (
        <Dialog
          title="Prendre la livraison"
          subtitle={selected.call_number}
          onClose={() => {
            if (!saving) setSelected(null);
          }}
        >
          <div className="courier-mission-confirm">
            <Truck size={30} />
            <h3>Confirmer la prise de cette livraison ?</h3>
            <p>
              <strong>{selected.client.name}</strong>
              <br />
              {selected.serial_number} · {selected.model}
            </p>
            <CallReference record={selected} role={user.role} compact />
            <div className="courier-mission-info">
              <Info size={17} />
              Vous devenez le livreur affecté et vous acceptez la mission. Cette
              action ne confirme aucune remise au client.
            </div>
            {stale && (
              <div className="courier-ready-warning" role="status">
                Cette disponibilité a changé. Fermez la confirmation et relisez
                la file actualisée.
              </div>
            )}
            {saveError && (
              <div className="error-box" role="alert">
                <AlertCircle size={17} />
                {saveError}
              </div>
            )}
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="button secondary"
              onClick={() => setSelected(null)}
              disabled={saving}
            >
              Annuler
            </button>
            <button
              type="button"
              className="button primary"
              disabled={saving || stale}
              onClick={() => void claim()}
            >
              {saving && <LoaderCircle className="spin" size={17} />}Oui
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
