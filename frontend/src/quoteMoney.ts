/** Financial totals are calculated by the server. These helpers only display
 * canonical decimal strings and validate unsent input without floating point. */
export const quoteCurrencies = [
  ["TND", "TND — Dinar tunisien"],
  ["EUR", "EUR — Euro"],
  ["USD", "USD — Dollar américain"],
] as const;

export function currencyDigits(currency: string) {
  return currency === "TND" ? 3 : 2;
}

export function decimalInput(value: string) {
  return value.trim().replace(",", ".");
}

export function validAmount(value: string, currency: string) {
  return new RegExp(`^\\d+(?:\\.\\d{1,${currencyDigits(currency)}})?$`).test(
    decimalInput(value),
  );
}

export function validVatRate(value: string) {
  const normalized = decimalInput(value);
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return false;
  const [integer, fraction = ""] = normalized.split(".");
  return (
    BigInt(integer) < 100n ||
    (BigInt(integer) === 100n && !/[1-9]/.test(fraction))
  );
}

export function quoteMoney(value: unknown, currency = "TND") {
  if (value === null || value === undefined || value === "")
    return "Non renseigné";
  const normalized = String(value);
  const match = /^(\d+)(?:\.(\d+))?$/.exec(normalized);
  if (!match) return `${normalized} ${currency}`;
  const fraction = (match[2] || "").padEnd(currencyDigits(currency), "0");
  return `${BigInt(match[1]).toLocaleString("fr-FR")},${fraction} ${currency}`;
}
