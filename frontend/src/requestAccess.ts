import type { RecordData, User } from "./api";

export function canWriteRequest(record: RecordData | undefined, user: User) {
  if (user.role === "admin" || user.role === "manager") return true;
  return (
    user.role === "technician" &&
    record?.assignment?.can_write_followup === true
  );
}

export function canEditRequestIntervention(
  intervention: RecordData,
  user: User,
  requests: RecordData[] = [],
) {
  if (user.role === "admin" || user.role === "manager") return true;
  return (
    user.role === "technician" &&
    intervention.technician === user.id &&
    canWriteRequest(
      requests.find((record) => record.id === intervention.service_request),
      user,
    )
  );
}
