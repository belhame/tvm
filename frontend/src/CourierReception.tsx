import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Info,
  LoaderCircle,
  PackageCheck,
  Search,
  ShieldCheck,
} from "lucide-react";
import { api, dateFR } from "./api";
import { requestStatusLabels } from "./resources";
import SerialCapture, { type SerialCaptureSource } from "./SerialCapture";
import {
  logisticsUuid,
  type LogisticsClient,
  type Pickup,
  type ReceptionCandidate,
  type ReceptionLookup,
  type ReceptionReceipt,
} from "./logistics";

export default function CourierReception({
  clients,
  pickup,
  onReceived,
  onClearPickup,
}: {
  clients: LogisticsClient[];
  pickup?: Pickup | null;
  onReceived: () => Promise<void>;
  onClearPickup?: () => void;
}) {
  const id = useId();
  const [serial, setSerial] = useState(pickup?.serial_number || "");
  const [source, setSource] = useState<SerialCaptureSource>("manual");
  const [clientId, setClientId] = useState(
    pickup ? String(pickup.client.id) : "",
  );
  const [clientReference, setClientReference] = useState(
    pickup?.client_reference || "",
  );
  const [fault, setFault] = useState(pickup?.fault_description || "");
  const [lookup, setLookup] = useState<ReceptionLookup | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState("");
  const [manual, setManual] = useState(false);
  const [manualModel, setManualModel] = useState("");
  const [manualBrand, setManualBrand] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [requestId, setRequestId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<ReceptionReceipt | null>(null);
  const mounted = useRef(true);
  const currentSerial = useRef(serial);
  const lookupGeneration = useRef(0);
  const lookupController = useRef<AbortController | null>(null);
  const saveController = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const attempt = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      lookupGeneration.current += 1;
      lookupController.current?.abort();
      saveController.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (pickup?.serial_number) void findSerial(pickup.serial_number);
  }, []);
  function changeSerial(value: string) {
    lookupController.current?.abort();
    lookupGeneration.current += 1;
    currentSerial.current = value;
    setSerial(value);
    setSource("manual");
    setLookup(null);
    setLookupBusy(false);
    setLookupError("");
    setManual(false);
    setManualModel("");
    setManualBrand("");
    setManualReason("");
    setRequestId("");
    setConfirmed(false);
    setError("");
    setReceipt(null);
    attempt.current = null;
    if (!pickup) setClientId("");
  }
  async function findSerial(
    value = serial,
    choices: Partial<ReceptionCandidate> = {},
  ) {
    const number = value.trim();
    if (!number || submitting.current) return;
    lookupController.current?.abort();
    const pending = new AbortController();
    lookupController.current = pending;
    const generation = ++lookupGeneration.current;
    setLookupBusy(true);
    setLookup(null);
    setLookupError("");
    setConfirmed(false);
    setError("");
    try {
      const result = await api<ReceptionLookup>("logistics/lookup/", {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({
          serial_number: number,
          ...(choices.product_id ? { product_id: choices.product_id } : {}),
          ...(choices.catalogue_import_id
            ? { catalogue_import_id: choices.catalogue_import_id }
            : {}),
          ...(choices.profile ? { profile: choices.profile } : {}),
        }),
      });
      if (
        !mounted.current ||
        pending.signal.aborted ||
        generation !== lookupGeneration.current ||
        value !== currentSerial.current
      )
        return;
      setLookup(result);
      setManual(result.status === "unknown");
      if (result.equipment) setClientId(String(result.equipment.client.id));
      const related = pickup?.service_request
        ? result.open_requests.find((row) => row.id === pickup.service_request)
        : null;
      setRequestId(
        related
          ? String(related.id)
          : result.open_requests.length === 1
            ? String(result.open_requests[0].id)
            : "",
      );
    } catch (failure) {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === lookupGeneration.current
      )
        setLookupError(
          failure instanceof Error
            ? failure.message
            : "Le numéro n’a pas pu être recherché.",
        );
    } finally {
      if (
        mounted.current &&
        !pending.signal.aborted &&
        generation === lookupGeneration.current
      )
        setLookupBusy(false);
    }
  }
  const known = lookup?.equipment;
  const suggested = lookup?.suggested;
  const chosenModel =
    known?.model || (!manual ? suggested?.model : manualModel) || "";
  const effectiveClient = known ? String(known.client.id) : clientId;
  const canReceive = !!(
    lookup &&
    effectiveClient &&
    confirmed &&
    chosenModel.trim() &&
    (!manual || manualReason.trim()) &&
    (lookup.open_requests.length <= 1 || requestId) &&
    !lookupBusy &&
    !saving &&
    !receipt
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canReceive || submitting.current || !lookup) return;
    const payload = {
      serial_number: serial.trim(),
      client: Number(effectiveClient),
      ...(pickup ? { pickup: pickup.id } : {}),
      ...(requestId ? { service_request: Number(requestId) } : {}),
      client_reference: clientReference,
      fault_description: fault.trim(),
      source,
      ...(!manual && !known && suggested
        ? {
            product_id: suggested.product_id,
            catalogue_import_id: suggested.catalogue_import_id,
            profile: suggested.profile,
          }
        : {}),
      ...(manual && !known
        ? {
            manual_model: manualModel.trim(),
            manual_brand: manualBrand.trim(),
            manual_reason: manualReason.trim(),
          }
        : {}),
    };
    const signature = JSON.stringify(payload);
    if (!attempt.current || attempt.current.signature !== signature)
      attempt.current = { signature, key: logisticsUuid() };
    const pending = new AbortController();
    saveController.current = pending;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await api<ReceptionReceipt>("logistics/receive/", {
        method: "POST",
        signal: pending.signal,
        body: JSON.stringify({ ...payload, request_key: attempt.current.key }),
      });
      if (!mounted.current || pending.signal.aborted) return;
      setReceipt(result);
      setConfirmed(false);
      try {
        await onReceived();
      } catch {
        if (mounted.current)
          setError(
            "La réception est enregistrée. Actualisez les tournées pour retrouver son état.",
          );
      }
    } catch (failure) {
      if (mounted.current && !pending.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "La réception n’a pas pu être confirmée. Réessayez sans modifier les champs pour conserver la même tentative.",
        );
    } finally {
      if (mounted.current && !pending.signal.aborted) {
        setSaving(false);
        submitting.current = false;
      }
    }
  }
  function newReception() {
    changeSerial("");
    setClientReference("");
    setFault("");
    setClientId("");
    if (pickup && onClearPickup) onClearPickup();
  }
  return (
    <section
      className="courier-reception"
      aria-label="Réception physique d’un onduleur"
    >
      <div className="courier-section-intro">
        <span>
          <PackageCheck size={24} />
        </span>
        <div>
          <h2>Réceptionner un onduleur</h2>
          <p>
            Scannez ou saisissez le numéro, vérifiez le matériel, puis confirmez
            sa réception physique.
          </p>
        </div>
      </div>
      {pickup && (
        <div className="courier-pickup-preset">
          <strong>
            Enlèvement #{pickup.id} · {pickup.client.name}
          </strong>
          <span>{pickup.pickup_address}</span>
          <button
            type="button"
            className="text-button"
            onClick={onClearPickup}
            disabled={saving}
          >
            Passer à une réception hors enlèvement
          </button>
        </div>
      )}
      {receipt ? (
        <div className="courier-reception-receipt" role="status">
          <CheckCircle2 size={35} />
          <h3>
            {receipt.already_received
              ? "Réception déjà enregistrée"
              : "Réception confirmée"}
          </h3>
          <p>
            {receipt.already_received
              ? "Le dossier ouvert existant a été retrouvé. Aucune nouvelle demande SAV n’a été créée."
              : "La réception et le dossier SAV sont enregistrés sur le serveur."}
          </p>
          <dl>
            <div>
              <dt>N° d’appel TVM</dt>
              <dd>{receipt.request.call_number}</dd>
            </div>
            <div>
              <dt>N° d’appel client</dt>
              <dd>{receipt.request.client_reference || "Non renseigné"}</dd>
            </div>
            <div>
              <dt>Numéro de série</dt>
              <dd>{receipt.request.serial_number}</dd>
            </div>
            <div>
              <dt>Matériel</dt>
              <dd>{receipt.request.equipment_name || receipt.request.model}</dd>
            </div>
            <div>
              <dt>Client</dt>
              <dd>{receipt.request.client.name}</dd>
            </div>
            <div>
              <dt>Arrivée enregistrée par le serveur</dt>
              <dd>
                {receipt.request.arrived_at
                  ? dateFR(receipt.request.arrived_at, true)
                  : "Non renseignée"}
              </dd>
            </div>
            <div>
              <dt>État du dossier</dt>
              <dd>
                {requestStatusLabels[receipt.request.status] ||
                  receipt.request.status}
              </dd>
            </div>
          </dl>
          <button
            type="button"
            className="button primary"
            onClick={newReception}
          >
            Nouvelle réception
          </button>
        </div>
      ) : (
        <>
          <SerialCapture
            value={serial}
            manualLabel="Numéro de série à réceptionner"
            disabled={saving}
            onChange={changeSerial}
            onSerialDetected={(value, meta) => {
              setSource(meta?.source || "manual");
              void findSerial(value);
            }}
          />
          <button
            type="button"
            className="button secondary courier-lookup-button"
            disabled={!serial.trim() || lookupBusy || saving}
            onClick={() => void findSerial()}
          >
            {lookupBusy ? (
              <LoaderCircle size={17} className="spin" />
            ) : (
              <Search size={17} />
            )}
            Rechercher le matériel
          </button>
          {lookupError && (
            <div className="error-box" role="alert">
              <AlertCircle size={17} />
              <span>{lookupError}</span>
            </div>
          )}
          {lookup && (
            <form className="courier-reception-form" onSubmit={submit}>
              <fieldset disabled={saving}>
                <div className="courier-identified-equipment">
                  <ShieldCheck size={22} />
                  <div>
                    <span>
                      {known
                        ? "Matériel déjà enregistré"
                        : suggested && !manual
                          ? "Modèle identifié dans le catalogue"
                          : "Identification à compléter"}
                    </span>
                    <strong>
                      {known?.equipment_name ||
                        (!manual ? suggested?.equipment_name : manualModel) ||
                        "Onduleur — modèle à renseigner"}
                    </strong>
                    <small>Type : Onduleur · S/N {lookup.serial_number}</small>
                  </div>
                </div>
                {lookup.status === "ambiguous" && !manual && (
                  <div className="courier-reception-choices">
                    <h3>Choisissez explicitement le modèle</h3>
                    {lookup.profile_options.length > 1 && (
                      <div className="form-field">
                        <label htmlFor={`${id}-profile`}>
                          Structure du numéro de série
                        </label>
                        <select
                          id={`${id}-profile`}
                          className="input"
                          defaultValue=""
                          onChange={(event) => {
                            if (event.target.value)
                              void findSerial(serial, {
                                profile: event.target.value,
                              });
                          }}
                        >
                          <option value="">Sélectionner une structure…</option>
                          {lookup.profile_options.map((profile) => (
                            <option value={profile} key={profile}>
                              {profile}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    {lookup.candidates.map((candidate) => (
                      <div
                        className="courier-candidate"
                        key={`${candidate.catalogue_import_id}:${candidate.product_id}:${candidate.profile}`}
                      >
                        <div>
                          <strong>{candidate.model}</strong>
                          <small>
                            {candidate.equipment_name} · {candidate.profile}
                          </small>
                        </div>
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={() => void findSerial(serial, candidate)}
                        >
                          Choisir ce modèle
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {!known && (
                  <label className="courier-manual-toggle">
                    <input
                      type="checkbox"
                      checked={manual}
                      onChange={(event) => {
                        setManual(event.target.checked);
                        setConfirmed(false);
                      }}
                    />
                    <span>
                      Renseigner un modèle manuel avec une justification
                    </span>
                  </label>
                )}
                {manual && !known && (
                  <div className="form-grid">
                    <div className="form-field">
                      <label htmlFor={`${id}-model`}>
                        Modèle manuel de l’onduleur
                      </label>
                      <input
                        id={`${id}-model`}
                        className="input"
                        required
                        maxLength={120}
                        value={manualModel}
                        onChange={(event) => {
                          setManualModel(event.target.value);
                          setConfirmed(false);
                        }}
                      />
                    </div>
                    <div className="form-field">
                      <label htmlFor={`${id}-brand`}>Marque du matériel</label>
                      <input
                        id={`${id}-brand`}
                        className="input"
                        maxLength={100}
                        value={manualBrand}
                        onChange={(event) => {
                          setManualBrand(event.target.value);
                          setConfirmed(false);
                        }}
                      />
                    </div>
                    <div className="form-field span-2">
                      <label htmlFor={`${id}-reason`}>
                        Justification du modèle manuel
                      </label>
                      <textarea
                        id={`${id}-reason`}
                        className="input"
                        required
                        maxLength={4000}
                        rows={3}
                        value={manualReason}
                        onChange={(event) => {
                          setManualReason(event.target.value);
                          setConfirmed(false);
                        }}
                      />
                    </div>
                  </div>
                )}
                <div className="form-grid">
                  <div className="form-field">
                    <label htmlFor={`${id}-client`}>Client propriétaire</label>
                    <select
                      id={`${id}-client`}
                      className="input"
                      required
                      value={effectiveClient}
                      disabled={!!known}
                      onChange={(event) => {
                        setClientId(event.target.value);
                        setConfirmed(false);
                      }}
                    >
                      <option value="">Sélectionner le client…</option>
                      {known &&
                        !clients.some(
                          (client) => client.id === known.client.id,
                        ) && (
                          <option value={known.client.id}>
                            {known.client.name}
                          </option>
                        )}
                      {clients.map((client) => (
                        <option value={client.id} key={client.id}>
                          {client.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-field">
                    <label htmlFor={`${id}-client-ref`}>
                      N° d’appel client / référence client
                    </label>
                    <input
                      id={`${id}-client-ref`}
                      className="input"
                      maxLength={120}
                      value={clientReference}
                      onChange={(event) => {
                        setClientReference(event.target.value);
                        setConfirmed(false);
                      }}
                    />
                  </div>
                  <div className="form-field span-2">
                    <label htmlFor={`${id}-fault`}>Motif signalé</label>
                    <textarea
                      id={`${id}-fault`}
                      className="input"
                      maxLength={4000}
                      rows={3}
                      value={fault}
                      onChange={(event) => {
                        setFault(event.target.value);
                        setConfirmed(false);
                      }}
                    />
                  </div>
                </div>
                {lookup.open_requests.length > 0 && (
                  <div className="courier-existing-request">
                    <Info size={18} />
                    <div>
                      <strong>
                        {lookup.open_requests.length === 1
                          ? "Un dossier SAV ouvert existe déjà"
                          : "Plusieurs dossiers ouverts : choisissez celui à réceptionner"}
                      </strong>
                      <p>
                        Une réception déjà enregistrée sera retrouvée, sans
                        créer de nouveau dossier ni modifier son état.
                      </p>
                      <div className="form-field">
                        <label htmlFor={`${id}-request`}>
                          Dossier SAV à réceptionner
                        </label>
                        <select
                          id={`${id}-request`}
                          className="input"
                          required={lookup.open_requests.length > 1}
                          value={requestId}
                          onChange={(event) => {
                            setRequestId(event.target.value);
                            setConfirmed(false);
                          }}
                        >
                          <option value="">Choisir un dossier…</option>
                          {lookup.open_requests.map((request) => (
                            <option value={request.id} key={request.id}>
                              {request.call_number}
                              {request.client_reference
                                ? ` · Réf. client ${request.client_reference}`
                                : ""}
                              {request.arrived_at
                                ? " · Arrivée déjà enregistrée"
                                : " · En attente de réception"}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                )}
                {lookup.warnings.map((warning, index) => (
                  <p className="courier-lookup-warning" key={index}>
                    {warning}
                  </p>
                ))}
                <div className="courier-server-arrival">
                  <Clock3 size={19} />
                  <div>
                    <strong>Date et heure attribuées par le serveur</strong>
                    <span>
                      La confirmation enregistre la réception réelle. Une
                      nouvelle demande est créée Non affecté, sans technicien
                      attribué.
                    </span>
                  </div>
                </div>
                <label className="courier-physical-confirm">
                  <input
                    type="checkbox"
                    required
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  <span>Je confirme avoir reçu physiquement cet onduleur.</span>
                </label>
                <button
                  type="submit"
                  className="button primary courier-confirm-reception"
                  disabled={!canReceive}
                >
                  {saving ? (
                    <LoaderCircle size={18} className="spin" />
                  ) : (
                    <PackageCheck size={18} />
                  )}
                  Confirmer la réception
                </button>
              </fieldset>
            </form>
          )}
        </>
      )}
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}
    </section>
  );
}
