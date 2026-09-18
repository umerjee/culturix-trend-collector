"use client";

import { useEffect, useState } from "react";
import { Check, Clock3, Database, Download, X } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";

type Item = { id: string; source_type: string; region: string | null; title: string; summary: string; category: string; priority_score: number | null; challenge_notes: string | null; pipeline_decision: string | null };

export default function CuratedItemsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [region, setRegion] = useState("IT");

  function load() { fetchAdminData<Item[]>("curated-items").then(setItems).catch(() => setItems([])); }
  useEffect(() => { load(); }, []);

  async function ingest(source_type: "unesco" | "wikipedia") {
    setBusy(true); setMessage("");
    const body = source_type === "unesco"
      ? { source_type, region, limit: 10, max_items: 3 }
      : { source_type, region, title: "History of Italy", max_items: 5 };
    try {
      const res = await fetch("/api/admin/curated-items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      setMessage(`${data.sources_fetched || 0} sources fetched, ${data.items_created || 0} new items created.`);
      load();
    } catch { setMessage("Ingestion failed."); } finally { setBusy(false); }
  }

  async function decide(id: string, decision: string) {
    await fetch(`/api/admin/curated-items/${id}/decision?decision=${decision}`, { method: "POST" });
    setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: decision } : item));
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Database className="h-4 w-4" /> World subjects</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Subject library</h1><p className="mt-1 text-sm text-gray-500">Select the real event, place, or idea first. A toon host is an optional treatment added after the subject is chosen.</p></div>
      <div className="flex items-center gap-2"><input value={region} onChange={(e) => setRegion(e.target.value.toUpperCase())} maxLength={2} className="w-16 rounded-lg border border-gray-200 px-3 py-2 text-sm uppercase" aria-label="ISO region" /><button disabled={busy} onClick={() => ingest("unesco")} className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"><Download className="h-4 w-4" /> Fetch UNESCO</button><button disabled={busy} onClick={() => ingest("wikipedia")} className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50">Fetch Wikipedia</button></div>
    </div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}
    <div className="space-y-3">{items.map((item) => <article key={item.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><div className="flex gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{item.source_type}</span><span>{item.region || "global"}</span><span>{item.category}</span></div><h2 className="mt-1 text-base font-semibold text-gray-900">{item.title}</h2></div><span className="text-sm font-bold text-primary-600">{item.priority_score ?? "-"}/100</span></div><p className="mt-2 text-sm text-gray-600">{item.summary}</p>{item.challenge_notes && <p className="mt-2 text-xs text-gray-400">Review: {item.challenge_notes}</p>}<div className="mt-4 flex items-center gap-2"><button onClick={() => decide(item.id, "include")} className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1.5 text-xs font-semibold text-green-700"><Check className="h-3.5 w-3.5" /> Select subject</button><button onClick={() => decide(item.id, "store_for_later")} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700"><Clock3 className="h-3.5 w-3.5" /> Later</button><button onClick={() => decide(item.id, "exclude")} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600"><X className="h-3.5 w-3.5" /> Exclude</button><span className="ml-auto text-xs text-gray-400">{item.pipeline_decision || "unreviewed"}</span></div></article>)}</div>
  </div>;
}