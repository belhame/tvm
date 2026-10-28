import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Info,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Send,
} from "lucide-react";
import { api, type RecordData, type User } from "./api";
import { requestStatusLabels } from "./resources";
import { canWriteRequest } from "./requestAccess";
import BatteryConfigurationCard from "./BatteryConfigurationCard";
import { batteryCountText, canViewBattery } from "./battery";
import "./SAVFollowup.css";

type FollowupResponse = { request: RecordData; events: RecordData[] };
export default function RequestFollowup({
  record,
  user,
  onChanged,
}: {
  record: RecordData;
  user: User;
  onChanged: (record: RecordData) => Promise<void>;
}) {
  const id = useId();
  const [status, setStatus] = useState(record.status);
  const [baseStatus, setBaseStatus] = useState(record.status);
  const [baseRevision, setBaseRevision] = useState<number>(
    record.assignment?.revision ?? 0,
  );
  const [observation, setObservation] = useState("");
  const [summary, setSummary] = useState("");
  const [isInternal, setIsInternal] = useState(true);
  const [batteryCount, setBatteryCount] = useState(
    batteryCountText(record.battery_count),
  );
  const [baseBatteryCount, setBaseBatteryCount] = useState(
    batteryCountText(record.battery_count),
  );
  const [batteryConfirmed, setBatteryConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  const revision = record.assignment?.revision ?? 0;
  const canWrite = canWriteRequest(record, user);
  const showBattery = canViewBattery(record, user);
  const batteryDirty = batteryCount !== baseBatteryCount;
  const stale =
    baseStatus !== record.status ||
    baseRevision !== revision ||
    ((batteryDirty || batteryConfirmed) &&
      baseBatteryCount !== batteryCountText(record.battery_count));
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    controller.current?.abort();
    submitting.current = false;
    setBusy(false);
  }, [record.id, revision]);
  useEffect(() => {
    if (
      !observation.trim() &&
      !summary.trim() &&
      status === baseStatus &&
      !batteryDirty &&
      !batteryConfirmed
    ) {
      setBaseStatus(record.status);
      setStatus(record.status);
      setBaseRevision(revision);
    }
  }, [record.status, revision]);
  useEffect(() => {
    if (!batteryDirty && !batteryConfirmed) {
      const freshCount = batteryCountText(record.battery_count);
      setBatteryCount(freshCount);
      setBaseBatteryCount(freshCount);
    }
  }, [record.battery_count]);
  async function refresh() {
    if (submitting.current) return;
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    setBusy(true);
    setError("");
    try {
      const fresh = await api<RecordData>(`requests/${record.id}/`, {
        signal: request.signal,
      });
      if (!request.signal.aborted) {
        setBaseStatus(fresh.status);
        setStatus(fresh.status);
        setBaseRevision(fresh.assignment?.revision ?? 0);
        setBaseBatteryCount(batteryCountText(fresh.battery_count));
        if (!batteryDirty && !batteryConfirmed)
          setBatteryCount(batteryCountText(fresh.battery_count));
        await onChanged(fresh);
        if (!request.signal.aborted)
          setNotice(
            "État et affectation actualisés. Relisez votre observation avant d’enregistrer.",
          );
      }
    } catch (failure) {
      if (!request.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!request.signal.aborted) setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canWrite || busy || submitting.current) return;
    const note = observation.trim(),
      final = summary.trim();
    if (stale) {
      setError(
        "Le dossier ou son affectation a changé. Actualisez les données avant d’enregistrer.",
      );
      return;
    }
    if (status !== baseStatus && !note) {
      setError(
        "Une observation est obligatoire pour chaque changement d’état.",
      );
      return;
    }
    if (showBattery && batteryDirty && !batteryConfirmed) {
      setError(
        "Confirmez le comptage réel des batteries avant d’enregistrer cette modification.",
      );
      return;
    }
    if (
      showBattery &&
      batteryConfirmed &&
      batteryCount !== "" &&
      (!/^\d+$/.test(batteryCount) || Number(batteryCount) > 100000)
    ) {
      setError(
        "Le nombre réel de batteries doit être un entier entre 0 et 100 000, ou rester vide.",
      );
      return;
    }
    if (!note && !final) {
      setError(
        "Saisissez une observation ou une synthèse avant d’enregistrer.",
      );
      return;
    }
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await api<FollowupResponse>(
        `requests/${record.id}/followup/`,
        {
          method: "POST",
          signal: request.signal,
          body: JSON.stringify({
            status,
            expected_status: baseStatus,
            assignment_revision: baseRevision,
            observation: note,
            ...(final ? { summary: final } : {}),
            is_internal: isInternal,
            ...(showBattery && batteryConfirmed
              ? {
                  battery_count:
                    batteryCount === "" ? null : Number(batteryCount),
                }
              : {}),
          }),
        },
      );
      if (request.signal.aborted) return;
      setBaseStatus(response.request.status);
      setStatus(response.request.status);
      setBaseRevision(response.request.assignment?.revision ?? baseRevision);
      setObservation("");
      setSummary("");
      setIsInternal(true);
      setBatteryCount(batteryCountText(response.request.battery_count));
      setBaseBatteryCount(batteryCountText(response.request.battery_count));
      setBatteryConfirmed(false);
      try {
        await onChanged(response.request);
      } catch {
        if (!request.signal.aborted)
          setNotice(
            "Suivi enregistré. Actualisez le dossier pour recharger ses autres données.",
          );
        return;
      }
      if (!request.signal.aborted)
        setNotice("Suivi enregistré dans le dossier SAV.");
    } catch (failure) {
      if (!request.signal.aborted) setError((failure as Error).message);
    } finally {
      submitting.current = false;
      if (!request.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="sav-followup-editor" aria-labelledby={`${id}-heading`}>
      <div className="sav-followup-editor-heading">
        <h3 id={`${id}-heading`}>
          {canWrite ? "Mettre à jour le suivi" : "Suivi du dossier"}
        </h3>
        <span className={`badge status-${record.status}`}>
          {requestStatusLabels[record.status] || record.status}
        </span>
      </div>
      {showBattery && !canWrite && <BatteryConfigurationCard record={record} />}
      {!canWrite ? (
        <div className="sav-followup-readonly">
          <LockKeyhole size={19} />
          <div>
            <strong>Suivi en lecture seule</strong>
            <p>
              {user.role === "technician"
                ? record.assignment?.technician === user.id &&
                  !record.assignment?.accepted
                  ? "Confirmez votre prise en charge pour ajouter une observation ou modifier ce dossier."
                  : "Le suivi est réservé au technicien actuellement désigné, après confirmation de sa prise en charge. Une ancienne intervention ne donne pas de droit d’écriture."
                : "Les observations partagées sont consultables dans l’historique."}
            </p>
          </div>
        </div>
      ) : (
        <form onSubmit={(event) => void submit(event)}>
          {showBattery && (
            <BatteryConfigurationCard record={record}>
              <div className="battery-count-edit">
                <div className="field">
                  <label htmlFor={`${id}-battery-count`}>
                    Nombre réel de batteries
                  </label>
                  <input
                    className="input"
                    id={`${id}-battery-count`}
                    type="number"
                    min={0}
                    max={100000}
                    step={1}
                    value={batteryCount}
                    disabled={busy}
                    onChange={(event) => {
                      setBatteryCount(event.target.value);
                      setBatteryConfirmed(false);
                      setError("");
                    }}
                    aria-describedby={`${id}-battery-help`}
                  />
                  <small id={`${id}-battery-help`}>
                    Renseignez le nombre constaté, y compris les batteries
                    externes. Une valeur vide signifie « non renseigné » ; 0
                    n’est jamais déduit d’une absence de batteries internes.
                  </small>
                </div>
                <label className="battery-count-confirm">
                  <input
                    type="checkbox"
                    checked={batteryConfirmed}
                    disabled={busy}
                    onChange={(event) => {
                      setBatteryConfirmed(event.target.checked);
                      setError("");
                    }}
                  />
                  <span>
                    J’ai vérifié le nombre de batteries sur ce matériel
                  </span>
                </label>
                <p className="battery-configuration-source">
                  La quantité est enregistrée uniquement après cette
                  confirmation et « Enregistrer le suivi », avec votre
                  observation ou synthèse. Une simple observation ne confirme
                  pas le nombre prérempli.
                </p>
              </div>
            </BatteryConfigurationCard>
          )}
          <div className="field">
            <label htmlFor={`${id}-status`}>État du dossier</label>
            <select
              className="input"
              id={`${id}-status`}
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setError("");
              }}
              disabled={busy}
            >
              {Object.entries(requestStatusLabels).map(([key, label]) => (
                <option
                  key={key}
                  value={key}
                  disabled={
                    key !== record.status &&
                    (["ready_for_delivery", "return_to_client"].includes(key) ||
                      (key === "new" &&
                        Boolean(
                          record.assignment?.technician ||
                            record.assigned_technician,
                        )))
                  }
                >
                  {label}
                </option>
              ))}
            </select>
            <small>
              Les états Prêt à être livré et Retour client nécessitent les
              validations de Livraison / Retour ou d’Échange.
            </small>
          </div>
          <div className="field">
            <label htmlFor={`${id}-observation`}>Observation</label>
            <textarea
              id={`${id}-observation`}
              className="input"
              rows={5}
              value={observation}
              onChange={(event) => {
                setObservation(event.target.value);
                setError("");
              }}
              maxLength={10000}
              required={status !== baseStatus}
              disabled={busy}
              aria-describedby={`${id}-observation-help`}
            />
            <small id={`${id}-observation-help`}>
              {status !== baseStatus
                ? "Obligatoire pour expliquer le changement d’état."
                : "Ajoutez une observation sans changer l’état si nécessaire."}
            </small>
          </div>
          <div className="field">
            <label htmlFor={`${id}-summary`}>
              Observation finale / synthèse
            </label>
            <textarea
              id={`${id}-summary`}
              className="input"
              rows={4}
              value={summary}
              onChange={(event) => {
                setSummary(event.target.value);
                setError("");
              }}
              maxLength={10000}
              disabled={busy}
              placeholder="Constats retenus, résultat et suite à donner…"
            />
          </div>
          <label className="sav-followup-private">
            <input
              type="checkbox"
              checked={isInternal}
              onChange={(event) => setIsInternal(event.target.checked)}
              disabled={busy}
            />
            <LockKeyhole size={15} />
            <span>Notes internes — masquées au client</span>
          </label>
          <p className="sav-followup-visibility">
            <Info size={15} />
            {isInternal
              ? "L’état reste visible au client ; votre observation et votre synthèse restent internes."
              : "Votre observation et votre synthèse seront visibles par le client de ce dossier."}
          </p>
          {stale && (
            <div className="sav-followup-warning" role="status">
              Le dossier ou l’affectation a changé depuis le début de votre
              saisie. Vos textes sont conservés ; actualisez l’état avant de
              poursuivre.
            </div>
          )}
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
          <div className="sav-followup-submit">
            <button className="button primary" disabled={busy || stale}>
              {busy ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <Send size={17} />
              )}
              Enregistrer le suivi
            </button>
            {(error || stale) && (
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => void refresh()}
              >
                <RefreshCw size={16} />
                Actualiser l’état
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
