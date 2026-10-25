export type RecordData = Record<string, any>;
export type User = {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  role: "admin" | "manager" | "technician" | "client";
  client: number | null;
};
let csrfToken = "";
export function setCsrf(value: string) {
  csrfToken = value;
}
function cookieCsrf() {
  return (
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("csrftoken="))
      ?.split("=")
      .slice(1)
      .join("=") || csrfToken
  );
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body instanceof FormData) {
    // The browser adds the multipart boundary when sending an XLS upload.
    headers.delete("Content-Type");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("X-CSRFToken")) {
    headers.set("X-CSRFToken", cookieCsrf());
  }
  const response = await fetch(
    path.startsWith("/api/") ? path : `/api/${path}`,
    {
      credentials: "same-origin",
      ...options,
      headers,
    },
  );
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) {
    const flatten = (value: unknown): string =>
      typeof value === "string"
        ? value
        : Array.isArray(value)
          ? value.map(flatten).join(" ")
          : value && typeof value === "object"
            ? Object.entries(value)
                .map(
                  ([key, val]) =>
                    `${key === "detail" || key === "non_field_errors" ? "" : `${key} : `}${flatten(val)}`,
                )
                .join(" · ")
            : String(value || "");
    throw new Error(
      flatten(body) || `La requête a échoué (${response.status}).`,
    );
  }
  return body as T;
}
export function listResult(value: any): RecordData[] {
  return Array.isArray(value) ? value : value?.results || [];
}
export function initials(value: string) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((x) => x[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
export const dateFR = (value?: string | null, withTime = false) =>
  value
    ? new Intl.DateTimeFormat("fr-FR", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
      }).format(new Date(value))
    : "Non planifié";
export const money = (value: string | number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(
    Number(value) || 0,
  );
