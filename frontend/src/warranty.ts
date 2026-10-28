export type WarrantyCheck = {
  basis: "recorded" | "catalogue" | "unknown";
  status: "active" | "expired" | "not_started" | "no_coverage" | "unknown";
  checked_on: string;
  manufacturer: string;
  profile: string;
  family: string;
  generation: string;
  model_name: string;
  industrial_part_number: string;
  commercial_part_number: string;
  manufactured_on: string | null;
  manufacture_date_basis: {
    type?: string;
    precision?: "day" | "week" | "month" | "unknown";
    reconstructed?: boolean;
    source?: string;
    blocked_reason?: string | null;
  };
  catalogue_identity_consistent: boolean;
  starts_on: string | null;
  ends_on: string | null;
  duration_months: number | null;
  scope: string;
  source: {
    catalogue_import_id: number | null;
    revision: string;
    product_sheet: string;
    product_row: number | null;
    warranty_sheet: string;
    warranty_row: number | null;
    warranty_match_type: string;
  };
  warnings: string[];
  rule: { code: string; start_offset_months: number };
  provisional: boolean;
};

export function warrantyScopeLabel(scope: string) {
  const labels: Record<string, string> = {
    electronics: "Électronique",
    battery: "Batteries",
    batteries: "Batteries",
    electronics_and_batteries: "Électronique et batteries",
    global: "Équipement complet",
    unspecified: "Étendue à confirmer",
  };
  return labels[scope] || scope || "Étendue à confirmer";
}
