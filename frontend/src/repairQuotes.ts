export type RepairQuoteCurrency = "TND" | "EUR" | "USD";
export type RepairQuoteDecision = "pending" | "accepted" | "refused";
export type RepairQuoteLine = {
  description: string;
  quantity: string;
  unit_ht: string;
};
export type RepairQuoteInput = {
  lines: RepairQuoteLine[];
  vat_rate: string;
  currency: RepairQuoteCurrency;
  discount_kind: "none" | "percent" | "fixed";
  discount_value: string;
  terms?: string;
  valid_until?: string | null;
};
export type RepairQuoteAmounts = {
  currency: RepairQuoteCurrency;
  precision: number;
  lines: (RepairQuoteLine & { total_ht: string })[];
  subtotal_ht: string;
  discount_kind: RepairQuoteInput["discount_kind"];
  discount_value: string;
  discount_ht: string;
  net_ht: string;
  vat_rate: string;
  vat_amount: string;
  total_ttc: string;
  fully_discounted: boolean;
};
export type RepairQuote = RepairQuoteInput & {
  id: number;
  service_request: number;
  call_number: string;
  client_reference: string;
  client: { id: number; name: string };
  equipment: { serial_number: string; brand: string; model: string };
  reference: string;
  version: number;
  state: "draft" | "issued";
  is_current: boolean;
  revision: number;
  decision_revision: number;
  decision: RepairQuoteDecision;
  amounts: RepairQuoteAmounts;
  issued_at: string | null;
  pdf_url: string | null;
  history: {
    id: number;
    decision: RepairQuoteDecision;
    revision: number;
    decided_at: string;
    actor_label: string;
  }[];
  can_edit: boolean;
  can_issue: boolean;
  can_decide: boolean;
  created_at: string;
};

export const repairQuoteDecisionLabels: Record<RepairQuoteDecision, string> = {
  pending: "En attente de réponse",
  accepted: "Accepté",
  refused: "Refusé",
};

export function repairQuoteInput(quote: RepairQuote): RepairQuoteInput {
  return {
    lines: quote.lines.map((line) => ({
      description: line.description,
      quantity: line.quantity,
      unit_ht: line.unit_ht,
    })),
    vat_rate: quote.vat_rate,
    currency: quote.currency,
    discount_kind: quote.discount_kind,
    discount_value: quote.discount_value,
    terms: quote.terms || "",
    valid_until: quote.valid_until || null,
  };
}

export function repairQuoteMoney(
  value: string,
  currency: RepairQuoteCurrency,
  precision = currency === "TND" ? 3 : 2,
) {
  // Values are server-rounded decimal strings; formatting never recomputes totals.
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return `${value} ${currency}`;
  return `${BigInt(match[1]).toLocaleString("fr-FR")},${(match[2] || "").padEnd(precision, "0")} ${currency}`;
}

export function repairQuotePdfUrl(quote: RepairQuote) {
  if (quote.state !== "issued" || !quote.pdf_url) return null;
  try {
    const url = new URL(quote.pdf_url, window.location.origin);
    return url.origin === window.location.origin &&
      url.pathname === `/api/repair-quotes/${quote.id}/pdf/`
      ? url.pathname
      : null;
  } catch {
    return null;
  }
}
