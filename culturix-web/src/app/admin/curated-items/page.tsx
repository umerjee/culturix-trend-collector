"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Clock3, Database, Download, X } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";

type Item = { id: string; source_type: string; region: string | null; title: string; summary: string; category: string; priority_score: number | null; challenge_notes: string | null; pipeline_decision: string | null; created_at: string | null };

const COUNTRY_INFO: Record<string, { name: string; continent: string }> = {
  US: { name: "United States", continent: "North America" }, CN: { name: "China", continent: "Asia" },
  IN: { name: "India", continent: "Asia" }, JP: { name: "Japan", continent: "Asia" },
  DE: { name: "Germany", continent: "Europe" }, FR: { name: "France", continent: "Europe" },
  IT: { name: "Italy", continent: "Europe" }, ES: { name: "Spain", continent: "Europe" },
  GB: { name: "United Kingdom", continent: "Europe" }, MX: { name: "Mexico", continent: "North America" },
  BR: { name: "Brazil", continent: "South America" }, CA: { name: "Canada", continent: "North America" },
  AU: { name: "Australia", continent: "Oceania" }, TR: { name: "Turkey", continent: "Asia" },
  KR: { name: "South Korea", continent: "Asia" }, SA: { name: "Saudi Arabia", continent: "Asia" },
  EG: { name: "Egypt", continent: "Africa" }, GR: { name: "Greece", continent: "Europe" },
  PT: { name: "Portugal", continent: "Europe" }, IR: { name: "Iran", continent: "Asia" },
};

