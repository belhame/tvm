import { api, listResult } from "./api";

/** Read a complete, scoped collection, including any server pagination. */
export async function readCourierCollection<T extends { id: number }>(
  path: string,
  signal: AbortSignal,
): Promise<T[]> {
  const endpoint = new URL(`/api/${path}`, window.location.origin);
  let next: string | null = endpoint.href;
  const seenPages = new Set<string>();
  const records = new Map<number, T>();
  while (next) {
    const url: URL = new URL(next, endpoint);
    if (
      url.origin !== endpoint.origin ||
      url.pathname !== endpoint.pathname ||
      url.username ||
      url.password ||
      seenPages.has(url.href) ||
      seenPages.size >= 1000
    )
      throw new Error("La liste des transports est incomplète. Actualisez votre espace.");
    seenPages.add(url.href);
    const result: T[] | { results: T[]; next?: string | null } = await api<T[] | { results: T[]; next?: string | null }>(
      `${url.pathname}${url.search}`,
      { signal },
    );
    for (const row of listResult(result) as T[]) records.set(row.id, row);
    next = Array.isArray(result) ? null : result.next || null;
  }
  return [...records.values()];
}
