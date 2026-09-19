"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Clock3, Database, Download, X } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";

type Item = { id: string; source_type: string; region: string | null; title: string; summary: string; category: string; priority_score: number | null; challenge_notes: string | null; pipeline_decision: string | null; source_url: string | null; created_at: string | null };
type Plan = { duration_seconds: number; beat_count: number; rationale: string; allowed_durations: number[]; source_chars: number; thin_source: boolean; existing_draft: boolean; visual_styles: { key: string; label: string }[]; estimate: Record<string, { gpu_seconds: number; cost_usd: number }> };

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
  const [planItem, setPlanItem] = useState<Item | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState("");
  const [duration, setDuration] = useState<number>(20);
  const [useHost, setUseHost] = useState(false);
  const [visualStyle, setVisualStyle] = useState("");
  const [generating, setGenerating] = useState(false);

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
      const item = items.find((candidate) => candidate.id === id);
      if (item) await openPlan(item);
      return;
    }
    await fetch(`/api/admin/curated-items/${id}/decision?decision=${decision}`, { method: "POST" });
    setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: decision } : item));
  }

  async function openPlan(item: Item) {
    setPlanItem(item); setPlan(null); setPlanError(""); setUseHost(false); setVisualStyle("");
    try {
      const res = await fetch(`/api/admin/curated-items/${item.id}/plan`);
      const data = await res.json();
      if (!res.ok) { setPlanError(data.detail || "Could not plan this subject."); return; }
      setPlan(data); setDuration(data.duration_seconds);
    } catch { setPlanError("Could not plan this subject."); }
  }

  async function confirmGenerate() {
    if (!planItem || !plan) return;
    setGenerating(true);
    const body: Record<string, unknown> = { duration_seconds: duration, use_host: useHost };
    if (visualStyle) body.visual_style = visualStyle;
    if (duration === plan.duration_seconds) body.beat_count = plan.beat_count;
    const res = await fetch(`/api/admin/curated-items/${planItem.id}/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    setGenerating(false);
    if (res.ok) {
      const id = planItem.id;
      setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: "include" } : item));
      setMessage(`Writing a fact-checked ${duration}s script. It appears in World Production in about a minute; nothing is rendered until you start it there.`);
      setPlanItem(null);
    } else {
      setPlanError(data.detail || "Generation failed.");
    }
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Database className="h-4 w-4" /> World subjects</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Subject library</h1><p className="mt-1 text-sm text-gray-500">Select the real event, place, or idea first. A toon host is an optional treatment added after the subject is chosen.</p></div>
      <Link href="/admin/world-production" className="rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-semibold text-primary-700 hover:bg-primary-100">World Production</Link>
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
    <div className="space-y-3">{visibleItems.map((item) => <article key={item.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{item.source_type}</span><span>{item.region ? `${COUNTRY_INFO[item.region]?.name || item.region} (${item.region})` : "global"}</span><span>{item.category}</span>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="text-primary-600 normal-case hover:underline">View source</a>}{item.created_at && <span>Fetched {new Date(item.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>}</div><h2 className="mt-1 text-base font-semibold text-gray-900">{item.title}</h2></div><span className="text-sm font-bold text-primary-600">{item.priority_score ?? "-"}/100</span></div><p className="mt-2 text-sm text-gray-600">{item.summary}</p>{item.challenge_notes && <p className="mt-2 text-xs text-gray-400">Review: {item.challenge_notes}</p>}<div className="mt-4 flex items-center gap-2"><button onClick={() => decide(item.id, "include")} className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1.5 text-xs font-semibold text-green-700"><Check className="h-3.5 w-3.5" /> Select subject</button><button onClick={() => decide(item.id, "store_for_later")} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700"><Clock3 className="h-3.5 w-3.5" /> Later</button><button onClick={() => decide(item.id, "exclude")} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600"><X className="h-3.5 w-3.5" /> Exclude</button><span className="ml-auto text-xs text-gray-400">{item.pipeline_decision || "unreviewed"}</span></div></article>)}</div>

    {planItem && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Plan World video">
      <div className="w-full max-w-lg max-h-[90dvh] overflow-y-auto rounded-2xl bg-white p-5 sm:p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">{planItem.title}</h2>
        <p className="mt-1 text-xs text-gray-400">{planItem.source_type} · {planItem.category}{planItem.source_url && <> · <a href={planItem.source_url} target="_blank" rel="noreferrer" className="text-primary-600 hover:underline">source</a></>}</p>
        {!plan && !planError && <p className="mt-6 text-sm text-gray-500">Planning the best length for this subject...</p>}
        {planError && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{planError}</p>}
        {plan && <>
          <p className="mt-4 text-sm text-gray-700"><span className="font-semibold">Suggested: {plan.duration_seconds}s, {plan.beat_count} beats.</span> {plan.rationale}</p>
          {plan.thin_source && <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">Short source text ({plan.source_chars} characters): longer videos would need invented detail, so the suggestion is capped.</p>}
          {plan.existing_draft && <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">A draft already exists for this subject. Archive it in World Production to regenerate.</p>}
          <div className="mt-4 grid grid-cols-3 min-[420px]:grid-cols-5 gap-2">{plan.allowed_durations.map((d) => <button key={d} onClick={() => setDuration(d)} className={`rounded-lg border px-2 py-2 text-center text-sm ${duration === d ? "border-primary-600 bg-primary-50 font-bold text-primary-700" : "border-gray-200 text-gray-600"}`}>{d}s<span className="block text-[10px] font-normal text-gray-400">~${plan.estimate[String(d)]?.cost_usd.toFixed(2)} render</span></button>)}</div>
          <label className="mt-4 block text-sm text-gray-600">Look
            <select value={visualStyle} onChange={(e) => setVisualStyle(e.target.value)} className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
              <option value="">Photorealistic (default)</option>
              {plan.visual_styles.map((style) => <option key={style.key} value={style.key}>{style.label}</option>)}
            </select>
          </label>
          <label className="mt-4 flex items-start gap-2 text-sm text-gray-600"><input type="checkbox" checked={useHost} onChange={(e) => setUseHost(e.target.checked)} className="mt-0.5" /><span>Add an on-screen host character <span className="text-xs text-gray-400">(optional; the default is real subject footage with narration)</span></span></label>
          <p className="mt-4 text-xs text-gray-400">This writes and fact-checks the script only. Rendering is a separate paid step in World Production.</p>
        </>}
        <div className="mt-6 flex justify-end gap-2">
          <button onClick={() => setPlanItem(null)} className="min-h-11 rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-600">Cancel</button>
          <button disabled={!plan || generating || plan.existing_draft} onClick={confirmGenerate} className="min-h-11 rounded-lg bg-primary-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">{generating ? "Starting..." : `Write ${duration}s script`}</button>
        </div>
      </div>
    </div>}
  </div>;
}