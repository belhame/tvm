import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { FileText, Pencil, Plus, ShieldCheck, Wrench } from "lucide-react";
import { api, dateFR, type RecordData, type User } from "./api";
import { interventionKinds, requestStatusLabels, statuses } from "./resources";
import InterventionWorksheet from "./InterventionWorksheet";
import OperationTimeline, { type OperationEvent } from "./OperationTimeline";
import RequestTimer, { useServerTimingRefresh } from "./RequestTimer";
import RequestDocuments from "./RequestDocuments";
import CallReference, { callIdentity } from "./CallReference";
import PreventiveProgress from "./PreventiveProgress";
import { ExchangePanel } from "./ExchangeWorkspace";
import DispositionPanel, { type DispositionAction } from "./DispositionPanel";
import RequestAssignment from "./RequestAssignment";
import RequestFollowup from "./RequestFollowup";
import { canWriteRequest } from "./requestAccess";
import "./SAVFollowup.css";

const tabs = [
  ["followup", "Suivi"],
  ["equipment", "Matériel"],
  ["contracts", "Contrat"],
  ["maintenance", "Maintenance"],
  ["commissioning", "Mise en service"],
  ["preventive", "Préventive"],
  ["exchange", "Échange"],
  ["dispatch", "Livraison / Retour"],
  ["conclusion", "Conclusion"],
  ["documents", "Documents"],
] as const;

function day(value?: string | null) {
  if (!value) return "Non renseignée";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : dateFR(value);
}
function Fact({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value === null || value === undefined || value === ""
          ? "Non renseigné"
          : String(value)}
      </dd>
    </div>
  );
}

