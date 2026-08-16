"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { Trend, UserRecord, Persona, Cluster } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";
import { PlatformBadge } from "@/components/admin/badges";

export default function SearchPage() {
  const [search, setSearch] = useState("");
  const [trends, setTrends] = useState<Trend[]>([]);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [loaded, setLoaded] = useState(false);

  // All four already cap at a reasonable size server-side (trends 200,
  // clusters/personas 50, users uncapped but typically small) — fetched
  // once on mount and filtered client-side, same pattern the old
  // trends-only search used, just widened to the other three record types.
  useEffect(() => {
    Promise.all([
      fetchAdminData<Trend[]>("trends"),
      fetchAdminData<UserRecord[]>("users"),
      fetchAdminData<Persona[]>("personas"),
      fetchAdminData<Cluster[]>("clusters"),
    ]).then(([t, u, p, c]) => {
      setTrends(t); setUsers(u); setPersonas(p); setClusters(c);
    }).finally(() => setLoaded(true));
  }, []);

  const q = search.toLowerCase();
  const matchedTrends = q ? trends.filter((t) => t.content.toLowerCase().includes(q) || (t.author ?? "").toLowerCase().includes(q)) : [];
  const matchedUsers = q ? users.filter((u) =>
    u.user_id.toLowerCase().includes(q) || u.content_profiles.some((cp) => cp.name.toLowerCase().includes(q))
  ) : [];
  const matchedPersonas = q ? personas.filter((p) => p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)) : [];
  const matchedClusters = q ? clusters.filter((c) => (c.description ?? "").toLowerCase().includes(q)) : [];

  return (
    <div className="space-y-4">
      <h1 className="font-bold text-gray-900 text-xl">Search</h1>
      <input
        autoFocus
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search trends, users, personas, and clusters…"
        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
      />

      {!loaded && search.length > 0 && <p className="text-sm text-gray-400">Loading…</p>}

      {search.length > 0 && loaded && (
        <div className="space-y-6">
          <SearchSection title="Trends" count={matchedTrends.length}>
            <ul className="divide-y divide-gray-50">
              {matchedTrends.slice(0, 20).map((t) => (
                <li key={t.id} className="flex items-center gap-3 px-6 py-3">
                  <PlatformBadge platform={t.platform} />
                  <span className="flex-1 text-sm text-gray-700 truncate">{t.content}</span>
                  <span className="text-xs text-gray-400 whitespace-nowrap">{fmt(t.collected_at)}</span>
                </li>
              ))}
            </ul>
          </SearchSection>

          <SearchSection title="Users" count={matchedUsers.length}>
            <ul className="divide-y divide-gray-50">
              {matchedUsers.slice(0, 20).map((u) => (
                <li key={u.user_id} className="px-6 py-3">
                  <Link href="/admin/users" className="text-sm text-gray-700 hover:text-primary-600 font-mono">
                    {u.user_id.slice(0, 16)}…
                  </Link>
                  <span className="text-xs text-gray-400 ml-2">{u.content_profiles.map((cp) => cp.name).join(", ")}</span>
                </li>
              ))}
            </ul>
          </SearchSection>

          <SearchSection title="Personas" count={matchedPersonas.length}>
            <ul className="divide-y divide-gray-50">
              {matchedPersonas.slice(0, 20).map((p) => (
                <li key={p.id} className="px-6 py-3">
                  <Link href={`/admin/personas/${p.id}`} className="text-sm text-gray-700 hover:text-primary-600 font-medium">
                    {p.name}
                  </Link>
                  <p className="text-xs text-gray-400 line-clamp-1">{p.description}</p>
                </li>
              ))}
            </ul>
          </SearchSection>

          <SearchSection title="Clusters" count={matchedClusters.length}>
            <ul className="divide-y divide-gray-50">
              {matchedClusters.slice(0, 20).map((c) => (
                <li key={c.id} className="px-6 py-3">
                  <Link href={`/admin/clusters/${c.id}`} className="text-sm text-gray-700 hover:text-primary-600 font-medium">
                    {c.description || `Cluster ${c.label}`}
                  </Link>
                </li>
              ))}
            </ul>
          </SearchSection>
        </div>
      )}
    </div>
  );
}

function SearchSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
      <div className="px-6 py-3 border-b border-gray-50 text-xs text-gray-400">
        {title} — {count} result{count !== 1 ? "s" : ""}
      </div>
      {children}
    </div>
  );
}
