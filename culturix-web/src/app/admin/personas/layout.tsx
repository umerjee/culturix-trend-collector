"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { Persona } from "@/lib/admin/types";
import { MomentumBadge } from "@/components/admin/badges";

export default function PersonasLayout({ children }: { children: React.ReactNode }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const pathname = usePathname();

  useEffect(() => {
    fetchAdminData<Persona[]>("personas").then(setPersonas).catch(() => setPersonas([])).finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="font-bold text-gray-900 text-xl">Personas</h1>
      <div className="grid lg:grid-cols-[1fr,1.1fr] gap-6 items-start lg:h-[calc(100vh-14rem)]">
        <div className="grid sm:grid-cols-2 gap-4 lg:h-full lg:content-start lg:overflow-y-auto lg:pr-1">
          {loading && <p className="text-gray-400 text-sm sm:col-span-2">Loading…</p>}
          {!loading && personas.length === 0 && (
            <p className="text-gray-400 text-sm sm:col-span-2">No personas yet — run the pipeline first.</p>
          )}
          {personas.map((p) => {
            const active = pathname === `/admin/personas/${p.id}`;
            return (
              <Link
                key={p.id}
                href={`/admin/personas/${p.id}`}
                className={`text-left bg-white rounded-xl border p-6 space-y-3 transition-colors block ${
                  active ? "border-primary-300 ring-1 ring-primary-100" : "border-gray-100 hover:border-gray-200"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-semibold text-gray-900">{p.name}</h3>
                  <MomentumBadge momentum={p.momentum} />
                </div>
                <p className="text-sm text-gray-500 line-clamp-2">{p.description}</p>
                {p.interests?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {p.interests.slice(0, 8).map((i, idx) => (
                      <span key={idx} className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded text-xs">{i}</span>
                    ))}
                  </div>
                )}
                {p.motivations?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {p.motivations.slice(0, 5).map((m, idx) => (
                      <span key={idx} className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded text-xs">{m}</span>
                    ))}
                  </div>
                )}
              </Link>
            );
          })}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-6 lg:h-full lg:overflow-y-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
