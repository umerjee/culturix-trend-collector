"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Clock3, Database, Download, Sparkles, X } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import { CATEGORY_LABELS } from "@/lib/worldTypes";

type Item = { id: string; source_type: string; region: string | null; title: string; summary: string; category: string; priority_score: number | null; challenge_notes: string | null; pipeline_decision: string | null; source_url: string | null; subject_category: string | null; created_at: string | null };
type Plan = { era?: string | null; duration_seconds: number; beat_count: number; rationale: string; allowed_durations: number[]; source_chars: number; thin_source: boolean; existing_draft: boolean; visual_styles: { key: string; label: string }[]; estimate: Record<string, { gpu_seconds: number; cost_usd: number }>; suggested_subject_category?: string | null };
// { phenomenon: ["Aurora", ...], species: [...], tech: [...] } — GET /admin/curated-items/suggested-topics.
type TopicSuggestions = Record<string, string[]>;

// Mirrors app/collectors/region_codes.py's REGION_NAMES (36 codes) — the full set the
// backend's trend collectors and World pipeline actually support, not just a curated
// subset. Kept here rather than fetched, matching this page's existing convention.
const COUNTRY_INFO: Record<string, { name: string; continent: string }> = {
  US: { name: "United States", continent: "North America" }, GB: { name: "United Kingdom", continent: "Europe" },
  FR: { name: "France", continent: "Europe" }, DE: { name: "Germany", continent: "Europe" },
  IT: { name: "Italy", continent: "Europe" }, ES: { name: "Spain", continent: "Europe" },
  PT: { name: "Portugal", continent: "Europe" }, CA: { name: "Canada", continent: "North America" },
  AU: { name: "Australia", continent: "Oceania" }, JP: { name: "Japan", continent: "Asia" },
  KR: { name: "South Korea", continent: "Asia" }, IN: { name: "India", continent: "Asia" },
  BR: { name: "Brazil", continent: "South America" }, TR: { name: "Turkey", continent: "Asia" },
  SA: { name: "Saudi Arabia", continent: "Asia" }, AE: { name: "UAE", continent: "Asia" },
  IL: { name: "Israel", continent: "Asia" }, IR: { name: "Iran", continent: "Asia" },
  NG: { name: "Nigeria", continent: "Africa" }, ZA: { name: "South Africa", continent: "Africa" },
  EG: { name: "Egypt", continent: "Africa" }, KE: { name: "Kenya", continent: "Africa" },
  ID: { name: "Indonesia", continent: "Asia" }, PH: { name: "Philippines", continent: "Asia" },
  TH: { name: "Thailand", continent: "Asia" }, VN: { name: "Vietnam", continent: "Asia" },
  MY: { name: "Malaysia", continent: "Asia" }, MX: { name: "Mexico", continent: "North America" },
  AR: { name: "Argentina", continent: "South America" }, CO: { name: "Colombia", continent: "South America" },
  CL: { name: "Chile", continent: "South America" }, PL: { name: "Poland", continent: "Europe" },
  UA: { name: "Ukraine", continent: "Europe" }, PK: { name: "Pakistan", continent: "Asia" },
  CN: { name: "China", continent: "Asia" }, GR: { name: "Greece", continent: "Europe" },
};