export default function CuratedItemsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [region, setRegion] = useState("IT");
  const [wikipediaTitle, setWikipediaTitle] = useState("History of Italy");
  const [unescoLimit, setUnescoLimit] = useState("5");
  const [continentFilter, setContinentFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [minimumPriority, setMinimumPriority] = useState("0");

  function load() { fetchAdminData<Item[]>("curated-items").then(setItems).catch(() => setItems([])); }
  useEffect(() => { load(); }, []);

  const continents = Array.from(new Set(Object.values(COUNTRY_INFO).map((country) => country.continent))).sort();
  const countries = Object.entries(COUNTRY_INFO)
    .filter(([, country]) => !continentFilter || country.continent === continentFilter)
    .sort(([, left], [, right]) => left.name.localeCompare(right.name));
  const visibleItems = items.filter((item) => {
    if (countryFilter && item.region !== countryFilter) return false;
    if (continentFilter && (!item.region || COUNTRY_INFO[item.region]?.continent !== continentFilter)) return false;
    if ((item.priority_score ?? 0) < Number(minimumPriority)) return false;
    return true;
  });

  async function ingest(source_type: "unesco" | "wikipedia") {
    setBusy(true); setMessage("");
    const body = source_type === "unesco"
      ? { source_type, region, limit: Number(unescoLimit), max_items: 3 }
      : { source_type, region, title: wikipediaTitle, max_items: 5 };
    try {
      const res = await fetch("/api/admin/curated-items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      setMessage(`${data.sources_fetched || 0} sources fetched, ${data.items_created || 0} new items created.`);
      load();
    } catch { setMessage("Ingestion failed."); } finally { setBusy(false); }
  }

  async function decide(id: string, decision: string) {
    if (decision === "include") {
      await selectSubject(id);
      return;
    }
    await fetch(`/api/admin/curated-items/${id}/decision?decision=${decision}`, { method: "POST" });
    setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: decision } : item));
  }

  async function selectSubject(id: string) {
    setMessage("Starting script and cinematic planning...");
    const res = await fetch(`/api/admin/curated-items/${id}/generate`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    setMessage(res.ok ? "World script and cinematic plan generation started. The draft will appear in World content when ready." : (data.detail || "Generation failed."));
    if (res.ok) setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: "include" } : item));
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Database className="h-4 w-4" /> World subjects</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Subject library</h1><p className="mt-1 text-sm text-gray-500">Select the real event, place, or idea first. A toon host is an optional treatment added after the subject is chosen.</p></div>
      <Link href="/world" target="_blank" className="rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-semibold text-primary-700 hover:bg-primary-100">View World Content</Link>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <input value={region} onChange={(e) => setRegion(e.target.value.toUpperCase())} maxLength={2} className="w-16 rounded-lg border border-gray-200 px-3 py-2 text-sm uppercase" aria-label="ISO region for fetching" title="ISO country code used for new fetches" />
        <input value={unescoLimit} onChange={(e) => setUnescoLimit(e.target.value)} type="number" min="1" max="10" className="w-20 rounded-lg border border-gray-200 px-3 py-2 text-sm" aria-label="UNESCO site count" title="UNESCO sites to fetch" />
        <button disabled={busy} onClick={() => ingest("unesco")} className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"><Download className="h-4 w-4" /> Fetch UNESCO</button>
        <input value={wikipediaTitle} onChange={(e) => setWikipediaTitle(e.target.value)} className="w-44 rounded-lg border border-gray-200 px-3 py-2 text-sm" aria-label="Wikipedia title" placeholder="Wikipedia title" />
        <button disabled={busy} onClick={() => ingest("wikipedia")} className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50">Fetch Wikipedia</button>
      </div>
    </div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}
    <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-gray-100 bg-white p-3">
      <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Browse</span>
      <select value={continentFilter} onChange={(e) => { setContinentFilter(e.target.value); setCountryFilter(""); }} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by continent">
        <option value="">All continents</option>{continents.map((continent) => <option key={continent} value={continent}>{continent}</option>)}
      </select>
      <select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by country">
        <option value="">All countries{continentFilter ? ` in ${continentFilter}` : ""}</option>{countries.map(([code, country]) => <option key={code} value={code}>{country.name}</option>)}
      </select>
      <select value={minimumPriority} onChange={(e) => setMinimumPriority(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Filter by priority ranking">
        <option value="0">All rankings</option>
        <option value="90">Top ranked · 90+</option>
        <option value="75">Strong · 75+</option>
        <option value="60">Promising · 60+</option>
      </select>
      {(continentFilter || countryFilter || minimumPriority !== "0") && <button onClick={() => { setContinentFilter(""); setCountryFilter(""); setMinimumPriority("0"); }} className="px-2 py-2 text-xs font-medium text-primary-600 hover:text-primary-800">Clear filters</button>}
      <span className="ml-auto text-xs text-gray-400">{visibleItems.length} of {items.length} subjects</span>
    </div>
    <div className="space-y-3">{visibleItems.map((item) => <article key={item.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{item.source_type}</span><span>{item.region ? `${COUNTRY_INFO[item.region]?.name || item.region} (${item.region})` : "global"}</span><span>{item.category}</span>{item.created_at && <span>Fetched {new Date(item.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>}</div><h2 className="mt-1 text-base font-semibold text-gray-900">{item.title}</h2></div><span className="text-sm font-bold text-primary-600">{item.priority_score ?? "-"}/100</span></div><p className="mt-2 text-sm text-gray-600">{item.summary}</p>{item.challenge_notes && <p className="mt-2 text-xs text-gray-400">Review: {item.challenge_notes}</p>}<div className="mt-4 flex items-center gap-2"><button onClick={() => decide(item.id, "include")} className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1.5 text-xs font-semibold text-green-700"><Check className="h-3.5 w-3.5" /> Select subject</button><button onClick={() => decide(item.id, "store_for_later")} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700"><Clock3 className="h-3.5 w-3.5" /> Later</button><button onClick={() => decide(item.id, "exclude")} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600"><X className="h-3.5 w-3.5" /> Exclude</button><span className="ml-auto text-xs text-gray-400">{item.pipeline_decision || "unreviewed"}</span></div></article>)}</div>
  </div>;
}