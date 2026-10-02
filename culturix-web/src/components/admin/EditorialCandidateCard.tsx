"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { flagEmoji, countryName } from "@/lib/worldPlaces";
import {
  missingChecklistItems, validateBlockNote, validatePostForm, validateScriptForm,
  type FieldErrors, type PostForm, PLATFORMS,
} from "@/lib/editorial/validate";

export type RankFactor = { factor: string; score: number; weight: number; reason: string };
export type ScreenHit = { category: string; terms: string[]; where: string };
export type LinkedClaim = { shot_number: number | null; text: string; source_sentence: string | null; flagged_claims: string[]; supported: boolean };
export type Candidate = {
  id: string; status: string; region: string; continent: string;
  trend: { type: string; id: number; title: string; summary: string | null; platforms: string[]; momentum: string | null };
  source: { curated_item_id: string; type: string; label: string; title: string; url: string; excerpt: string };
  rank_score: number | null; rank_factors: RankFactor[];
  safety: { status: string; exclusions: ScreenHit[]; review: ScreenHit[]; checklist: Record<string, boolean> | null;
            note: string | null; reviewed_by: string | null; reviewed_at: string | null };
  script_id: string | null; grounding_status: string; language: string; format: string | null; toon_id: string | null;
  grounding: { grounded: boolean | null; unsupported_claims: string[]; judge_failed: boolean; auto_fixed?: boolean; claims?: LinkedClaim[] } | null;
  approved_by: string | null; approved_at: string | null;
  script?: { hook_line: string | null; tone: string | null; total_duration_seconds: number | null; comedy_score: number | null;
             changed_since_approval: boolean; shots: { shot_number: number; dialogue?: string | null; action?: string | null }[] };
};
export type Meta = {
  formats: Record<string, string>; languages: Record<string, string>; safety_checklist: Record<string, string>;
};

const FACTOR_LABEL: Record<string, string> = {
  trend_momentum: "Trend momentum", source_quality: "Source quality", cultural_relevance: "Cultural relevance",
  novelty: "Novelty", cast_fit: "Cast fit",
};
const CATEGORY_LABEL: Record<string, string> = {
  tragedy: "Tragedy", active_conflict: "Active conflict", religious_worship: "Religious worship",
  historic_conflict: "Historic conflict", religion: "Religion",
};
const TONES = ["funny", "deadpan", "satiric", "wholesome", "chaotic"];
const STATUS_STYLE: Record<string, string> = {
  candidate: "bg-gray-100 text-gray-700", scripted: "bg-blue-50 text-blue-700", approved: "bg-emerald-50 text-emerald-700",
  published: "bg-purple-50 text-purple-700", blocked: "bg-red-50 text-red-700", rejected: "bg-gray-100 text-gray-500",
};

async function post(path: string, body: unknown): Promise<any> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message || data.error || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data;
}

function FieldError({ text }: { text?: string }) {
  return text ? <p className="mt-1 text-xs text-red-600">{text}</p> : null;
}

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>{children}</span>;
}

