import type { User } from "./api";

export type LogisticsClient = { id: number; name: string };
export type CourierOption = {
  id: number;
  name: string;
  courier_kind?: "internal" | "client";
  client?: number | null;
};
export type LogisticsBootstrap = {
  user: User;
  clients: LogisticsClient[];
  couriers: CourierOption[];
  metrics: { pickups: number; ready: number; returns: number };
  capabilities?: {
    can_receive: boolean;
    can_lookup: boolean;
    can_pickups: boolean;
  };
};
export type Pickup = {
  id: number;
  status: "requested" | "assigned" | "collected" | "received" | "cancelled";
  client: LogisticsClient;
  equipment: number | null;
  serial_number: string;
  brand: string;
  model: string;
  client_reference: string;
  fault_description: string;
  pickup_address: string;
  contact_name: string;
  contact_phone: string;
  assigned_courier: number | null;
  assigned_courier_name: string;
  requested_at: string;
  collected_at: string | null;
  received_at: string | null;
  service_request: number | null;
  call_number: string;
  can_assign: boolean;
  can_collect: boolean;
  can_receive: boolean;
  can_cancel: boolean;
  pickup_scope?: "direct" | "end_customer";
  end_customer_name?: string;
};
export type OutboundJob = {
  id: number;
  kind: "delivery" | "return";
  status: "assigned" | "completed" | "cancelled";
  service_request: number;
  call_number: string;
  client_reference: string;
  client: LogisticsClient;
  equipment: number;
  serial_number: string;
  brand: string;
  model: string;
  recipient_name: string;
  handed_over_at: string | null;
  assigned_courier: number;
  assigned_courier_name: string;
  can_handoff: boolean;
  can_assign: boolean;
  delivery_address?: string;
  contact_name?: string;
  contact_phone?: string;
  handed_over_by_name?: string;
  handed_over_by_role?: string;
  active?: boolean;
  cancelled_at?: string | null;
  can_cancel?: boolean;
  blocking_reason?: string | null;
  assignment_mode?: "manual" | "automatic";
  routing_source?: "manual" | "default_courier" | "internal_courier" | "";
  assignment_revision?: number;
  assigned_courier_kind?: "internal" | "client";
};
export type ReceptionCandidate = {
  product_id: number;
  catalogue_import_id: number;
  profile: string;
  brand: string;
  model: string;
  equipment_name: string;
};
export type ReceptionLookup = {
  status: "known" | "catalogue_match" | "ambiguous" | "unknown";
  serial_number: string;
  equipment: null | {
    id: number;
    client: LogisticsClient;
    brand: string;
    model: string;
    equipment_type: "ups";
    equipment_name: string;
  };
  suggested: null | (ReceptionCandidate & { equipment_type: "ups" });
  candidates: ReceptionCandidate[];
  profile_options: string[];
  open_requests: {
    id: number;
    call_number: string;
    client_reference: string;
    arrived_at: string | null;
    status: string;
  }[];
  warnings: string[];
};
export type ReceptionReceipt = {
  receipt_id: number;
  created_request: boolean;
  created_equipment: boolean;
  already_received: boolean;
  request: {
    id: number;
    call_number: string;
    client_reference: string;
    serial_number: string;
    brand: string;
    model: string;
    equipment_type: "ups";
    equipment_name: string;
    client: LogisticsClient;
    arrived_at: string | null;
    status: string;
  };
};
export const pickupLabels: Record<string, string> = {
  requested: "Enlèvement demandé",
  assigned: "Affecté à un livreur",
  collected: "Pris en charge",
  received: "Réceptionné à l’atelier",
  cancelled: "Annulé",
};
export function logisticsUuid() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (entry) =>
    entry.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export function logisticsReference(
  call_number: string,
  client_reference: string,
) {
  return { call_number, client_reference };
}
