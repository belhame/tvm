import type { RecordData, User } from "./api";

export type BatteryConfiguration = {
  status: "matched" | "unknown" | "ambiguous" | "stale";
  reference: string | null;
  configuration: string | null;
  nominal_count: number | null;
  voltage_v: string | null;
  capacity_ah: string | null;
  suppliers: string[];
  source: string;
  warnings: string[];
  external_battery_required: boolean;
  recorded_intervention_counts: {
    intervention_id: number;
    reference: string;
    battery_count: number;
  }[];
  is_saved_reference: boolean;
};

export function canViewBattery(record: RecordData, user: User) {
  return (
    ["admin", "manager", "technician"].includes(user.role) &&
    (record.assignment?.accepted === true ||
      Boolean(record.battery_configuration) ||
      (record.battery_count !== null && record.battery_count !== undefined) ||
      Boolean(record.battery_count_source))
  );
}

export function batteryCountText(value: unknown) {
  return typeof value === "number" && Number.isInteger(value)
    ? String(value)
    : "";
}