export default function EditorialCandidateCard({ candidate, meta, onChange }: { candidate: Candidate; meta: Meta; onChange: (c: Candidate) => void }) {
  const c = candidate;
  const place = countryName(c.region) || c.region;
  const closed = c.status === "blocked" || c.status === "rejected";

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 sm:p-5">
      <header className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-gray-900"><span aria-hidden="true">{flagEmoji(c.region)}</span> {place}</span>
        <Badge className="bg-gray-50 text-gray-600">{c.continent}</Badge>
        <Badge className={STATUS_STYLE[c.status] || "bg-gray-100 text-gray-700"}>{c.status}</Badge>
        {c.rank_score !== null && <Badge className="bg-indigo-50 text-indigo-700">Rank {Math.round(c.rank_score * 100)}</Badge>}
        <SafetyBadge status={c.safety.status} />
        {c.script_id && <GroundingBadge status={c.grounding_status} />}
      </header>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section className="rounded-lg bg-gray-50 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Trend · context only, not a fact source</h3>
          <p className="mt-1 font-medium text-gray-900">{c.trend.title}</p>
          {c.trend.summary && <p className="mt-1 text-sm text-gray-600 line-clamp-3">{c.trend.summary}</p>}
          <p className="mt-2 text-xs text-gray-500">
            {c.trend.type} #{c.trend.id}{c.trend.platforms.length ? ` · ${c.trend.platforms.join(", ")}` : ""}
            {c.trend.momentum ? ` · momentum ${c.trend.momentum}` : ""}
          </p>
        </section>
        <section className="rounded-lg bg-amber-50/60 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-800">Source · the only allowed facts</h3>
          <a href={c.source.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 font-medium text-gray-900 hover:text-indigo-700 hover:underline">
            {c.source.title} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
          <p className="text-xs text-gray-500">{c.source.label}</p>
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-medium text-amber-900">Source excerpt</summary>
            <p className="mt-1 max-h-48 overflow-y-auto whitespace-pre-line text-xs leading-relaxed text-gray-700">{c.source.excerpt}</p>
          </details>
        </section>
      </div>

      {c.rank_factors.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium text-gray-700">
            Why it ranks here{c.rank_score === null ? " (not ranked: blocked)" : ""}
          </summary>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="text-gray-500"><tr><th className="py-1 pr-2 font-medium">Factor</th><th className="py-1 pr-2 font-medium">Score</th><th className="py-1 pr-2 font-medium">Weight</th><th className="py-1 font-medium">Reason</th></tr></thead>
            <tbody>
              {c.rank_factors.map((f) => (
                <tr key={f.factor} className="border-t border-gray-100 align-top">
                  <td className="py-1 pr-2 text-gray-800">{FACTOR_LABEL[f.factor] || f.factor}</td>
                  <td className="py-1 pr-2 tabular-nums">{Math.round(f.score * 100)}</td>
                  <td className="py-1 pr-2 tabular-nums">{Math.round(f.weight * 100)}%</td>
                  <td className="py-1 text-gray-600">{f.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <SafetySection candidate={c} meta={meta} onChange={onChange} />
      {!closed && c.safety.status !== "blocked" && <ScriptSection candidate={c} meta={meta} onChange={onChange} />}
      {(c.status === "approved" || c.status === "published") && <PostSection candidate={c} onChange={onChange} />}
    </article>
  );
}

function SafetyBadge({ status }: { status: string }) {
  if (status === "cleared") return <Badge className="bg-emerald-50 text-emerald-700"><ShieldCheck className="h-3 w-3" aria-hidden="true" /> Safety cleared</Badge>;
  if (status === "blocked") return <Badge className="bg-red-50 text-red-700"><ShieldAlert className="h-3 w-3" aria-hidden="true" /> Blocked</Badge>;
  return <Badge className="bg-amber-50 text-amber-800">Safety review pending</Badge>;
}

function GroundingBadge({ status }: { status: string }) {
  if (status === "grounded") return <Badge className="bg-emerald-50 text-emerald-700"><CheckCircle2 className="h-3 w-3" aria-hidden="true" /> Claims grounded</Badge>;
  if (status === "unsupported") return <Badge className="bg-red-50 text-red-700"><XCircle className="h-3 w-3" aria-hidden="true" /> Unsupported claims</Badge>;
  return <Badge className="bg-amber-50 text-amber-800">Fact-check not completed</Badge>;
}

function HitList({ hits, tone }: { hits: ScreenHit[]; tone: "red" | "amber" }) {
  return (
    <ul className={`mt-1 space-y-0.5 text-xs ${tone === "red" ? "text-red-700" : "text-amber-800"}`}>
      {hits.map((h, i) => <li key={i}>{CATEGORY_LABEL[h.category] || h.category} in the {h.where}: {h.terms.join(", ")}</li>)}
    </ul>
  );
}

function SafetySection({ candidate: c, meta, onChange }: { candidate: Candidate; meta: Meta; onChange: (c: Candidate) => void }) {
  const keys = Object.keys(meta.safety_checklist);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const decided = c.safety.status !== "pending" || c.status === "rejected";

  async function decide(decision: "clear" | "block" | "reject") {
    setError(null);
    if (decision === "clear") {
      const missing = missingChecklistItems(checks, keys);
      if (missing.length) return setError("Confirm every item before clearing.");
    }
    if (decision === "block") {
      const problem = validateBlockNote(note);
      if (problem) return setError(problem);
    }
    setBusy(true);
    try {
      onChange(await post(`/api/admin/editorial/${c.id}/safety`, { decision, checklist: checks, note: note || undefined }));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 border-t border-gray-100 pt-4">
      <h3 className="text-sm font-semibold text-gray-900">Cultural-safety review</h3>
      {c.safety.exclusions.length > 0 && (
        <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="text-xs font-semibold text-red-800">Hard exclusion. This candidate cannot be cleared, scripted or published.</p>
          <HitList hits={c.safety.exclusions} tone="red" />
        </div>
      )}
      {c.safety.review.length > 0 && (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-semibold text-amber-900">Check before signing off (not a block on its own):</p>
          <HitList hits={c.safety.review} tone="amber" />
        </div>
      )}
      {decided ? (
        <p className="mt-2 text-xs text-gray-600">
          {c.status === "rejected" ? "Rejected" : c.safety.status === "cleared" ? "Cleared" : "Blocked"}
          {c.safety.reviewed_by ? ` by ${c.safety.reviewed_by}` : ""}{c.safety.reviewed_at ? ` on ${new Date(c.safety.reviewed_at).toLocaleString()}` : ""}
          {c.safety.note ? `: ${c.safety.note}` : ""}
        </p>
      ) : (
        <fieldset className="mt-2" disabled={busy}>
          <legend className="sr-only">Safety checklist</legend>
          {c.safety.exclusions.length === 0 && keys.map((key) => (
            <label key={key} className="flex min-h-[36px] items-start gap-2 text-sm text-gray-700">
              <input type="checkbox" className="mt-1 h-4 w-4" checked={!!checks[key]} onChange={(e) => setChecks((s) => ({ ...s, [key]: e.target.checked }))} />
              {meta.safety_checklist[key]}
            </label>
          ))}
          <label className="mt-2 block text-xs text-gray-600">
            Note (required to block)
            <input value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            {c.safety.exclusions.length === 0 && (
              <button type="button" onClick={() => decide("clear")} className="min-h-[40px] rounded-lg bg-emerald-600 px-4 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">Clear safety</button>
            )}
            <button type="button" onClick={() => decide("block")} className="min-h-[40px] rounded-lg border border-red-200 px-4 text-sm font-semibold text-red-700 hover:bg-red-50">Block</button>
            <button type="button" onClick={() => decide("reject")} className="min-h-[40px] rounded-lg border border-gray-200 px-4 text-sm font-semibold text-gray-700 hover:bg-gray-50">Not a fit</button>
            {busy && <Loader2 className="h-4 w-4 animate-spin self-center text-gray-400" aria-hidden="true" />}
          </div>
          {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
        </fieldset>
      )}
    </section>
  );
}

type Brand = { id: string; name: string };
type Variant = { id: string; name: string; image_url: string | null };

function ScriptSection({ candidate: c, meta, onChange }: { candidate: Candidate; meta: Meta; onChange: (c: Candidate) => void }) {
  const [open, setOpen] = useState(!c.script_id);
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [form, setForm] = useState({ brandId: "", castIds: [] as string[], format: c.format || "trend_to_history", language: c.language || "en", tone: "funny", durationSeconds: "15" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canScript = c.status === "candidate" || c.status === "scripted";

  useEffect(() => {
    if (!open || brands) return;
    fetch("/api/culturetoons/brands").then((r) => (r.ok ? r.json() : [])).then((b: Brand[]) => {
      setBrands(Array.isArray(b) ? b : []);
      if (Array.isArray(b) && b.length === 1) setForm((f) => ({ ...f, brandId: b[0].id }));
    }).catch(() => setBrands([]));
  }, [open, brands]);

  useEffect(() => {
    if (!form.brandId) { setVariants([]); return; }
    fetch(`/api/culturetoons/variants?brand_id=${encodeURIComponent(form.brandId)}`)
      .then((r) => (r.ok ? r.json() : [])).then((v) => setVariants(Array.isArray(v) ? v : [])).catch(() => setVariants([]));
  }, [form.brandId]);

  async function run(label: string, path: string, body: unknown) {
    setError(null);
    setBusy(label);
    try {
      onChange(await post(path, body));
      return true;
    } catch (e) {
      setError(String((e as Error).message));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function generate() {
    const found = validateScriptForm(form, Object.keys(meta.formats), Object.keys(meta.languages));
    setErrors(found);
    if (Object.keys(found).length) return;
    const ok = await run("script", `/api/admin/editorial/${c.id}/script`, {
      brand_id: form.brandId, character_variant_ids: form.castIds, format: form.format, language: form.language,
      tone: form.tone, target_duration_seconds: Number(form.durationSeconds), num_shots: Math.max(2, Math.min(6, Math.round(Number(form.durationSeconds) / 5))),
    });
    if (ok) setOpen(false);
  }

  const claims = c.grounding?.claims || [];
  const approveBlockers = [
    c.safety.status !== "cleared" && "clear the safety review",
    c.grounding_status !== "grounded" && "ground every factual claim",
  ].filter(Boolean) as string[];

  return (
    <section className="mt-4 border-t border-gray-100 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">Comedy script</h3>
        {c.script_id && canScript && (
          <button type="button" onClick={() => setOpen((o) => !o)} className="text-xs font-medium text-indigo-700 hover:underline">
            {open ? "Cancel" : "Write it again"}
          </button>
        )}
      </div>

      {c.script && (
        <div className="mt-2 rounded-lg border border-gray-100 p-3">
          <p className="font-medium text-gray-900">{c.script.hook_line}</p>
          <p className="mt-1 text-xs text-gray-500">
            {c.format ? (c.format.replace(/_/g, " ")) : ""} · {meta.languages[c.language] || c.language} · {c.script.tone}
            {c.script.total_duration_seconds ? ` · ${c.script.total_duration_seconds}s` : ""}
            {c.script.comedy_score != null ? ` · craft score ${c.script.comedy_score}` : ""}
          </p>
          {c.script.changed_since_approval && (
            <p className="mt-2 flex items-center gap-1 text-xs font-medium text-amber-800"><AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> Edited after approval: rendering and publishing are paused until it is re-checked and approved again.</p>
          )}
          <ol className="mt-3 space-y-2">
            {claims.map((claim, i) => (
              <li key={i} className={`rounded-md p-2 text-sm ${claim.supported ? "bg-gray-50" : "bg-red-50"}`}>
                <p className="text-gray-900">
                  <span className="mr-1 text-xs text-gray-500">{claim.shot_number ? `Shot ${claim.shot_number}` : "Hook"}</span>
                  {claim.text}
                </p>
                {claim.source_sentence && <p className="mt-1 text-xs text-emerald-800">Source: “{claim.source_sentence}”</p>}
                {claim.flagged_claims.length > 0 && <p className="mt-1 text-xs text-red-700">Not supported by the source: {claim.flagged_claims.join("; ")}</p>}
              </li>
            ))}
          </ol>
          {c.grounding?.judge_failed && <p className="mt-2 text-xs text-amber-800">The fact-check could not run. Re-check before approving.</p>}
          {c.grounding?.auto_fixed && <p className="mt-2 text-xs text-gray-500">Some lines were rewritten automatically to match the source.</p>}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" disabled={!!busy} onClick={() => run("grounding", `/api/admin/editorial/${c.id}/grounding`, {})}
              className="min-h-[40px] rounded-lg border border-gray-200 px-4 text-sm font-semibold text-gray-800 hover:bg-gray-50 disabled:opacity-50">
              {busy === "grounding" ? "Checking…" : "Re-check facts"}
            </button>
            {(c.status === "scripted" || c.script.changed_since_approval) && (
              <button type="button" disabled={!!busy || approveBlockers.length > 0} onClick={() => run("approve", `/api/admin/editorial/${c.id}/approve`, {})}
                className="min-h-[40px] rounded-lg bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                Approve for render
              </button>
            )}
            {approveBlockers.length > 0 && <span className="text-xs text-gray-500">To approve: {approveBlockers.join(" and ")}.</span>}
            {c.toon_id && <Link href="/admin/comedy-videos" className="text-sm font-medium text-indigo-700 hover:underline">Render it in the Comedy studio →</Link>}
          </div>
        </div>
      )}

      {open && canScript && (
        <fieldset className="mt-3 grid gap-3 sm:grid-cols-2" disabled={!!busy}>
          <legend className="sr-only">Script settings</legend>
          <label className="text-xs text-gray-600">Brand
            <select value={form.brandId} onChange={(e) => setForm((f) => ({ ...f, brandId: e.target.value, castIds: [] }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              <option value="">{brands === null ? "Loading…" : "Choose a brand"}</option>
              {(brands || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
            <FieldError text={errors.brandId} />
          </label>
          <label className="text-xs text-gray-600">Format
            <select value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              {Object.keys(meta.formats).map((key) => <option key={key} value={key}>{key.replace(/_/g, " ")}</option>)}
            </select>
            <span className="mt-1 block text-[11px] text-gray-500">{meta.formats[form.format]}</span>
            <FieldError text={errors.format} />
          </label>
          <div className="text-xs text-gray-600 sm:col-span-2">
            Cast
            <div className="mt-1 flex flex-wrap gap-2">
              {variants.length === 0 && <span className="text-gray-400">{form.brandId ? "No characters in this brand." : "Choose a brand first."}</span>}
              {variants.map((v) => {
                const on = form.castIds.includes(v.id);
                return (
                  <label key={v.id} className={`flex min-h-[36px] cursor-pointer items-center gap-2 rounded-full border px-3 text-sm ${on ? "border-indigo-400 bg-indigo-50 text-indigo-800" : "border-gray-200 text-gray-700"}`}>
                    <input type="checkbox" className="h-4 w-4" checked={on}
                      onChange={(e) => setForm((f) => ({ ...f, castIds: e.target.checked ? [...f.castIds, v.id] : f.castIds.filter((id) => id !== v.id) }))} />
                    {v.name}{!v.image_url && <span className="text-[11px] text-amber-700">(no portrait)</span>}
                  </label>
                );
              })}
            </div>
            <FieldError text={errors.castIds} />
          </div>
          <label className="text-xs text-gray-600">Language
            <select value={form.language} onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              {Object.entries(meta.languages).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-gray-600">Tone
              <select value={form.tone} onChange={(e) => setForm((f) => ({ ...f, tone: e.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
                {TONES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="text-xs text-gray-600">Seconds
              <input inputMode="numeric" value={form.durationSeconds} onChange={(e) => setForm((f) => ({ ...f, durationSeconds: e.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
              <FieldError text={errors.durationSeconds} />
            </label>
          </div>
          <div className="sm:col-span-2 flex items-center gap-3">
            <button type="button" onClick={generate} className="min-h-[40px] rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50">
              {busy === "script" ? "Writing and fact-checking…" : "Write script"}
            </button>
            <span className="text-xs text-gray-500">Takes 1-2 minutes. Facts may only come from the source excerpt.</span>
          </div>
        </fieldset>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
    </section>
  );
}

const EMPTY_POST: PostForm = { platform: "tiktok", postUrl: "", postedAt: "", views: "", likes: "", comments: "", shares: "", saves: "", follows: "", avgWatchSeconds: "", completionRate: "" };

function PostSection({ candidate: c, onChange }: { candidate: Candidate; onChange: (c: Candidate) => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<PostForm>(EMPTY_POST);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function save() {
    const { errors: found, payload } = validatePostForm(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const out = await post(`/api/admin/editorial/${c.id}/posts`, payload);
      onChange(out.candidate);
      setSaved(`Recorded on ${form.platform}.`);
      setForm(EMPTY_POST);
      setOpen(false);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof PostForm, label: string, hint?: string) => (
    <label className="text-xs text-gray-600">{label}
      <input value={form[key]} onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))} inputMode={key === "postUrl" || key === "postedAt" ? undefined : "decimal"}
        type={key === "postedAt" ? "date" : "text"} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" placeholder={hint} />
      <FieldError text={errors[key]} />
    </label>
  );

  return (
    <section className="mt-4 border-t border-gray-100 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-900">Where it was posted</h3>
        <button type="button" onClick={() => setOpen((o) => !o)} className="text-xs font-medium text-indigo-700 hover:underline">{open ? "Cancel" : "Record a post"}</button>
      </div>
      {saved && <p className="mt-1 text-xs text-emerald-700">{saved} Update its numbers later from the performance table.</p>}
      {open && (
        <fieldset className="mt-3 grid gap-3 sm:grid-cols-4" disabled={busy}>
          <legend className="sr-only">Post details</legend>
          <label className="text-xs text-gray-600">Platform
            <select value={form.platform} onChange={(e) => setForm((f) => ({ ...f, platform: e.target.value }))} className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm">
              {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <FieldError text={errors.platform} />
          </label>
          <div className="sm:col-span-2">{field("postUrl", "Post link", "https://…")}</div>
          {field("postedAt", "Posted on")}
          {field("views", "Views")}{field("likes", "Likes")}{field("comments", "Comments")}{field("shares", "Shares")}
          {field("saves", "Saves", "if available")}{field("follows", "Follows", "if available")}
          {field("avgWatchSeconds", "Avg watch (s)", "if available")}{field("completionRate", "Completion %", "if available")}
          <div className="sm:col-span-4 flex items-center gap-3">
            <button type="button" onClick={save} className="min-h-[40px] rounded-lg bg-gray-900 px-4 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50">Save post</button>
            <span className="text-xs text-gray-500">Leave optional metrics empty when the platform doesn&apos;t show them; empty is not zero.</span>
          </div>
        </fieldset>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
    </section>
  );
}
