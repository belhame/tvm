import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  Info,
  LoaderCircle,
  Search,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { ApiError, api, dateFR, type User } from "./api";
import { logisticsUuid } from "./logistics";
import SimpleSAVLookup from "./SimpleSAVLookup";
import type {
  SimpleSAVCreation,
  SimpleSAVLookupResult,
  SimpleSAVOptions,
  SimpleSAVRequest,
} from "./simpleSAV";
import "./SimpleSAVIntake.css";

type Props = {
  user: User;
  initialClientId?: number;
  initialSerial?: string;
  onSaved: () => Promise<void>;
  onClose: () => void;
  onOpenRequest?: (id: number) => void;
  onBusyChange?: (busy: boolean) => void;
};
function payloadOf(error: unknown): Record<string, unknown> | null {
  return error instanceof ApiError &&
    error.payload &&
    typeof error.payload === "object" &&
    !Array.isArray(error.payload)
    ? (error.payload as Record<string, unknown>)
    : null;
}
export default function SimpleSAVIntake({
  user,
  initialClientId,
  initialSerial = "",
  onSaved,
  onClose,
  onOpenRequest,
  onBusyChange,
}: Props) {
  const id = useId();
  const [options, setOptions] = useState<SimpleSAVOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [optionsVersion, setOptionsVersion] = useState(0);
  const [client, setClient] = useState(
    initialClientId ? String(initialClientId) : "",
  );
  const [serial, setSerial] = useState(initialSerial);
  const [courier, setCourier] = useState("");
  const [clientReference, setClientReference] = useState("");
  const [description, setDescription] = useState("");
  const [lookup, setLookup] = useState<SimpleSAVLookupResult | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<SimpleSAVCreation | null>(null);
  const [conflict, setConflict] = useState<SimpleSAVRequest | null>(null);
  const [refreshWarning, setRefreshWarning] = useState("");
  const mounted = useRef(true);
  const lookupGeneration = useRef(0);
  const lookupController = useRef<AbortController | null>(null);
  const saveController = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const requestKey = useRef<{ signature: string; key: string } | null>(null);
  const lookupScope = useRef("");
  const draftSignature = JSON.stringify({
    client,
    serial,
    courier,
    clientReference,
    description,
  });
  const latestDraft = useRef(draftSignature);
  latestDraft.current = draftSignature;
  const lookupSignature = JSON.stringify([client, serial.trim()]);
  lookupScope.current = lookupSignature;
  const receiptRef = useRef<HTMLDivElement>(null);
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
    const request = new AbortController();
    setOptionsError("");
    api<SimpleSAVOptions>("logistics/sav-intake/options/", {
      signal: request.signal,
    })
      .then((response) => {
        if (!request.signal.aborted) setOptions(response);
      })
      .catch((failure: Error) => {
        if (!request.signal.aborted) setOptionsError(failure.message);
      });
    return () => request.abort();
  }, [optionsVersion]);
  useEffect(() => {
    lookupGeneration.current += 1;
    lookupController.current?.abort();
    setLookup(null);
    setLookupBusy(false);
    setLookupError("");
    setConflict(null);
    setError("");
  }, [lookupSignature]);
  useEffect(() => {
    if (receipt) receiptRef.current?.focus();
  }, [receipt]);
  useEffect(() => {
    onBusyChange?.(saving);
    return () => onBusyChange?.(false);
  }, [saving, onBusyChange]);
  const availableCouriers = (options?.couriers || []).filter(
    (person) =>
      person.courier_kind === "internal" ||
      (person.courier_kind === "client" && person.client === Number(client)),
  );
  function changeClient(value: string) {
    setClient(value);
    const selected = options?.couriers.find(
      (person) => String(person.id) === courier,
    );
    if (
      selected?.courier_kind === "client" &&
      selected.client !== Number(value)
    )
      setCourier("");
  }
  async function search() {
    if (saving || receipt) return;
    const entered = serial.trim();
    if (!client || !entered) {
      setLookupError("Choisissez le client et renseignez le numéro de série.");
      return;
    }
    lookupController.current?.abort();
    const request = new AbortController();
    lookupController.current = request;
    const stamp = ++lookupGeneration.current;
    const scope = JSON.stringify([client, entered]);
    setLookupBusy(true);
    setLookupError("");
    setLookup(null);
    setConflict(null);
    try {
      const response = await api<SimpleSAVLookupResult>(
        "logistics/sav-intake/lookup/",
        {
          method: "POST",
          body: JSON.stringify({
            client: Number(client),
            serial_number: entered,
          }),
          signal: request.signal,
        },
      );
      if (
        mounted.current &&
        !request.signal.aborted &&
        lookupGeneration.current === stamp &&
        lookupScope.current === scope
      )
        setLookup(response);
    } catch (failure) {
      if (
        mounted.current &&
        !request.signal.aborted &&
        lookupGeneration.current === stamp &&
        lookupScope.current === scope
      )
        setLookupError((failure as Error).message);
    } finally {
      if (
        mounted.current &&
        !request.signal.aborted &&
        lookupGeneration.current === stamp
      )
        setLookupBusy(false);
    }
  }
  function serialKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (!lookupBusy) void search();
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving || submitting.current || receipt || !options) return;
    const entered = serial.trim();
    if (!client || !entered) {
      setError("Choisissez le client et renseignez le numéro de série.");
      return;
    }
    if (
      options.courier_required &&
      (!courier ||
        !availableCouriers.some((person) => String(person.id) === courier))
    ) {
      setError("Choisissez le livreur qui a apporté l’onduleur.");
      return;
    }
    const body = {
      client: Number(client),
      serial_number: entered,
      ...(options.actor_courier
        ? {}
        : courier
          ? { arrival_courier: Number(courier) }
          : {}),
      ...(clientReference.trim()
        ? { client_reference: clientReference.trim() }
        : {}),
      ...(description.trim() ? { description: description.trim() } : {}),
    };
    const signature = JSON.stringify(body);
    if (!requestKey.current || requestKey.current.signature !== signature)
      requestKey.current = { signature, key: logisticsUuid() };
    const currentDraft = draftSignature;
    const request = new AbortController();
    saveController.current = request;
    lookupController.current?.abort();
    lookupGeneration.current += 1;
    setLookupBusy(false);
    submitting.current = true;
    setSaving(true);
    setError("");
    setConflict(null);
    try {
      const response = await api<SimpleSAVCreation>(
        "logistics/sav-intake/create/",
        {
          method: "POST",
          body: JSON.stringify({
            ...body,
            request_key: requestKey.current.key,
          }),
          signal: request.signal,
        },
      );
      if (
        !mounted.current ||
        request.signal.aborted ||
        latestDraft.current !== currentDraft
      )
        return;
      setReceipt(response);
      try {
        await onSaved();
      } catch {
        if (mounted.current && !request.signal.aborted)
          setRefreshWarning(
            "La demande est enregistrée. Actualisez la liste pour la retrouver.",
          );
      }
    } catch (failure) {
      if (
        !mounted.current ||
        request.signal.aborted ||
        latestDraft.current !== currentDraft
      )
        return;
      const payload = payloadOf(failure);
      setError(
        typeof payload?.detail === "string"
          ? payload.detail
          : (failure as Error).message,
      );
      if (
        payload?.open_request &&
        typeof payload.open_request === "object" &&
        typeof (payload.open_request as SimpleSAVRequest).id === "number"
      )
        setConflict(payload.open_request as SimpleSAVRequest);
    } finally {
      submitting.current = false;
      if (mounted.current && !request.signal.aborted) setSaving(false);
    }
  }
  const selectedClient = options?.clients.find(
    (entry) => String(entry.id) === client,
  );
  if (receipt) {
    const summary: SimpleSAVLookupResult = {
      serial_number: receipt.equipment.serial_number,
      client: selectedClient || {
        id: Number(client),
        name: "Client sélectionné",
      },
      equipment: receipt.equipment,
      coverage: receipt.coverage,
      return_history: receipt.return_history,
      open_request: null,
      warnings: receipt.warnings,
    };
    return (
      <div className="simple-sav-intake">
        <div
          ref={receiptRef}
          tabIndex={-1}
          className="simple-sav-receipt"
          role="group"
          aria-label="Demande SAV enregistrée"
        >
          <CheckCircle2 size={28} />
          <div>
            <h2>Demande SAV enregistrée</h2>
            <strong>N° d’appel TVM : {receipt.request.call_number}</strong>
            <p>
              {receipt.created
                ? "La réception de l’onduleur a été enregistrée."
                : "Cette demande était déjà enregistrée. Aucun doublon n’a été créé."}
            </p>
          </div>
        </div>
        <dl className="simple-sav-receipt-facts">
          <div>
            <dt>Date d’arrivée enregistrée</dt>
            <dd>
              {receipt.request.arrived_at
                ? dateFR(receipt.request.arrived_at, true)
                : "Non renseignée"}
            </dd>
          </div>
          <div>
            <dt>État</dt>
            <dd>
              {receipt.request.status === "new"
                ? "Non affecté"
                : receipt.request.status}
            </dd>
          </div>
          <div>
            <dt>Livreur enregistré</dt>
            <dd>{receipt.request.arrival_courier?.name || "Non renseigné"}</dd>
          </div>
        </dl>
        <SimpleSAVLookup result={summary} onOpenRequest={onOpenRequest} />
        {refreshWarning && (
          <div className="simple-sav-warning" role="status">
            {refreshWarning}
          </div>
        )}
        <div className="modal-footer">
          <button type="button" className="button primary" onClick={onClose}>
            Terminer
          </button>
        </div>
      </div>
    );
  }
  return (
    <form className="simple-sav-intake" onSubmit={(event) => void save(event)}>
      <div className="simple-sav-intro">
        <span>
          <ClipboardList size={23} />
        </span>
        <div>
          <h2>Enregistrer la réception d’un onduleur</h2>
          <p>
            {user.role === "courier"
              ? "Client et numéro de série. Votre compte livreur est associé automatiquement."
              : "Client, numéro de série et livreur. Les autres informations sont facultatives."}
          </p>
        </div>
      </div>
      {optionsError && (
        <div className="error-box" role="alert">
          <AlertCircle size={18} />
          <span>{optionsError}</span>
          <button
            type="button"
            className="button secondary small"
            onClick={() => setOptionsVersion((value) => value + 1)}
          >
            Réessayer
          </button>
        </div>
      )}
      {!options && !optionsError && (
        <div className="simple-sav-loading" role="status">
          <LoaderCircle className="spin" size={18} />
          Chargement des clients et livreurs…
        </div>
      )}
      <div className="simple-sav-layout">
        <fieldset disabled={saving || !options} className="simple-sav-fields">
          <div className="field">
            <label htmlFor={`${id}-client`}>Client</label>
            <select
              id={`${id}-client`}
              className="input"
              value={client}
              onChange={(event) => changeClient(event.target.value)}
              required
            >
              <option value="">Choisir un client…</option>
              {options?.clients.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-serial`}>Numéro de série</label>
            <input
              id={`${id}-serial`}
              className="input simple-sav-serial"
              value={serial}
              onChange={(event) => setSerial(event.target.value)}
              onKeyDown={serialKey}
              maxLength={120}
              required
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
            />
            <small>
              La touche Entrée d’une douchette lance la vérification, sans
              enregistrer la demande.
            </small>
          </div>
          {options?.actor_courier ? (
            <div className="simple-sav-actor-courier">
              <Truck size={19} />
              <div>
                <span>Livreur enregistré</span>
                <strong>{options.actor_courier.name}</strong>
                <small>
                  Votre compte livreur sera associé automatiquement à la
                  réception.
                </small>
              </div>
            </div>
          ) : (
            <div className="field">
              <label htmlFor={`${id}-courier`}>Livreur</label>
              <select
                id={`${id}-courier`}
                className="input"
                value={courier}
                onChange={(event) => setCourier(event.target.value)}
                required={options?.courier_required}
              >
                <option value="">Choisir le livreur…</option>
                {availableCouriers.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                    {person.courier_kind === "client"
                      ? " · Livreur du client"
                      : " · TVM"}
                  </option>
                ))}
              </select>
              <small>
                Qui a apporté l’onduleur : livreur TVM ou livreur de la société
                sélectionnée.
              </small>
            </div>
          )}
          <button
            type="button"
            className="button secondary simple-sav-lookup-button"
            onClick={() => void search()}
            disabled={lookupBusy || !client || !serial.trim()}
          >
            {lookupBusy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <Search size={17} />
            )}
            Rechercher le modèle et la garantie
          </button>
          <div className="simple-sav-optional">
            <h3>Informations facultatives</h3>
            <div className="field">
              <label htmlFor={`${id}-client-reference`}>
                N° d’appel client (facultatif)
              </label>
              <input
                id={`${id}-client-reference`}
                className="input"
                value={clientReference}
                onChange={(event) => setClientReference(event.target.value)}
                maxLength={120}
              />
            </div>
            <div className="field">
              <label htmlFor={`${id}-description`}>
                Description (facultative)
              </label>
              <textarea
                id={`${id}-description`}
                className="input"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                maxLength={4000}
              />
            </div>
          </div>
        </fieldset>
        <aside className="simple-sav-results" aria-live="polite">
          {lookupBusy ? (
            <div className="simple-sav-placeholder">
              <LoaderCircle className="spin" size={24} />
              <h3>Vérification du numéro de série…</h3>
              <p>
                Recherche du modèle, de la couverture et des anciens dossiers de
                ce client.
              </p>
            </div>
          ) : lookup ? (
            <SimpleSAVLookup result={lookup} onOpenRequest={onOpenRequest} />
          ) : (
            <div className="simple-sav-placeholder">
              <ShieldCheck size={30} />
              <h3>Garantie et historique</h3>
              <p>
                La recherche affiche le modèle identifié et signale les retours
                d’équipements déjà traités.
              </p>
              <small>
                Vous pouvez enregistrer sans recherche préalable. Le serveur
                vérifiera ces informations au moment de la création.
              </small>
            </div>
          )}
          {lookupError && (
            <div className="error-box" role="alert">
              <AlertCircle size={17} />
              {lookupError}
            </div>
          )}
        </aside>
      </div>
      <div className="simple-sav-server-note">
        <Info size={17} />
        <p>
          L’enregistrement confirme la réception physique de l’onduleur. Le
          serveur fixe la date et l’heure d’arrivée et crée la demande en état{" "}
          <strong>Non affecté</strong>. Aucun technicien, devis PDF ou facture
          n’est ajouté automatiquement.
        </p>
      </div>
      {error && (
        <div className="error-box" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}
      {conflict && (
        <div className="simple-sav-warning">
          <strong>Demande déjà ouverte : {conflict.call_number}</strong>
          <p>
            {conflict.arrived_at
              ? `Arrivée enregistrée le ${dateFR(conflict.arrived_at, true)}.`
              : "Consultez la demande existante avant de renouveler la saisie."}
          </p>
          {onOpenRequest && (
            <button
              type="button"
              className="button secondary small"
              onClick={() => onOpenRequest(conflict.id)}
            >
              Ouvrir la demande existante
            </button>
          )}
        </div>
      )}
      <div className="modal-footer">
        <span className="form-secure">
          <ShieldCheck size={14} />
          Enregistrement partagé sur le serveur
        </span>
        <button
          type="button"
          className="button secondary"
          onClick={onClose}
          disabled={saving}
        >
          Annuler
        </button>
        <button
          type="submit"
          className="button primary"
          disabled={saving || !options}
        >
          {saving ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <CheckCircle2 size={17} />
          )}
          Enregistrer
        </button>
      </div>
    </form>
  );
}
