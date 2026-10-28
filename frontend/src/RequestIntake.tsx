import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ClipboardList,
  Info,
  LoaderCircle,
  Search,
  Server,
  ShieldCheck,
} from "lucide-react";
import { api, type RecordData, type User } from "./api";
import { optionLabel, requestReceptionFields } from "./resources";
import RequestReceptionFields, {
  defaultArrivalLocal,
} from "./RequestReceptionFields";
import SerialLookupSummary, {
  type SerialLookupResult,
} from "./SerialLookupSummary";

type LookupChoices = {
  product_id?: number;
  profile?: string;
  catalogue_import_id?: number;
  warranty_reference_id?: number;
};

function uuid() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export default function RequestIntake({
  user,
  equipment,
  clients,
  initialEquipmentId,
  onSaved,
  onClose,
}: {
  user: User;
  equipment: RecordData[];
  clients: RecordData[];
  initialEquipmentId?: number;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const formId = useId();
  const initialEquipment = equipment.find(
    (row) => row.id === initialEquipmentId,
  );
  const canCreateEquipment = user.role === "admin" || user.role === "manager";
  const [serial, setSerial] = useState(
    String(initialEquipment?.serial_number || ""),
  );
  const [equipmentId, setEquipmentId] = useState(
    initialEquipment ? String(initialEquipment.id) : "",
  );
  const [clientId, setClientId] = useState(
    initialEquipment ? String(initialEquipment.client) : "",
  );
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("normal");
  const [plannedVisits, setPlannedVisits] = useState("");
  const [reception, setReception] = useState<RecordData>(() =>
    Object.fromEntries(
      requestReceptionFields
        .filter((field) => field.name !== "closed_at")
        .map((field) => [
          field.name,
          field.name === "arrived_at"
            ? defaultArrivalLocal()
            : (field.default ?? ""),
        ]),
    ),
  );
  const [lookup, setLookup] = useState<SerialLookupResult | null>(null);
  const [profileOptions, setProfileOptions] = useState<string[]>([]);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualModel, setManualModel] = useState("");
  const [manufacturedOn, setManufacturedOn] = useState("");
  const [durationMonths, setDurationMonths] = useState("");
  const [manualReason, setManualReason] = useState("");
  const lookupController = useRef<AbortController | null>(null);
  const saveController = useRef<AbortController | null>(null);
  const lookupGeneration = useRef(0);
  const currentSerial = useRef(serial);
  const mounted = useRef(true);
  const submission = useRef<{ signature: string; key: string } | null>(null);

  function edited() {
    submission.current = null;
    setError("");
  }

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
    if (initialEquipment) void findSerial(initialEquipment.serial_number);
    // The initial equipment is a one-time form preset, not a live selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function changeSerial(value: string, selectedEquipment?: RecordData) {
    edited();
    currentSerial.current = value;
    lookupGeneration.current += 1;
    lookupController.current?.abort();
    setSerial(value);
    setLookup(null);
    setProfileOptions([]);
    setLookupBusy(false);
    setLookupError("");
    setEquipmentId(selectedEquipment ? String(selectedEquipment.id) : "");
    setClientId(selectedEquipment ? String(selectedEquipment.client) : "");
    setManual(false);
    setManualModel("");
    setManufacturedOn("");
    setDurationMonths("");
    setManualReason("");
  }

  async function findSerial(value = serial, choices: LookupChoices = {}) {
    const query = value.trim();
    if (!query) return;
    setError("");
    lookupController.current?.abort();
    const controller = new AbortController();
    lookupController.current = controller;
    const generation = ++lookupGeneration.current;
    const sourceSerial = value;
    setLookupBusy(true);
    setLookupError("");
    setLookup(null);
    try {
      const result = await api<SerialLookupResult>("serial-lookup/", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({ serial_number: query, ...choices }),
      });
      if (
        !mounted.current ||
        controller.signal.aborted ||
        generation !== lookupGeneration.current ||
        sourceSerial !== currentSerial.current
      )
        return;
      setLookup(result);
      setProfileOptions((previous) =>
        Array.from(new Set([...previous, ...result.detection.profile_options])),
      );
      if (result.existing_equipment) {
        setEquipmentId(String(result.existing_equipment.id));
        setClientId(String(result.existing_equipment.client));
        setManual(false);
        setManualModel("");
        setManufacturedOn("");
        setDurationMonths("");
        setManualReason("");
      }
    } catch (failure) {
      if (
        !mounted.current ||
        controller.signal.aborted ||
        generation !== lookupGeneration.current
      )
        return;
      setLookupError(
        failure instanceof Error
          ? failure.message
          : "La recherche n’a pas abouti. Réessayez.",
      );
    } finally {
      if (
        mounted.current &&
        !controller.signal.aborted &&
        generation === lookupGeneration.current
      )
        setLookupBusy(false);
    }
  }

  function chooseLookup(choices: LookupChoices) {
    edited();
    void findSerial(serial, choices);
  }

  const localEquipment = equipment.find(
    (row) => String(row.id) === equipmentId,
  );
  const existing = lookup?.existing_equipment || localEquipment || null;
  const selectedProduct =
    lookup?.selected_product ||
    lookup?.product_candidates.find(
      (row) => row.id === lookup.selected_product_id,
    ) ||
    null;
  const catalogueNumber = selectedProduct?.catalogue_number?.trim() || "";
  const productModel =
    catalogueNumber && !["NA", "N/A"].includes(catalogueNumber.toUpperCase())
      ? catalogueNumber
      : selectedProduct?.product_name || "";
  const model = existing?.model || (manual ? manualModel : productModel);
  const modelLength = Array.from(model).length;
  const hasRecordedWarranty = Boolean(
    lookup?.recorded_warranties?.length ||
      lookup?.computed_warranty.status === "recorded_priority" ||
      existing?.warranty_until,
  );
  const profileNeedsChoice = Boolean(lookup?.detection.requires_profile_choice);
  const productNeedsChoice = Boolean(
    lookup?.detection.requires_product_choice &&
      lookup.product_candidates.length > 0 &&
      !selectedProduct,
  );
  const warrantyNeedsChoice =
    !hasRecordedWarranty && lookup?.computed_warranty.status === "needs_choice";
  const canSave = Boolean(
    serial.trim() &&
      subject.trim() &&
      description.trim() &&
      !lookupBusy &&
      !saving &&
      (existing ||
        (canCreateEquipment &&
          clientId &&
          lookup &&
          model.trim() &&
          modelLength <= 120 &&
          !profileNeedsChoice &&
          !productNeedsChoice &&
          !warrantyNeedsChoice &&
          (!manual || manualReason.trim()))),
  );
  const selectedWarrantyId = hasRecordedWarranty
    ? null
    : (lookup?.selected_warranty?.id ??
      lookup?.computed_warranty.warranty_id ??
      lookup?.default_warranty_id);
  const currentChoices: LookupChoices = {
    ...(lookup?.detection.profile ? { profile: lookup.detection.profile } : {}),
    ...(lookup?.catalogue_import_id
      ? { catalogue_import_id: lookup.catalogue_import_id }
      : {}),
    ...(selectedProduct ? { product_id: selectedProduct.id } : {}),
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    const payload: RecordData = {
      serial_number: serial.trim(),
      subject: subject.trim(),
      description: description.trim(),
      priority,
      ...(canCreateEquipment
        ? {
            planned_visit_count:
              plannedVisits === "" ? null : Number(plannedVisits),
          }
        : {}),
      ...Object.fromEntries(
        requestReceptionFields
          .filter((field) => field.name !== "closed_at")
          .map((field) => [
            field.name,
            field.name === "arrived_at"
              ? reception.arrived_at
                ? new Date(reception.arrived_at).toISOString()
                : null
              : field.name === "return_flag"
                ? reception.return_flag === true ||
                  reception.return_flag === "true"
                : (reception[field.name] ?? field.default ?? ""),
          ]),
      ),
      ...(existing
        ? { equipment: existing.id, client: existing.client }
        : { client: Number(clientId) }),
      ...currentChoices,
      ...(selectedWarrantyId
        ? { warranty_reference_id: selectedWarrantyId }
        : {}),
      ...(manual && !existing
        ? {
            manual_model: manualModel.trim(),
            manual_reason: manualReason.trim(),
            ...(manufacturedOn
              ? { manufactured_on_override: manufacturedOn }
              : {}),
            ...(durationMonths !== ""
              ? { duration_months_override: Number(durationMonths) }
              : {}),
          }
        : {}),
    };
    const signature = JSON.stringify(payload);
    if (!submission.current || submission.current.signature !== signature)
      submission.current = { signature, key: uuid() };
    const requestKey = submission.current.key;
    const controller = new AbortController();
    saveController.current = controller;
    setSaving(true);
    setError("");
    try {
      await api("requests/intake/", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({ ...payload, request_key: requestKey }),
      });
      if (!mounted.current || controller.signal.aborted) return;
      await onSaved();
      if (mounted.current) onClose();
    } catch (failure) {
      if (mounted.current && !controller.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "L’enregistrement n’a pas pu être confirmé. Réessayez sans modifier les champs pour conserver la même tentative.",
        );
    } finally {
      if (mounted.current && !controller.signal.aborted) setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="request-intake">
      <div className="modal-content">
        <div className="request-intake-intro">
          <ClipboardList size={20} />
          <div>
            <strong>Identifiez l’onduleur, puis décrivez la demande.</strong>
            <p>
              La recherche ne modifie aucune donnée. La validation enregistre le
              dossier et, si nécessaire, le nouvel équipement dans une seule
              opération.
            </p>
          </div>
        </div>
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        <fieldset disabled={saving}>
          <section className="request-intake-section">
            <div className="request-intake-section-title">
              <span>1</span>
              <h3>Équipement et numéro de série</h3>
            </div>
            <label className="form-field">
              Équipement concerné
              <select
                className="input"
                value={equipmentId}
                onChange={(event) => {
                  const selected = equipment.find(
                    (row) => String(row.id) === event.target.value,
                  );
                  changeSerial(selected?.serial_number || "", selected);
                  if (selected) void findSerial(selected.serial_number);
                }}
              >
                <option value="">
                  Saisir un numéro de série ou choisir un équipement existant…
                </option>
                {equipment.map((row) => (
                  <option value={row.id} key={row.id}>
                    {optionLabel("equipment", row)}
                  </option>
                ))}
              </select>
              <small>
                Vous pouvez conserver le parcours habituel en choisissant un
                équipement déjà enregistré.
              </small>
            </label>
            <div className="request-intake-serial-row">
              <label className="form-field">
                Numéro de série <span className="required">*</span>
                <input
                  className="input"
                  value={serial}
                  required
                  maxLength={120}
                  autoComplete="off"
                  onChange={(event) => changeSerial(event.target.value)}
                  placeholder="Saisir ou scanner le numéro de série"
                />
              </label>
              <button
                type="button"
                className="button primary"
                disabled={!serial.trim() || lookupBusy}
                onClick={() =>
                  void findSerial(serial, {
                    ...currentChoices,
                    ...(selectedWarrantyId
                      ? { warranty_reference_id: selectedWarrantyId }
                      : {}),
                  })
                }
              >
                {lookupBusy ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <Search size={17} />
                )}
                Rechercher le modèle et la garantie
              </button>
            </div>
            {lookupBusy && (
              <div className="request-intake-loading" role="status">
                <LoaderCircle size={17} className="spin" />
                Recherche du modèle, des garanties et de l’historique…
              </div>
            )}
            {lookupError && (
              <div className="error-box" role="alert">
                <AlertCircle size={17} />
                <div>
                  {lookupError}
                  {existing && (
                    <p>
                      Vous pouvez enregistrer la demande pour l’équipement déjà
                      enregistré, sans nouvelle identification du catalogue.
                    </p>
                  )}
                </div>
              </div>
            )}
            {lookup && (
              <>
                {profileOptions.length > 1 && (
                  <label className="form-field request-intake-choice">
                    Structure du numéro de série
                    <select
                      className="input"
                      value={lookup.detection.profile || ""}
                      onChange={(event) =>
                        chooseLookup({
                          ...(lookup.catalogue_import_id
                            ? {
                                catalogue_import_id: lookup.catalogue_import_id,
                              }
                            : {}),
                          ...(event.target.value
                            ? { profile: event.target.value }
                            : {}),
                        })
                      }
                    >
                      <option value="">
                        Choisir explicitement une structure…
                      </option>
                      {profileOptions.map((profile) => (
                        <option value={profile} key={profile}>
                          {profile}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {lookup.product_candidates.length > 1 && (
                  <div className="request-intake-product-choice">
                    <div className="request-intake-choice-warning">
                      <AlertCircle size={17} />
                      <p>
                        Plusieurs produits correspondent à ce numéro. Comparez
                        les références et choisissez le modèle exact ; aucun
                        premier résultat n’est retenu automatiquement.
                      </p>
                    </div>
                    <label className="form-field">
                      Modèle du catalogue
                      <select
                        className="input"
                        value={selectedProduct?.id || ""}
                        onChange={(event) =>
                          chooseLookup({
                            ...(lookup.catalogue_import_id
                              ? {
                                  catalogue_import_id:
                                    lookup.catalogue_import_id,
                                }
                              : {}),
                            ...(lookup.detection.profile
                              ? { profile: lookup.detection.profile }
                              : {}),
                            ...(event.target.value
                              ? { product_id: Number(event.target.value) }
                              : {}),
                          })
                        }
                      >
                        <option value="">
                          Choisir explicitement un produit…
                        </option>
                        {lookup.product_candidates.map((product) => (
                          <option key={product.id} value={product.id}>
                            {product.catalogue_number ||
                              "Référence courte absente"}{" "}
                            · {product.product_name}
                            {product.version
                              ? ` · version ${product.version}`
                              : ""}
                            {product.manufacturing_part_number
                              ? ` · ${product.manufacturing_part_number}`
                              : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}
                {lookup.warranty_options.length > 0 &&
                  (!selectedWarrantyId || lookup.warranty_options.length > 1) &&
                  !hasRecordedWarranty && (
                    <div className="request-intake-warranty-choice">
                      <div className="request-intake-choice-warning">
                        <ShieldCheck size={17} />
                        <p>
                          {lookup.warranty_options.length > 1
                            ? "Plusieurs couvertures sont proposées. Choisissez celle qui s’applique, par exemple électronique ou batterie ; aucune durée maximale n’est retenue automatiquement."
                            : "Une couverture apparentée est proposée. Vérifiez sa portée avant de la retenir explicitement."}
                        </p>
                      </div>
                      <label className="form-field">
                        Couverture de garantie
                        <select
                          className="input"
                          value={selectedWarrantyId || ""}
                          onChange={(event) =>
                            chooseLookup({
                              ...currentChoices,
                              ...(event.target.value
                                ? {
                                    warranty_reference_id: Number(
                                      event.target.value,
                                    ),
                                  }
                                : {}),
                            })
                          }
                        >
                          <option value="">
                            Choisir explicitement une couverture…
                          </option>
                          {lookup.warranty_options.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.product_name || option.category} ·{" "}
                              {(
                                {
                                  electronics: "Électronique",
                                  battery: "Batteries",
                                  batteries: "Batteries",
                                  electronics_and_batteries:
                                    "Électronique et batteries",
                                  unspecified: "Portée à préciser",
                                } as Record<string, string>
                              )[option.scope] ||
                                option.scope ||
                                option.category}{" "}
                              · {option.duration_text}
                              {option.conditions
                                ? ` · ${option.conditions}`
                                : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  )}
                <SerialLookupSummary
                  result={lookup}
                  role={user.role}
                  candidate={selectedProduct || undefined}
                />
              </>
            )}
          </section>

          <section className="request-intake-section">
            <div className="request-intake-section-title">
              <span>2</span>
              <h3>Client et modèle retenus</h3>
            </div>
            {existing ? (
              <div className="request-intake-existing">
                <CheckCircle2 size={18} />
                <div>
                  <strong>Équipement existant conservé</strong>
                  <p>
                    Le client, le modèle et les garanties déjà enregistrés ne
                    sont pas écrasés par la recherche catalogue.
                  </p>
                </div>
              </div>
            ) : !canCreateEquipment ? (
              <div className="request-intake-choice-warning">
                <Info size={18} />
                <p>
                  Le rôle technicien permet de créer une demande uniquement pour
                  un équipement déjà enregistré. Recherchez son numéro de série
                  ou sélectionnez-le ci-dessus.
                </p>
              </div>
            ) : null}
            <div className="form-grid">
              <label className="form-field">
                Client <span className="required">*</span>
                {existing ? (
                  <input
                    className="input"
                    readOnly
                    value={
                      existing.client_name ||
                      clients.find((row) => row.id === existing.client)?.name ||
                      "Client enregistré"
                    }
                  />
                ) : (
                  <select
                    className="input"
                    required
                    value={clientId}
                    onChange={(event) => {
                      edited();
                      setClientId(event.target.value);
                    }}
                    disabled={!canCreateEquipment}
                  >
                    <option value="">
                      Choisir le client du nouvel équipement…
                    </option>
                    {clients.map((client) => (
                      <option key={client.id} value={client.id}>
                        {client.name}
                      </option>
                    ))}
                  </select>
                )}
              </label>
              <label className="form-field">
                Modèle identifié
                <input
                  className="input"
                  readOnly
                  value={model}
                  placeholder={
                    productNeedsChoice
                      ? "Choisissez un produit du catalogue"
                      : "Modèle court du catalogue ou modèle existant"
                  }
                />
                {modelLength > 120 && (
                  <small className="request-intake-model-limit">
                    Ce modèle contient {modelLength} caractères ; la limite est
                    de 120. Aucune troncature n’est appliquée.
                  </small>
                )}
              </label>
            </div>
            {selectedProduct && (
              <p className="request-intake-product-name">
                <span>Nom produit complet</span>
                {selectedProduct.product_name}
              </p>
            )}
            {canCreateEquipment && !existing && lookup && (
              <details className="request-intake-manual">
                <summary>
                  Saisie contrôlée si le référentiel est incomplet
                </summary>
                <label className="request-intake-checkbox">
                  <input
                    type="checkbox"
                    checked={manual}
                    onChange={(event) => {
                      edited();
                      setManual(event.target.checked);
                      if (event.target.checked && !manualModel)
                        setManualModel(productModel);
                    }}
                  />
                  Renseigner manuellement le modèle ou compléter les
                  informations de garantie
                </label>
                {manual && (
                  <div className="form-grid">
                    <label className="form-field">
                      Modèle manuel <span className="required">*</span>
                      <input
                        className="input"
                        required
                        value={manualModel}
                        onChange={(event) => {
                          edited();
                          setManualModel(event.target.value);
                        }}
                      />
                      <small>
                        120 caractères maximum ; aucune troncature automatique.
                      </small>
                    </label>
                    <label className="form-field">
                      Date de fabrication à confirmer
                      <input
                        className="input"
                        type="date"
                        value={manufacturedOn}
                        onChange={(event) => {
                          edited();
                          setManufacturedOn(event.target.value);
                        }}
                      />
                    </label>
                    <label className="form-field">
                      Durée de garantie manuelle (mois)
                      <input
                        className="input"
                        type="number"
                        min="0"
                        max="1200"
                        step="1"
                        value={durationMonths}
                        onChange={(event) => {
                          edited();
                          setDurationMonths(event.target.value);
                        }}
                      />
                      <small>
                        Le début reste la date de fabrication + 6 mois
                        calendaires, calculé par le serveur.
                      </small>
                    </label>
                    <label className="form-field span-2">
                      Justification de la saisie manuelle{" "}
                      <span className="required">*</span>
                      <textarea
                        className="input"
                        rows={3}
                        required
                        value={manualReason}
                        onChange={(event) => {
                          edited();
                          setManualReason(event.target.value);
                        }}
                        placeholder="Source de l’information et raison de cette saisie contrôlée"
                      />
                    </label>
                  </div>
                )}
              </details>
            )}
          </section>

          <section className="request-intake-section">
            <RequestReceptionFields
              value={reception}
              onChange={(name, entry) => {
                edited();
                setReception((previous) => ({ ...previous, [name]: entry }));
              }}
            />
          </section>
          <section className="request-intake-section">
            <div className="request-intake-section-title">
              <span>3</span>
              <h3>Demande SAV</h3>
            </div>
            <div className="form-grid">
              <label className="form-field span-2">
                Objet du signalement <span className="required">*</span>
                <input
                  className="input"
                  required
                  maxLength={200}
                  value={subject}
                  onChange={(event) => {
                    edited();
                    setSubject(event.target.value);
                  }}
                  placeholder="Ex. Alarme batterie, défaut de charge…"
                />
              </label>
              <label className="form-field span-2">
                Description de la panne <span className="required">*</span>
                <textarea
                  className="input"
                  rows={4}
                  required
                  value={description}
                  onChange={(event) => {
                    edited();
                    setDescription(event.target.value);
                  }}
                  placeholder="Décrivez le problème, son contexte et les symptômes observés."
                />
              </label>
              <label className="form-field">
                Priorité
                <select
                  className="input"
                  value={priority}
                  onChange={(event) => {
                    edited();
                    setPriority(event.target.value);
                  }}
                >
                  <option value="low">Basse</option>
                  <option value="normal">Normale</option>
                  <option value="high">Haute</option>
                  <option value="urgent">Urgente</option>
                </select>
              </label>
              {canCreateEquipment && (
                <div className="form-field">
                  <label htmlFor={`${formId}-planned-visits`}>
                    Nombre de visites préventives prévues
                  </label>
                  <input
                    id={`${formId}-planned-visits`}
                    className="input"
                    type="number"
                    min="1"
                    max="1000"
                    step="1"
                    value={plannedVisits}
                    onChange={(event) => {
                      edited();
                      setPlannedVisits(event.target.value);
                    }}
                    aria-describedby={`${formId}-planned-visits-help`}
                  />
                  <small id={`${formId}-planned-visits-help`}>
                    Objectif facultatif pour ce dossier. Laissez vide si non
                    défini ; les visites se créent et se planifient séparément.
                  </small>
                </div>
              )}
            </div>
          </section>
        </fieldset>
      </div>
      <div className="modal-footer">
        <span className="form-secure">
          <Server size={14} />
          Enregistrement partagé, en une validation
        </span>
        <button
          type="button"
          className="button secondary"
          onClick={onClose}
          disabled={saving}
        >
          Annuler
        </button>
        <button className="button primary" type="submit" disabled={!canSave}>
          {saving ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <Check size={17} />
          )}
          Enregistrer
        </button>
      </div>
    </form>
  );
}
