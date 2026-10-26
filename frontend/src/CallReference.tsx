import type { RecordData, User } from "./api";

export type CallIdentity = {
  tvm: string;
  client: string;
  visit: string;
};

function referenceText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

/** The visit's INT reference is never used as a fallback TVM call number. */
export function callIdentity(record: RecordData, visit = false): CallIdentity {
  return {
    tvm:
      referenceText(record.call_number) ||
      referenceText(record.request_reference) ||
      (visit ? "" : referenceText(record.reference)),
    client: referenceText(record.client_reference),
    visit: visit
      ? referenceText(record.reference) ||
        referenceText(record.intervention_reference)
      : "",
  };
}

/** A standalone client label makes the TVM fallback explicit without inventing a reference. */
export function callPrimary(
  record: RecordData,
  role: User["role"],
  visit = false,
): string {
  const identity = callIdentity(record, visit);
  if (role === "client" && identity.client) return identity.client;
  if (role === "client")
    return identity.tvm ? `N° TVM ${identity.tvm}` : "N° TVM non renseigné";
  return identity.tvm || "N° TVM non renseigné";
}

export default function CallReference({
  record,
  role,
  visit = false,
  showClient = true,
  showVisit = visit,
  compact = false,
}: {
  record: RecordData;
  role: User["role"];
  visit?: boolean;
  showClient?: boolean;
  showVisit?: boolean;
  compact?: boolean;
}) {
  const identity = callIdentity(record, visit);
  const clientPrimary = role === "client" && !!identity.client;
  const primaryValue = clientPrimary
    ? identity.client
    : identity.tvm || "Non renseigné";

  return (
    <span
      className={`call-reference${compact ? " call-reference-compact" : ""}`}
    >
      <span
        className={`call-reference-primary ${clientPrimary ? "call-reference-client" : "call-reference-tvm"}`}
      >
        <span className="call-reference-label">
          {clientPrimary ? "N° d’appel client" : "N° d’appel TVM"}
        </span>
        <strong className="call-reference-value">{primaryValue}</strong>
      </span>

      {clientPrimary && identity.tvm && (
        <span className="call-reference-secondary call-reference-tvm">
          <span className="call-reference-label">N° d’appel TVM</span>
          <span className="call-reference-value">{identity.tvm}</span>
        </span>
      )}

      {!clientPrimary && showClient && identity.client && (
        <span className="call-reference-secondary call-reference-client">
          <span className="call-reference-label">N° d’appel client</span>
          <span className="call-reference-value">{identity.client}</span>
        </span>
      )}

      {showVisit && identity.visit && (
        <span className="call-reference-secondary call-reference-visit">
          <span className="call-reference-label">Référence de visite</span>
          <span className="call-reference-value">{identity.visit}</span>
        </span>
      )}
    </span>
  );
}
