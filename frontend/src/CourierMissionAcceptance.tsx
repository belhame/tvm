import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { AlertCircle, Info, LoaderCircle, UserCheck } from "lucide-react";
import { api, type User } from "./api";
import CallReference from "./CallReference";
import type { OutboundJob } from "./logistics";
type DialogProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
};
export default function CourierMissionAcceptance({
  job,
  currentJob,
  user,
  Dialog,
  onClose,
  onSaved,
  onRefresh,
}: {
  job: OutboundJob;
  currentJob?: OutboundJob;
  user: User;
  Dialog: ComponentType<DialogProps>;
  onClose: () => void;
  onSaved: (job: OutboundJob) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const submitting = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  const stale =
    !currentJob ||
    currentJob.assignment_revision !== job.assignment_revision ||
    currentJob.assigned_courier !== user.id ||
    currentJob.can_accept !== true;
  async function accept() {
    if (saving || submitting.current || stale || !job.can_accept) return;
    const request = new AbortController();
    controller.current = request;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const updated = await api<OutboundJob>(
        `logistics/outbound/${job.id}/accept/`,
        {
          method: "POST",
          body: JSON.stringify({
            expected_revision: job.assignment_revision ?? 0,
            accept: true,
          }),
          signal: request.signal,
        },
      );
      if (mounted.current && !request.signal.aborted) {
        setConfirmed(true);
        try {
          await onSaved(updated);
        } catch {
          if (mounted.current && !request.signal.aborted)
            setError(
              "La mission est acceptée. L’actualisation a échoué ; rechargez vos missions avant de poursuivre.",
            );
        }
      }
    } catch (failure) {
      if (mounted.current && !request.signal.aborted) {
        setError((failure as Error).message);
        try {
          await onRefresh();
        } catch {
          if (mounted.current && !request.signal.aborted)
            setError(
              `${(failure as Error).message} Actualisez vos missions pour vérifier l’état réel.`,
            );
        }
      }
    } finally {
      submitting.current = false;
      if (mounted.current && !request.signal.aborted) setSaving(false);
    }
  }
  return (
    <Dialog
      title={confirmed ? "Mission acceptée" : "Accepter la mission"}
      subtitle={job.call_number}
      onClose={() => {
        if (!saving) onClose();
      }}
    >
      <div className="courier-mission-confirm">
        <UserCheck size={30} />
        <h3>
          {confirmed
            ? "Votre acceptation a été enregistrée sur le serveur."
            : "Confirmez-vous l’acceptation de cette mission ?"}
        </h3>
        <p>
          <strong>{job.client.name}</strong>
          <br />
          {job.serial_number} · {job.model}
        </p>
        <CallReference record={job} role={user.role} compact />
        <div className="courier-mission-info">
          <Info size={17} />
          Cette acceptation confirme votre prise en charge du transport. La
          remise physique au client restera à enregistrer séparément.
        </div>
        {stale && !saving && !confirmed && (
          <div className="courier-ready-warning" role="status">
            Cette affectation a changé ou la mission a déjà été acceptée. Fermez
            la confirmation et consultez vos missions actualisées.
          </div>
        )}
        {error && (
          <div className="error-box" role="alert">
            <AlertCircle size={17} />
            {error}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button
          type="button"
          className="button secondary"
          onClick={onClose}
          disabled={saving}
        >
          {confirmed ? "Fermer" : "Annuler"}
        </button>
        {!confirmed && (
          <button
            type="button"
            className="button primary"
            onClick={() => void accept()}
            disabled={saving || stale}
          >
            {saving && <LoaderCircle className="spin" size={17} />}Oui
          </button>
        )}
      </div>
    </Dialog>
  );
}
