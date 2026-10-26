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
  ClipboardList,
  LoaderCircle,
  MapPin,
  PackageCheck,
  Plus,
  Truck,
} from "lucide-react";
import { api, dateFR, listResult, type RecordData, type User } from "./api";
import CallReference from "./CallReference";
import NotificationCenter from "./NotificationCenter";
import {
  logisticsReference,
  logisticsUuid,
  pickupLabels,
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
export function HandoffReceipt({ job }: { job: OutboundJob }) {
  return (
    <div className="handoff-receipt">
      <CheckCircle2 size={23} />
      <div>
        <strong>
          {job.handed_over_by_role === "courier"
            ? "Remise enregistrée par le livreur"
            : "Remise enregistrée par l’équipe TVM"}
        </strong>
        <p>Destinataire indiqué : {job.recipient_name}</p>
        <p>
          {job.handed_over_at
            ? dateFR(job.handed_over_at, true)
            : "Date non renseignée"}{" "}
          ·{" "}
          {job.handed_over_by_name ||
            "Auteur indiqué dans le journal du transport"}
        </p>
        <p>Livreur affecté : {job.assigned_courier_name}</p>
        <small>
          Déclaration enregistrée par l’équipe de livraison. Aucune signature
          électronique du client n’a été recueillie.
        </small>
      </div>
    </div>
  );
}
export default function ClientPickups({
  user,
  equipment,
  client,
  Dialog,
}: {
  user: User;
  equipment: RecordData[];
  client?: RecordData;
  Dialog: ComponentType<DialogProps>;
}) {
  const [pickups, setPickups] = useState<Pickup[]>([]);
  const [jobs, setJobs] = useState<OutboundJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [tab, setTab] = useState("pickups");
  const [notice, setNotice] = useState("");
  const [cancelling, setCancelling] = useState<Pickup | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [busy, setBusy] = useState(false);
  const cancelId = useId();
  const mounted = useRef(true);
  const mutationController = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      mutationController.current?.abort();
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setErrors([]);
    void Promise.allSettled([
      api("logistics/pickups/", { signal: controller.signal }),
      api("logistics/outbound/", { signal: controller.signal }),
    ]).then((results) => {
      if (controller.signal.aborted) return;
      const failures: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          if (index === 0) setPickups(listResult(result.value) as Pickup[]);
          else setJobs(listResult(result.value) as OutboundJob[]);
        } else
          failures.push(
            result.reason instanceof Error
              ? result.reason.message
              : "Chargement impossible.",
          );
      });
      setErrors(failures);
      setLoading(false);
    });
    return () => controller.abort();
  }, [revision, user.id]);
  async function cancel(event: FormEvent) {
    event.preventDefault();
    if (!cancelling || !cancelReason.trim() || busy) return;
    const pending = new AbortController();
    mutationController.current = pending;
    setBusy(true);
    try {
      await api(`logistics/pickups/${cancelling.id}/cancel/`, {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({ reason: cancelReason.trim() }),
      });
      if (mounted.current && !pending.signal.aborted) {
        setCancelling(null);
        setCancelReason("");
        setNotice("Demande d’enlèvement annulée.");
        setRevision((value) => value + 1);
      }
    } catch (error) {
      if (mounted.current && !pending.signal.aborted)
        setErrors([
          error instanceof Error ? error.message : "Annulation impossible.",
        ]);
    } finally {
      if (mounted.current && !pending.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="client-pickups">
      <div className="page-heading">
        <div>
          <div className="eyebrow">VOTRE ESPACE CLIENT</div>
          <h1>Mes enlèvements</h1>
          <p>
            Demandez le transport d’un onduleur vers le SAV et suivez sa prise
            en charge.
          </p>
        </div>
        <button
          type="button"
          className="button primary"
          onClick={() => setCreateOpen(true)}
        >
          <Plus size={18} />
          Demander un enlèvement
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
      <div
        className="page-tabs"
        role="group"
        aria-label="Suivi de mes transports"
      >
        <button
          type="button"
          aria-pressed={tab === "pickups"}
          className={tab === "pickups" ? "active" : ""}
          onClick={() => setTab("pickups")}
        >
          Enlèvements demandés <span>{pickups.length}</span>
        </button>
        <button
          type="button"
          aria-pressed={tab === "deliveries"}
          className={tab === "deliveries" ? "active" : ""}
          onClick={() => setTab("deliveries")}
        >
          Livraisons et retours <span>{jobs.length}</span>
        </button>
      </div>
      {loading ? (
        <div className="loading-state">
          <LoaderCircle size={18} className="spin" />
          Chargement de vos transports…
        </div>
      ) : tab === "pickups" ? (
        <div className="pickup-card-list">
          {pickups.length ? (
            pickups.map((pickup) => (
              <article className="card pickup-card" key={pickup.id}>
                <div className="pickup-card-header">
                  <span className="pickup-card-icon">
                    <Truck size={22} />
                  </span>
                  <div>
                    <h2>{pickup.serial_number}</h2>
                    <p>{pickup.model || "Modèle signalé non renseigné"}</p>
                  </div>
                  <span
                    className={`logistics-status logistics-${pickup.status}`}
                  >
                    {pickupLabels[pickup.status]}
                  </span>
                </div>
                <dl className="logistics-facts">
                  <div>
                    <dt>Votre n° d’appel client</dt>
                    <dd>{pickup.client_reference || "Non renseigné"}</dd>
                  </div>
                  <div>
                    <dt>Demande créée</dt>
                    <dd>{dateFR(pickup.requested_at, true)}</dd>
                  </div>
                  <div>
                    <dt>Adresse d’enlèvement</dt>
                    <dd>{pickup.pickup_address}</dd>
                  </div>
                  <div>
                    <dt>Contact</dt>
                    <dd>
                      {pickup.contact_name} · {pickup.contact_phone}
                    </dd>
                  </div>
                  <div>
                    <dt>Prise en charge du transport</dt>
                    <dd>
                      {pickup.collected_at
                        ? dateFR(pickup.collected_at, true)
                        : "En attente du livreur"}
                    </dd>
                  </div>
                  <div>
                    <dt>Arrivée au SAV</dt>
                    <dd>
                      {pickup.received_at
                        ? dateFR(pickup.received_at, true)
                        : "Pas encore réceptionné"}
                    </dd>
                  </div>
                </dl>
                <p className="pickup-fault">{pickup.fault_description}</p>
                {pickup.call_number && (
                  <CallReference
                    record={logisticsReference(
                      pickup.call_number,
                      pickup.client_reference,
                    )}
                    role="client"
                    compact
                  />
                )}
                {!pickup.received_at && pickup.status !== "cancelled" && (
                  <div className="pickup-before-arrival">
                    <PackageCheck size={17} />
                    La demande d’enlèvement n’enregistre pas une arrivée au SAV.
                    Celle-ci sera confirmée lors de la réception physique.
                  </div>
                )}
                {pickup.can_cancel && (
                  <button
                    type="button"
                    className="button secondary small"
                    onClick={() => {
                      setCancelling(pickup);
                      setCancelReason("");
                    }}
                  >
                    Annuler cet enlèvement
                  </button>
                )}
              </article>
            ))
          ) : (
            <div className="empty-state card">
              <Truck size={30} />
              <h3>Aucun enlèvement demandé</h3>
              <p>
                Choisissez un de vos équipements ou renseignez le numéro de
                série à envoyer au SAV.
              </p>
              <button
                type="button"
                className="button secondary"
                onClick={() => setCreateOpen(true)}
              >
                Demander un enlèvement
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="pickup-card-list">
          {jobs.length ? (
            jobs.map((job) => (
              <article className="card pickup-card" key={job.id}>
                <div className="pickup-card-header">
                  <span className="pickup-card-icon">
                    <Truck size={22} />
                  </span>
                  <div>
                    <h2>
                      {job.kind === "return"
                        ? "Retour de votre onduleur"
                        : "Livraison de votre onduleur"}
                    </h2>
                    <p>
                      {job.serial_number} · {job.model}
                    </p>
                  </div>
                  <span className={`logistics-status logistics-${job.status}`}>
                    {job.status === "completed"
                      ? "Remise enregistrée"
                      : job.status === "cancelled"
                        ? "Transport annulé"
                        : "Livraison affectée"}
                  </span>
                </div>
                <CallReference
                  record={logisticsReference(
                    job.call_number,
                    job.client_reference,
                  )}
                  role="client"
                  compact
                />
                {job.status === "completed" ? (
                  <HandoffReceipt job={job} />
                ) : job.status === "cancelled" ? (
                  <p className="pickup-awaiting-delivery">
                    Ce transport a été annulé par l’équipe. Aucune remise n’a
                    été enregistrée.
                  </p>
                ) : (
                  <p className="pickup-awaiting-delivery">
                    La remise au destinataire sera enregistrée par le livreur
                    avec son nom et l’heure du serveur.
                  </p>
                )}
              </article>
            ))
          ) : (
            <div className="empty-state card">
              <ClipboardList size={29} />
              <h3>Aucune livraison ou retour affecté</h3>
              <p>
                Les transports de vos dossiers apparaîtront ici après leur
                préparation.
              </p>
            </div>
          )}
        </div>
      )}
      <details className="card client-pickup-notifications">
        <summary>Mes notifications de prise en charge</summary>
        <NotificationCenter key={user.id} user={user} compact />
      </details>
      {createOpen && (
        <Dialog
          title="Demander un enlèvement"
          subtitle="Le dossier SAV sera ouvert à la réception physique du matériel."
          onClose={() => setCreateOpen(false)}
          wide
        >
          <PickupForm
            equipment={equipment.filter((item) => item.client === user.client)}
            client={client}
            onClose={() => setCreateOpen(false)}
            onSaved={(pickup) => {
              setPickups((rows) => [
                pickup,
                ...rows.filter((row) => row.id !== pickup.id),
              ]);
              setCreateOpen(false);
              setNotice(
                "Demande d’enlèvement enregistrée. Le matériel n’est pas encore déclaré arrivé au SAV.",
              );
              setRevision((value) => value + 1);
            }}
          />
        </Dialog>
      )}
      {cancelling && (
        <Dialog
          title="Annuler l’enlèvement"
          subtitle={cancelling.serial_number}
          onClose={() => {
            if (!busy) setCancelling(null);
          }}
        >
          <form onSubmit={cancel}>
            <div className="modal-content">
              <div className="form-field">
                <label htmlFor={cancelId}>
                  Motif d’annulation de l’enlèvement
                </label>
                <textarea
                  id={cancelId}
                  className="input"
                  required
                  rows={3}
                  maxLength={4000}
                  value={cancelReason}
                  onChange={(event) => setCancelReason(event.target.value)}
                  disabled={busy}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="button secondary"
                onClick={() => setCancelling(null)}
                disabled={busy}
              >
                Conserver l’enlèvement
              </button>
              <button
                type="submit"
                className="button primary"
                disabled={!cancelReason.trim() || busy}
              >
                {busy && <LoaderCircle size={16} className="spin" />}Confirmer
                l’annulation
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </div>
  );
}

function PickupForm({
  equipment,
  client,
  onClose,
  onSaved,
}: {
  equipment: RecordData[];
  client?: RecordData;
  onClose: () => void;
  onSaved: (pickup: Pickup) => void;
}) {
  const id = useId();
  const [equipmentId, setEquipmentId] = useState("");
  const [serial, setSerial] = useState("");
  const [model, setModel] = useState("");
  const [brand, setBrand] = useState("");
  const [clientReference, setClientReference] = useState("");
  const [fault, setFault] = useState("");
  const [address, setAddress] = useState(
    [client?.address, client?.postal_code, client?.city, client?.country]
      .filter(Boolean)
      .join(", "),
  );
  const [contactName, setContactName] = useState(client?.contact_name || "");
  const [contactPhone, setContactPhone] = useState(client?.phone || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const controller = useRef<AbortController | null>(null);
  const attempt = useRef<{ signature: string; key: string } | null>(null);
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
    if (submitting.current) return;
    const payload = {
      ...(equipmentId
        ? { equipment: Number(equipmentId) }
        : {
            serial_number: serial.trim(),
            model: model.trim(),
            brand: brand.trim(),
          }),
      client_reference: clientReference,
      fault_description: fault.trim(),
      pickup_address: address.trim(),
      contact_name: contactName.trim(),
      contact_phone: contactPhone.trim(),
    };
    const signature = JSON.stringify(payload);
    if (!attempt.current || attempt.current.signature !== signature)
      attempt.current = { signature, key: logisticsUuid() };
    const pending = new AbortController();
    controller.current = pending;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await api<Pickup>("logistics/pickups/", {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({ ...payload, request_key: attempt.current.key }),
      });
      if (mounted.current && !pending.signal.aborted) onSaved(result);
    } catch (failure) {
      if (mounted.current && !pending.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "L’enlèvement n’a pas pu être confirmé. Réessayez sans modifier les champs.",
        );
    } finally {
      if (mounted.current && !pending.signal.aborted) {
        setSaving(false);
        submitting.current = false;
      }
    }
  }
  return (
    <form className="client-pickup-form" onSubmit={submit}>
      <div className="modal-content">
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        <div className="client-pickup-intro">
          <MapPin size={22} />
          <p>
            Indiquez le matériel, le lieu de collecte et le contact. La date
            d’arrivée sera horodatée au SAV lors de sa réception.
          </p>
        </div>
        <fieldset disabled={saving}>
          <div className="form-grid">
            <div className="form-field span-2">
              <label htmlFor={`${id}-equipment`}>Équipement à envoyer</label>
              <select
                id={`${id}-equipment`}
                className="input"
                value={equipmentId}
                onChange={(event) => setEquipmentId(event.target.value)}
              >
                <option value="">Renseigner un autre onduleur…</option>
                {equipment.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.serial_number} · {item.model}
                  </option>
                ))}
              </select>
            </div>
            {!equipmentId && (
              <>
                <div className="form-field">
                  <label htmlFor={`${id}-serial`}>
                    Numéro de série de l’onduleur
                  </label>
                  <input
                    id={`${id}-serial`}
                    className="input"
                    required
                    maxLength={120}
                    value={serial}
                    onChange={(event) => setSerial(event.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor={`${id}-model`}>Modèle signalé</label>
                  <input
                    id={`${id}-model`}
                    className="input"
                    required
                    maxLength={120}
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor={`${id}-brand`}>Marque signalée</label>
                  <input
                    id={`${id}-brand`}
                    className="input"
                    maxLength={100}
                    value={brand}
                    onChange={(event) => setBrand(event.target.value)}
                  />
                </div>
              </>
            )}
            <div className="form-field">
              <label htmlFor={`${id}-reference`}>Votre n° d’appel client</label>
              <input
                id={`${id}-reference`}
                className="input"
                maxLength={120}
                value={clientReference}
                onChange={(event) => setClientReference(event.target.value)}
              />
            </div>
            <div className="form-field span-2">
              <label htmlFor={`${id}-fault`}>Problème signalé</label>
              <textarea
                id={`${id}-fault`}
                className="input"
                required
                rows={3}
                maxLength={4000}
                value={fault}
                onChange={(event) => setFault(event.target.value)}
              />
            </div>
            <div className="form-field span-2">
              <label htmlFor={`${id}-address`}>Adresse d’enlèvement</label>
              <textarea
                id={`${id}-address`}
                className="input"
                required
                rows={3}
                maxLength={4000}
                value={address}
                onChange={(event) => setAddress(event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor={`${id}-contact`}>Contact pour l’enlèvement</label>
              <input
                id={`${id}-contact`}
                className="input"
                required
                maxLength={150}
                value={contactName}
                onChange={(event) => setContactName(event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor={`${id}-phone`}>Téléphone du contact</label>
              <input
                id={`${id}-phone`}
                className="input"
                required
                maxLength={40}
                type="tel"
                value={contactPhone}
                onChange={(event) => setContactPhone(event.target.value)}
              />
            </div>
          </div>
        </fieldset>
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
          disabled={
            saving ||
            (!equipmentId && (!serial.trim() || !model.trim())) ||
            !fault.trim() ||
            !address.trim() ||
            !contactName.trim() ||
            !contactPhone.trim()
          }
        >
          {saving ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <Truck size={17} />
          )}
          Enregistrer la demande d’enlèvement
        </button>
      </div>
    </form>
  );
}