export default function RequestDossier({
  record: initialRecord,
  data,
  user,
  onEditRequest,
  onCreateIntervention,
  onOpenIntervention,
  onEditIntervention,
  onChanged,
  onOpenExchange,
  onOpenDispatch,
}: {
  record: RecordData;
  data: Record<string, RecordData[]>;
  user: User;
  onEditRequest: (record: RecordData) => void;
  onCreateIntervention: (kind: string) => void;
  onOpenIntervention: (record: RecordData) => void;
  onEditIntervention: (record: RecordData) => void;
  onChanged: () => Promise<void>;
  onOpenExchange?: () => void;
  onOpenDispatch?: () => void;
}) {
  const tabId = useId();
  const [record, setRecord] = useState<RecordData>(initialRecord);
  const [timingError, setTimingError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const recordGeneration = useRef(0);
  async function refreshRecord() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const stamp = ++recordGeneration.current;
    try {
      const fresh = await api<RecordData>(`requests/${initialRecord.id}/`, {
        signal: request.signal,
      });
      if (
        !request.signal.aborted &&
        mounted.current &&
        recordGeneration.current === stamp
      ) {
        setRecord(fresh);
        setTimingError("");
      }
    } catch (error) {
      if (
        !request.signal.aborted &&
        mounted.current &&
        recordGeneration.current === stamp
      )
        setTimingError(
          error instanceof Error
            ? error.message
            : "L’actualisation du dossier n’a pas abouti.",
        );
    }
  }
  useEffect(() => {
    controller.current?.abort();
    recordGeneration.current += 1;
    setRecord(initialRecord);
    setTimingError("");
  }, [initialRecord]);
  useEffect(() => {
    mounted.current = true;
    void refreshRecord();
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, [initialRecord.id]);
  useServerTimingRefresh(refreshRecord);
  const [tab, setTab] = useState<string>("followup");
  const [dispositionAction, setDispositionAction] = useState<
    DispositionAction | undefined
  >();
  const [decisionNonce, setDecisionNonce] = useState(0);
  function openDecision(action: DispositionAction) {
    setDispositionAction(action);
    setDecisionNonce((value) => value + 1);
    setTab("dispatch");
  }
  function handleTabKey(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = tabs.findIndex(([key]) => key === tab);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? tabs.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
            tabs.length;
    setTab(tabs[next][0]);
    event.currentTarget
      .querySelectorAll<HTMLButtonElement>("button[role=tab]")
      [next]?.focus();
  }
  const [timelineScope, setTimelineScope] = useState<"request" | "equipment">(
    "request",
  );
  const [timelineEvents, setTimelineEvents] = useState<OperationEvent[]>([]);
  const [timelineVersion, setTimelineVersion] = useState(0);
  async function applyRecord(updated: RecordData) {
    controller.current?.abort();
    recordGeneration.current += 1;
    setRecord(updated);
    setTimelineVersion((value) => value + 1);
    await onChanged();
  }
  const equipment = data.equipment?.find((row) => row.id === record.equipment);
  const client = data.clients?.find((row) => row.id === equipment?.client);
  const interventions = (data.interventions || []).filter(
    (row) => row.service_request === record.id,
  );
  const contracts = (data.contracts || []).filter(
    (row) =>
      row.client === equipment?.client &&
      (!row.equipment || row.equipment === record.equipment),
  );
  const warranties = (data.warranties || []).filter(
    (row) => row.equipment === record.equipment,
  );
  const canManage = user.role === "admin" || user.role === "manager";
  const canAddOperation = canWriteRequest(record, user);
  const canWriteEquipment =
    canManage ||
    (data.requests || []).some(
      (row) =>
        row.equipment === record.equipment &&
        canWriteRequest(row.id === record.id ? record : row, user),
    );
  const summaries = timelineEvents
    .filter(
      (event) =>
        (event.kind === "summary" ||
          (event.source === "followup" &&
            event.summary?.trim() &&
            event.summary !== "État de la demande modifié.")) &&
        event.service_request === record.id &&
        (!event.is_internal || user.role !== "client"),
    )
    .sort(
      (a, b) =>
        Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id,
    );
  const shown = interventions.filter(
    (row) => (row.kind || "maintenance") === tab,
  );

  function renderTimeline(showComposer: boolean) {
    return (
      <>
        {" "}
        <div
          className="page-tabs request-dossier-timeline-scope"
          role="group"
          aria-label="Périmètre de l’historique"
        >
          <button
            type="button"
            aria-pressed={timelineScope === "request"}
            className={timelineScope === "request" ? "active" : ""}
            onClick={() => {
              setTimelineEvents([]);
              setTimelineScope("request");
            }}
          >
            Historique du dossier
          </button>
          <button
            type="button"
            aria-pressed={timelineScope === "equipment"}
            className={timelineScope === "equipment" ? "active" : ""}
            onClick={() => {
              setTimelineEvents([]);
              setTimelineScope("equipment");
            }}
          >
            Historique de l’onduleur
          </button>
        </div>
        <OperationTimeline
          requestId={timelineScope === "request" ? record.id : undefined}
          equipmentId={
            timelineScope === "equipment" ? record.equipment : undefined
          }
          user={user}
          canWrite={
            timelineScope === "request" ? canAddOperation : canWriteEquipment
          }
          onChanged={async () => {
            await refreshRecord();
            await onChanged();
          }}
          onEventsLoaded={setTimelineEvents}
          requestRecord={timelineScope === "request" ? record : undefined}
          refreshKey={timelineVersion}
          showComposer={showComposer}
        />
      </>
    );
  }

  return (
    <div className="request-dossier">
      <div className="modal-content">
        <div className="request-dossier-heading">
          <div>
            <div className="request-dossier-reference">
              <CallReference record={record} role={user.role} />
            </div>
            <p>{record.subject}</p>
          </div>
          <span className={`badge status-${record.status}`}>
            {requestStatusLabels[record.status] || record.status}
          </span>
        </div>
        <div className="request-dossier-meta">
          <span>{record.client_name || equipment?.client_name}</span>
          <span>
            S/N : {record.equipment_serial || equipment?.serial_number}
          </span>
          <span>
            {record.assigned_technician_name &&
            record.assigned_technician_name !== "Non affecté"
              ? `Affecté à ${record.assigned_technician_name}`
              : "Non affecté"}
          </span>
          <span className={record.is_due_overdue ? "request-overdue" : ""}>
            Échéance : {day(record.due_on)}
          </span>
        </div>
        <RequestTimer timing={record.timing} />
        <RequestAssignment
          record={record}
          user={user}
          technicians={data.users || []}
          onChanged={applyRecord}
        />
        {user.role !== "client" &&
          tab !== "dispatch" &&
          (record.disposition?.can_mark_repaired ||
            record.disposition?.can_mark_nonrepairable) && (
            <div className="request-test-decision-bar">
              <div>
                <strong>Résultat des tests et du diagnostic</strong>
                <span>Choisissez l’orientation réelle de l’onduleur.</span>
              </div>
              {record.disposition.can_mark_repaired && (
                <button
                  type="button"
                  className="button primary small"
                  onClick={() => openDecision("repair")}
                >
                  Tests validés — Réparé
                </button>
              )}
              {record.disposition.can_mark_nonrepairable && (
                <button
                  type="button"
                  className="button secondary small"
                  onClick={() => openDecision("nonrepairable")}
                >
                  Non réparable — Retour client
                </button>
              )}
            </div>
          )}
        {timingError && (
          <div className="error-box" role="alert">
            <span>Le dossier n’a pas pu être actualisé : {timingError}</span>
            <button
              className="button secondary small"
              type="button"
              onClick={() => void refreshRecord()}
            >
              Réessayer
            </button>
          </div>
        )}
        <div
          className="request-dossier-tabs page-tabs"
          role="tablist"
          aria-label="Fiche du dossier SAV"
          onKeyDown={handleTabKey}
        >
          {tabs.map(([key, label]) => (
            <button
              type="button"
              role="tab"
              id={`${tabId}-${key}`}
              aria-controls={`${tabId}-panel`}
              tabIndex={tab === key ? 0 : -1}
              aria-selected={tab === key}
              className={tab === key ? "active" : ""}
              onClick={() => setTab(key)}
              key={key}
            >
              {label}
              {interventionKinds.some(([kind]) => kind === key) && (
                <span>
                  {
                    interventions.filter(
                      (row) => (row.kind || "maintenance") === key,
                    ).length
                  }
                </span>
              )}
            </button>
          ))}
        </div>
        <div
          className="request-dossier-panel"
          role="tabpanel"
          id={`${tabId}-panel`}
          aria-labelledby={`${tabId}-${tab}`}
        >
          {tab === "followup" && (
            <div className="sav-followup-layout">
              <div className="sav-followup-history">
                {renderTimeline(false)}
              </div>
              <aside className="sav-followup-sidebar">
                <RequestFollowup
                  record={record}
                  user={user}
                  onChanged={applyRecord}
                />
                <details className="sav-followup-reception">
                  <summary>Informations de réception et du dossier</summary>
                  <section className="request-dossier-card">
                    <h3>Fiche de suivi du dossier</h3>
                    <dl className="request-dossier-facts">
                      <Fact
                        label="Date d’arrivée"
                        value={
                          record.arrived_at
                            ? dateFR(record.arrived_at, true)
                            : "Non renseignée"
                        }
                      />
                      <Fact
                        label="Date de clôture"
                        value={
                          record.closed_at
                            ? dateFR(record.closed_at, true)
                            : "Non renseignée"
                        }
                      />
                      <Fact
                        label="N° d’appel TVM / n° d’intervention métier"
                        value={callIdentity(record).tvm}
                      />
                      <Fact
                        label="N° d’appel client / référence client"
                        value={record.client_reference}
                      />
                      <Fact label="Client final" value={record.end_customer} />
                      <Fact
                        label="Nom du contact"
                        value={record.contact_name}
                      />
                      <Fact
                        label="Téléphone du contact"
                        value={record.contact_phone}
                      />
                      <Fact
                        label="E-mail du contact"
                        value={record.contact_email}
                      />
                      <Fact
                        label="Retour de matériel"
                        value={record.return_flag ? "Oui" : "Non"}
                      />
                      <Fact label="Emballage reçu" value={record.packaging} />
                      <Fact
                        label="Lieu de prise en charge"
                        value={
                          (
                            {
                              workshop: "Atelier",
                              depot: "Dépôt",
                              onsite: "Sur site",
                            } as Record<string, string>
                          )[record.service_location]
                        }
                      />
                      <Fact
                        label="Matériel livré par"
                        value={
                          (
                            { courier: "Livreur", client: "Client" } as Record<
                              string,
                              string
                            >
                          )[record.delivered_by]
                        }
                      />
                      <Fact
                        label="Nom du livreur"
                        value={record.courier_name}
                      />
                      <Fact
                        label="Situation de garantie du dossier"
                        value={
                          (
                            {
                              unspecified: "Non précisée",
                              warranty: "Garantie",
                              quotation: "Devis",
                              contract: "Contrat",
                              billable: "Facturable",
                            } as Record<string, string>
                          )[record.warranty_status]
                        }
                      />
                    </dl>
                    <h4>Accessoires reçus</h4>
                    <p>{record.accessories || "Non renseignés"}</p>
                    <p className="request-followup-note">
                      Les informations de réception et la situation du dossier
                      sont saisies par l’équipe. Le compteur reste inconnu tant
                      qu’aucune arrivée réelle n’est renseignée.
                    </p>
                  </section>
                </details>
              </aside>
            </div>
          )}
          {tab === "documents" && (
            <RequestDocuments
              requestId={record.id}
              user={user}
              onChanged={onChanged}
            />
          )}
          {tab === "dispatch" && (
            <>
              <DispositionPanel
                key={`${record.id}:${user.id}:${decisionNonce}`}
                record={record}
                user={user}
                initialAction={dispositionAction}
                onChanged={async (updated) => {
                  setRecord(updated);
                  await onChanged();
                }}
              />
              {onOpenDispatch && (
                <button
                  type="button"
                  className="button secondary small dispatch-open-dossier"
                  onClick={onOpenDispatch}
                >
                  Ouvrir les livraisons et retours
                </button>
              )}
              {record.exchange && (
                <div className="request-exchange-dispatch-link">
                  <p>
                    Le remplacement et sa validation financière se suivent dans
                    l’onglet Échange du dossier.
                  </p>
                  <button
                    type="button"
                    className="button secondary small"
                    onClick={() => setTab("exchange")}
                  >
                    Voir l’échange et sa facturation
                  </button>
                </div>
              )}
            </>
          )}
          {tab === "equipment" && (
            <>
              <section className="request-dossier-card">
                <h3>Matériel concerné</h3>
                <dl className="request-dossier-facts">
                  <Fact
                    label="Client"
                    value={record.client_name || equipment?.client_name}
                  />
                  <Fact
                    label="Contact principal"
                    value={client?.contact_name}
                  />
                  <Fact
                    label="Numéro de série"
                    value={record.equipment_serial || equipment?.serial_number}
                  />
                  <Fact
                    label="Modèle"
                    value={equipment?.model || record.equipment_model}
                  />
                  <Fact label="Marque" value={equipment?.brand} />
                  <Fact
                    label="Site / emplacement"
                    value={equipment?.location}
                  />
                  <Fact label="Puissance (kVA)" value={equipment?.power_kva} />
                  <Fact
                    label="Fabrication enregistrée"
                    value={
                      equipment?.manufactured_on
                        ? day(equipment.manufactured_on)
                        : null
                    }
                  />
                  <Fact
                    label="Mise en service"
                    value={
                      equipment?.commissioned_on
                        ? day(equipment.commissioned_on)
                        : null
                    }
                  />
                  <Fact
                    label="Fin de garantie enregistrée"
                    value={
                      equipment?.warranty_until
                        ? day(equipment.warranty_until)
                        : null
                    }
                  />
                </dl>
              </section>
              <section className="request-dossier-card">
                <h3>Signalement</h3>
                <p>
                  {record.description || "Aucune description complémentaire."}
                </p>
              </section>
              {warranties.length > 0 && (
                <section className="request-dossier-card">
                  <h3>
                    <ShieldCheck size={16} /> Garanties enregistrées
                  </h3>
                  {warranties.map((warranty) => (
                    <div className="request-dossier-related" key={warranty.id}>
                      <strong>{warranty.provider}</strong>
                      <span>
                        {day(warranty.starts_on)} → {day(warranty.ends_on)}
                      </span>
                      <p>{warranty.terms}</p>
                    </div>
                  ))}
                </section>
              )}
            </>
          )}
          {tab === "contracts" && (
            <section className="request-dossier-card">
              <h3>Contrats de maintenance</h3>
              <p>
                Les contrats client ou équipement sont distincts des garanties
                constructeur.
              </p>
              {contracts.length ? (
                contracts.map((contract) => (
                  <div className="request-dossier-related" key={contract.id}>
                    <strong>{contract.number}</strong>
                    <span className={`badge status-${contract.status}`}>
                      {statuses[contract.status] || contract.status}
                    </span>
                    <p>
                      {day(contract.starts_on)} → {day(contract.ends_on)} ·{" "}
                      {contract.equipment
                        ? "Contrat équipement"
                        : "Contrat client"}
                    </p>
                    <p>{contract.coverage}</p>
                    <small>{contract.visits_per_year} visite(s) par an</small>
                  </div>
                ))
              ) : (
                <p className="request-dossier-empty">
                  Aucun contrat enregistré dans ce périmètre.
                </p>
              )}
            </section>
          )}
          {interventionKinds.some(([kind]) => kind === tab) && (
            <section className="request-dossier-card">
              <div className="request-dossier-actions">
                <h3>{interventionKinds.find(([kind]) => kind === tab)?.[1]}</h3>
                {canAddOperation && (
                  <button
                    type="button"
                    className="button primary small"
                    onClick={() => onCreateIntervention(tab)}
                  >
                    <Plus size={16} />
                    Créer une fiche
                  </button>
                )}
              </div>
              {tab === "exchange" && (
                <>
                  <ExchangePanel
                    key={`${record.id}:${user.id}`}
                    record={record}
                    equipment={data.equipment || []}
                    user={user}
                    onChanged={async (updated) => {
                      setRecord(updated);
                      await onChanged();
                    }}
                  />
                  {onOpenExchange && (
                    <button
                      type="button"
                      className="button secondary small exchange-open-dossier"
                      onClick={onOpenExchange}
                    >
                      Ouvrir l’espace Échange
                    </button>
                  )}
                  <h4 className="exchange-visit-history-title">
                    Fiches de visite d’échange
                  </h4>
                  <p className="operation-tab-description">
                    Les fiches de visite conservent l’historique des
                    interventions. La validation du remplacement et la
                    disponibilité pour livraison sont suivies séparément
                    ci-dessus.
                  </p>
                </>
              )}
              {tab === "preventive" && <PreventiveProgress record={record} />}
              {tab === "commissioning" && (
                <p className="operation-tab-description">
                  Chaque fiche conserve le site, le contact, les contrôles
                  d’installation et d’essai ainsi que la date réelle de mise en
                  service. Son rapport PDF reprend les informations
                  enregistrées.
                </p>
              )}
              {shown.length ? (
                shown.map((intervention) => (
                  <article
                    className="request-dossier-related"
                    key={intervention.id}
                  >
                    <div className="request-dossier-actions">
                      <CallReference
                        record={intervention}
                        role={user.role}
                        visit
                        compact
                      />
                      <span className={`badge status-${intervention.status}`}>
                        {statuses[intervention.status] || intervention.status}
                      </span>
                    </div>
                    <dl className="request-dossier-facts">
                      <Fact
                        label="Date de l’opération"
                        value={day(intervention.performed_on)}
                      />
                      <Fact
                        label="Technicien"
                        value={intervention.technician_name}
                      />
                      <Fact
                        label="Ancien numéro de série"
                        value={intervention.equipment_serial}
                      />
                      {tab === "exchange" && (
                        <Fact
                          label="Nouveau numéro de série"
                          value={
                            intervention.replacement_equipment_serial ||
                            data.equipment?.find(
                              (row) =>
                                row.id === intervention.replacement_equipment,
                            )?.serial_number
                          }
                        />
                      )}
                      <Fact
                        label="Armoire batteries"
                        value={intervention.cabinet_serial}
                      />
                      <Fact
                        label="Nombre de batteries"
                        value={intervention.battery_count}
                      />
                      <Fact label="Site" value={intervention.site} />
                      <Fact
                        label="Client final"
                        value={intervention.end_customer}
                      />
                      <Fact label="Contact" value={intervention.contact_name} />
                      <Fact
                        label="Téléphone du contact"
                        value={intervention.contact_phone}
                      />
                      <Fact
                        label="Contrat lié"
                        value={
                          data.contracts?.find(
                            (row) => row.id === intervention.contract,
                          )?.number || intervention.contract_number
                        }
                      />
                      <Fact
                        label="Début du contrat lié"
                        value={
                          intervention.contract_starts_on
                            ? day(intervention.contract_starts_on)
                            : null
                        }
                      />
                      <Fact
                        label="Fin du contrat lié"
                        value={
                          intervention.contract_ends_on
                            ? day(intervention.contract_ends_on)
                            : null
                        }
                      />
                      <Fact
                        label="Début de l’extension liée"
                        value={
                          intervention.extension_starts_on
                            ? day(intervention.extension_starts_on)
                            : null
                        }
                      />
                      <Fact
                        label="Fin de l’extension liée"
                        value={
                          intervention.extension_ends_on
                            ? day(intervention.extension_ends_on)
                            : null
                        }
                      />
                      <Fact
                        label="Conclusion"
                        value={
                          statuses[intervention.conclusion] ||
                          intervention.conclusion
                        }
                      />
                    </dl>
                    {intervention.summary && <p>{intervention.summary}</p>}
                    {intervention.conclusion_notes && (
                      <p>{intervention.conclusion_notes}</p>
                    )}
                    <InterventionWorksheet
                      kind={tab}
                      value={intervention.structured_data || {}}
                      readonly
                      onChange={() => {}}
                    />
                    <div className="request-dossier-actions">
                      <button
                        type="button"
                        className="button secondary small"
                        onClick={() => onOpenIntervention(intervention)}
                      >
                        <Wrench size={15} />
                        Ouvrir l’intervention
                      </button>
                      {(canManage ||
                        (user.role === "technician" &&
                          canAddOperation &&
                          intervention.technician === user.id)) && (
                        <button
                          type="button"
                          className="button secondary small"
                          onClick={() => onEditIntervention(intervention)}
                        >
                          <Pencil size={15} />
                          Modifier la fiche
                        </button>
                      )}
                      <a
                        className="button secondary small"
                        href={`/api/interventions/${intervention.id}/report/`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <FileText size={15} />
                        Rapport PDF
                      </a>
                    </div>
                  </article>
                ))
              ) : (
                <p className="request-dossier-empty">
                  Aucune fiche de ce type pour cette demande.
                </p>
              )}
            </section>
          )}
          {tab === "conclusion" && (
            <section className="request-dossier-card request-dossier-conclusion">
              <h3>Synthèses du dossier</h3>
              {summaries.length ? (
                summaries.map((event) => (
                  <article className="request-dossier-related" key={event.id}>
                    <strong>{dateFR(event.created_at, true)}</strong>
                    {event.is_internal && (
                      <span className="badge">Interne</span>
                    )}
                    <p>{event.summary}</p>
                  </article>
                ))
              ) : (
                <p className="request-dossier-empty">
                  Aucune synthèse visible n’a été enregistrée. Les synthèses
                  peuvent être ajoutées dans l’historique du dossier ci-dessous.
                </p>
              )}
              <h3>Conclusions des interventions</h3>
              {interventions
                .filter((row) => row.conclusion || row.conclusion_notes)
                .map((row) => (
                  <article className="request-dossier-related" key={row.id}>
                    <strong>
                      <CallReference
                        record={row}
                        role={user.role}
                        visit
                        compact
                      />
                      {statuses[row.conclusion] ||
                        row.conclusion ||
                        "Conclusion renseignée"}
                    </strong>
                    <p>{row.conclusion_notes || row.summary}</p>
                  </article>
                ))}
            </section>
          )}
        </div>
        {tab !== "followup" && renderTimeline(true)}
      </div>
      <div className="modal-footer">
        <a
          className="button secondary"
          href={`/api/requests/${record.id}/report/`}
          target="_blank"
          rel="noreferrer"
        >
          <FileText size={16} />
          PDF de suivi du dossier
        </a>
        <span className="form-secure">
          N° d’appel TVM · {callIdentity(record).tvm || "Non renseigné"}
        </span>
        {canManage && (
          <button
            type="button"
            className="button primary"
            onClick={() => onEditRequest(record)}
          >
            <Pencil size={16} />
            Modifier le dossier
          </button>
        )}
      </div>
    </div>
  );
}