export default function CuratedItemsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [region, setRegion] = useState("IT");
  const [ingestContinent, setIngestContinent] = useState("Europe");
  const [wikipediaTitle, setWikipediaTitle] = useState("History of Italy");
  const [wikipediaTitleTouched, setWikipediaTitleTouched] = useState(false);
  const [wikipediaCategory, setWikipediaCategory] = useState("");
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
  const [era, setEra] = useState("");
  const [planCategory, setPlanCategory] = useState("");
  const [generating, setGenerating] = useState(false);
  const [suggestions, setSuggestions] = useState<TopicSuggestions>({});

  function load() { fetchAdminData<Item[]>("curated-items").then(setItems).catch(() => setItems([])); }
  useEffect(() => {
    load();
    fetchAdminData<TopicSuggestions>("curated-item-topic-suggestions").then(setSuggestions).catch(() => setSuggestions({}));
  }, []);

  const continents = Array.from(new Set(Object.values(COUNTRY_INFO).map((country) => country.continent))).sort();
  const countries = Object.entries(COUNTRY_INFO)
    .filter(([, country]) => !continentFilter || country.continent === continentFilter)
    .sort(([, left], [, right]) => left.name.localeCompare(right.name));
  const ingestCountries = Object.entries(COUNTRY_INFO)
    .filter(([, country]) => country.continent === ingestContinent)
    .sort(([, left], [, right]) => left.name.localeCompare(right.name));

  function selectIngestRegion(code: string) {
    setRegion(code);
    // A curator who hasn't typed a custom title yet almost always wants "History of
    // {country}" for that country — pre-fill it as a convenience, but never overwrite
    // something they've already deliberately typed.
    if (!wikipediaTitleTouched) setWikipediaTitle(`History of ${COUNTRY_INFO[code]?.name || code}`);
  }
  const visibleItems = items.filter((item) => {
    if (countryFilter && item.region !== countryFilter) return false;
    if (continentFilter && (!item.region || COUNTRY_INFO[item.region]?.continent !== continentFilter)) return false;
    if ((item.priority_score ?? 0) < Number(minimumPriority)) return false;
    return true;
  });

  async function ingest(source_type: "unesco" | "wikipedia", override?: { title: string; subject_category: string }) {
    setBusy(true); setMessage("");
    const title = override?.title ?? wikipediaTitle;
    const subjectCategory = override?.subject_category ?? wikipediaCategory;
    const body = source_type === "unesco"
      ? { source_type, region, limit: Number(unescoLimit), max_items: 3 }
      : { source_type, region, title, max_items: 5, ...(subjectCategory ? { subject_category: subjectCategory } : {}) };
    try {
      const res = await fetch("/api/admin/curated-items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      // Scoring each fetched source is one or more real LLM calls and runs in the background now
      // (a real Italy fetch measured ~48s inline, which risked the request timing out before this
      // page ever saw a response) — so there's no synchronous items_created count to show yet.
      // Poll the list for a while instead of making the curator refresh manually.
      setMessage(data.message || `${data.sources_fetched || 0} source(s) fetched — scoring in the background.`);
      load();
      let ticks = 0;
      const poll = window.setInterval(() => {
        ticks += 1;
        load();
        if (ticks >= 15) window.clearInterval(poll); // ~90s at 6s/tick, generous for a handful of LLM calls
      }, 6000);
    } catch { setMessage("Ingestion failed."); } finally { setBusy(false); }
  }

  function addSuggestedTopic(category: string, title: string) {
    setWikipediaTitle(title); setWikipediaCategory(category);
    ingest("wikipedia", { title, subject_category: category });
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
    setPlanItem(item); setPlan(null); setPlanError(""); setUseHost(false); setVisualStyle(""); setEra(""); setPlanCategory("");
    try {
      const res = await fetch(`/api/admin/curated-items/${item.id}/plan`);
      const data = await res.json();
      if (!res.ok) { setPlanError(data.detail || "Could not plan this subject."); return; }
      setPlan(data); setDuration(data.duration_seconds); setEra(data.era || "");
      setPlanCategory(data.suggested_subject_category || "");
    } catch { setPlanError("Could not plan this subject."); }
  }

  async function confirmGenerate() {
    if (!planItem || !plan) return;
    setGenerating(true);
    const body: Record<string, unknown> = { duration_seconds: duration, use_host: useHost };
    if (visualStyle) body.visual_style = visualStyle;
    if (era.trim()) body.era = era.trim();
    if (planCategory) body.subject_category = planCategory;
    if (duration === plan.duration_seconds) body.beat_count = plan.beat_count;
    const res = await fetch(`/api/admin/curated-items/${planItem.id}/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    setGenerating(false);
    if (res.ok) {
      const id = planItem.id;
      setItems((current) => current.map((item) => item.id === id ? { ...item, pipeline_decision: "include" } : item));
      setMessage(`Writing a fact-checked ${duration}s script. It is already in World Production, greyed out as "under production", and becomes reviewable in a minute or two. Nothing is rendered until you start it there.`);
      setPlanItem(null);
    } else {
      setPlanError(data.detail || "Generation failed.");
    }
  }

  return <div className="max-w-6xl">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div><div className="flex items-center gap-2 text-primary-600 text-xs font-bold uppercase tracking-wider"><Database className="h-4 w-4" /> World subjects</div><h1 className="mt-2 text-2xl font-bold text-gray-900">Subject library</h1><p className="mt-1 text-sm text-gray-500">Select the real event, place, or idea first. A toon host is an optional treatment added after the subject is chosen.</p></div>
      <Link href="/admin/world-production" className="rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-semibold text-primary-700 hover:bg-primary-100">World Production</Link>
      <div className="w-full rounded-xl border border-gray-100 bg-white p-3">
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-400">Fetch a new subject for</span>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={ingestContinent}
            onChange={(e) => {
              const nextContinent = e.target.value;
              setIngestContinent(nextContinent);
              const firstInContinent = Object.entries(COUNTRY_INFO).find(([, c]) => c.continent === nextContinent);
              if (firstInContinent) selectIngestRegion(firstInContinent[0]);
            }}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
            aria-label="Continent for the new fetch"
          >
            {continents.map((continent) => <option key={continent} value={continent}>{continent}</option>)}
          </select>
          <select
            value={region}
            onChange={(e) => selectIngestRegion(e.target.value)}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
            aria-label="Country for the new fetch"
          >
            {ingestCountries.map(([code, country]) => <option key={code} value={code}>{country.name}</option>)}
          </select>
          <span className="mx-1 h-5 w-px bg-gray-200" aria-hidden="true" />
          <input value={unescoLimit} onChange={(e) => setUnescoLimit(e.target.value)} type="number" min="1" max="10" className="w-16 rounded-lg border border-gray-200 px-3 py-2 text-sm" aria-label="UNESCO site count" title="Number of UNESCO sites to fetch" />
          <button disabled={busy} onClick={() => ingest("unesco")} className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"><Download className="h-4 w-4" /> Fetch UNESCO sites</button>
          <span className="mx-1 h-5 w-px bg-gray-200" aria-hidden="true" />
          <input
            value={wikipediaTitle}
            onChange={(e) => { setWikipediaTitle(e.target.value); setWikipediaTitleTouched(true); }}
            className="w-52 rounded-lg border border-gray-200 px-3 py-2 text-sm"
            aria-label="Wikipedia article title"
            placeholder="Wikipedia title"
            title='Pre-filled from the country above as "History of {country}" — edit freely for a different article'
          />
          <select value={wikipediaCategory} onChange={(e) => setWikipediaCategory(e.target.value)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700" aria-label="Browse category for this Wikipedia fetch" title='Set this for Phenomena/Species/Technology topics — nothing else can tell them apart from a general "custom" subject'>
            <option value="">Category: auto-detect</option>
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          <button disabled={busy} onClick={() => ingest("wikipedia")} className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50">Fetch Wikipedia</button>
        </div>
      </div>
    </div>
    {message && <p className="mb-5 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700">{message}</p>}
    {Object.keys(suggestions).length > 0 && <div className="mb-5 rounded-xl border border-gray-100 bg-white p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400"><Sparkles className="h-3.5 w-3.5" /> Suggested topics — one click fetches and scores it</div>
      <div className="space-y-2">
        {Object.entries(suggestions).map(([category, titles]) => <div key={category} className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs font-semibold text-gray-500">{CATEGORY_LABELS[category] || category}</span>
          {titles.map((title) => <button key={title} disabled={busy} onClick={() => addSuggestedTopic(category, title)} className="rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:border-primary-300 hover:text-primary-700 disabled:opacity-50">{title}</button>)}
        </div>)}
      </div>
    </div>}
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
    <div className="space-y-3">{visibleItems.map((item) => <article key={item.id} className="rounded-xl border border-gray-100 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase text-gray-400"><span>{item.source_type}</span><span>{item.region ? `${COUNTRY_INFO[item.region]?.name || item.region} (${item.region})` : "global"}</span><span>{item.category}</span>{item.subject_category && <span className="text-primary-500">{CATEGORY_LABELS[item.subject_category] || item.subject_category}</span>}{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" className="text-primary-600 normal-case hover:underline">View source</a>}{item.created_at && <span>Fetched {new Date(item.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>}</div><h2 className="mt-1 text-base font-semibold text-gray-900">{item.title}</h2></div><span className="text-sm font-bold text-primary-600">{item.priority_score ?? "-"}/100</span></div><p className="mt-2 text-sm text-gray-600">{item.summary}</p>{item.challenge_notes && <p className="mt-2 text-xs text-gray-400">Review: {item.challenge_notes}</p>}<div className="mt-4 flex items-center gap-2"><button onClick={() => decide(item.id, "include")} className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1.5 text-xs font-semibold text-green-700"><Check className="h-3.5 w-3.5" /> Select subject</button><button onClick={() => decide(item.id, "store_for_later")} className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-700"><Clock3 className="h-3.5 w-3.5" /> Later</button><button onClick={() => decide(item.id, "exclude")} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2.5 py-1.5 text-xs font-semibold text-gray-600"><X className="h-3.5 w-3.5" /> Exclude</button><span className="ml-auto text-xs text-gray-400">{item.pipeline_decision || "unreviewed"}</span></div></article>)}</div>

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
          <label className="mt-4 block text-sm text-gray-600">Period shown
            <input value={era} onChange={(e) => setEra(e.target.value)} maxLength={120} placeholder='For example: Roman Republic, 307 BC' className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm placeholder:text-gray-300" />
            <span className="mt-1 block text-xs text-gray-400">Decides what may appear: only things that existed then. Include a year. Change it if the suggestion is wrong; leave it empty to let the AI decide.</span>
          </label>
          <label className="mt-4 block text-sm text-gray-600">Browse category
            <select value={planCategory} onChange={(e) => setPlanCategory(e.target.value)} className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
              {Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
            <span className="mt-1 block text-xs text-gray-400">Where this shows up on /world. Pre-filled from the ingest choice when there was one; change it if it's wrong.</span>
          </label>
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