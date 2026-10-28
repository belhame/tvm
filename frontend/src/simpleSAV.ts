export type SimpleSAVPerson = { id: number; name: string };
export type SimpleSAVOptions = {
  clients: SimpleSAVPerson[];
  couriers: (SimpleSAVPerson & {
    courier_kind: "internal" | "client";
    client: number | null;
  })[];
  courier_required: boolean;
  actor_courier: SimpleSAVPerson | null;
};
export type SimpleSAVRequest = {
  id: number;
  call_number: string;
  client_reference: string;
  status: string;
  arrived_at: string | null;
  return_flag: boolean;
  arrival_courier: SimpleSAVPerson;
};
export type SimpleSAVLookupResult = {
  serial_number: string;
  client: SimpleSAVPerson;
  equipment: {
    id: number | null;
    serial_number: string;
    brand: string;
    model: string;
    known: boolean;
    identification: "recorded" | "catalogue" | "unknown";
  };
  coverage: {
    status: "active" | "expired" | "no_coverage" | "unknown" | "not_started";
    warranty_status: "warranty" | "quotation" | "unspecified";
    label: string;
    provisional: boolean;
    warnings: string[];
  };
  return_history: {
    is_return: boolean;
    matches: {
      id: number;
      call_number: string;
      client_reference: string;
      created_at: string;
      arrived_at: string | null;
      serial_number: string;
      relation: "same_equipment" | "replacement";
    }[];
    truncated: boolean;
  };
  open_request: SimpleSAVRequest | null;
  warnings: string[];
};
export type SimpleSAVCreation = Omit<
  SimpleSAVLookupResult,
  "serial_number" | "client" | "open_request"
> & {
  created: boolean;
  request: SimpleSAVRequest;
};
