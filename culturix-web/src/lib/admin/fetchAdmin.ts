// Client-side fetch helpers for the /api/admin/data proxy — shared by every
// routed admin page (each now fetches only the slice it needs, rather than
// one giant loadAll() powering every section at once).
export async function fetchAdminData<T>(type: string, params?: Record<string, string | number>): Promise<T> {
  const qs = new URLSearchParams({ type, ...Object.fromEntries(Object.entries(params ?? {}).map(([k, v]) => [k, String(v)])) });
  const res = await fetch(`/api/admin/data?${qs.toString()}`, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${type} → HTTP ${res.status}: ${JSON.stringify(body)}`);
  return body;
}

export async function fetchAdminDetail<T>(type: string, id: number | string): Promise<T> {
  return fetchAdminData<T>(type, { id });
}
