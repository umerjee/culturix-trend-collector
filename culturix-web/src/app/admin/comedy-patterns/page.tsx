"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import GenerateScriptPanel from "@/components/admin/GenerateScriptPanel";

type PerComedian = {
  id: string; name: string; videos: number; videos_with_transcript: number;
  routines: number; jokes: number;
};

type Overview = {
  comedians: number; videos: number; videos_with_transcript: number;
  routines: number; jokes: number; per_comedian: PerComedian[];
};

type TechniqueStat = {
  technique: string; sample_size: number; avg_surprise_score: number | null;
  avg_complexity_score: number | null; avg_punchline_position_seconds: number | null;
  avg_tag_count: number | null;
};

type StructureStat = { structure: string; sample_size: number; avg_surprise_score: number | null };

type ComedyPatternsResponse = {
  overview: Overview;
  technique_stats: TechniqueStat[];
  top_structures: StructureStat[];
};

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-4 py-3">
      <div className="text-2xl font-semibold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  );
}

export default function ComedyPatternsPage() {
  const [data, setData] = useState<ComedyPatternsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    fetchAdminData<ComedyPatternsResponse>("comedy-patterns")
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading && !data) {
    return <div className="flex items-center gap-2 text-gray-500 text-sm"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  }

  return (
    <div className="max-w-5xl space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Comedy patterns</h1>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">
            Real stand-up routines, ingested and analyzed by the comedy-ai pipeline (separate
            repo, shared Postgres, <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">comedy_ai</code> schema).
            The technique/structure stats below are already being fed live into CultureToons&apos;
            &quot;funny&quot;-tone script writer as data-backed craft guidance — never the literal
            jokes, only aggregate timing and technique correlations, to avoid reproducing any real
            comedian&apos;s material.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 shrink-0"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <GenerateScriptPanel />

      {data && (
        <>
          <section>
            <h2 className="text-sm font-semibold text-gray-700 mb-3">Stage 1 pipeline progress</h2>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <StatCard label="Comedians" value={data.overview.comedians} />
              <StatCard label="Videos ingested" value={data.overview.videos} />
              <StatCard label="With a real transcript" value={data.overview.videos_with_transcript} />
              <StatCard label="Routines segmented" value={data.overview.routines} />
              <StatCard label="Jokes analyzed" value={data.overview.jokes} />
            </div>
          </section>

          <section>
            <h2 className="text-sm font-semibold text-gray-700 mb-3">By comedian</h2>
            <div className="overflow-x-auto rounded-xl border border-gray-100 bg-white">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                    <th className="px-4 py-2 font-medium">Comedian</th>
                    <th className="px-4 py-2 font-medium">Videos</th>
                    <th className="px-4 py-2 font-medium">Transcript</th>
                    <th className="px-4 py-2 font-medium">Segmented</th>
                    <th className="px-4 py-2 font-medium">Jokes analyzed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.overview.per_comedian.map((c) => (
                    <tr key={c.id} className="border-b border-gray-50 last:border-0">
                      <td className="px-4 py-2 font-medium text-gray-900">{c.name}</td>
                      <td className="px-4 py-2 text-gray-600">{c.videos}</td>
                      <td className="px-4 py-2 text-gray-600">{c.videos_with_transcript}</td>
                      <td className="px-4 py-2 text-gray-600">{c.routines}</td>
                      <td className="px-4 py-2 text-gray-600">{c.jokes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="text-sm font-semibold text-gray-700 mb-1">Technique stats</h2>
            <p className="text-xs text-gray-500 mb-3">
              Ranked by average surprise score. This is exactly the data currently injected into
              the script writer prompt for &quot;funny&quot;-tone scripts.
            </p>
            {data.technique_stats.length === 0 ? (
              <p className="text-sm text-gray-400 italic">Not enough analyzed jokes yet for honest stats (needs 2+ per technique).</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-gray-100 bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                      <th className="px-4 py-2 font-medium">Technique</th>
                      <th className="px-4 py-2 font-medium">Sample</th>
                      <th className="px-4 py-2 font-medium">Avg surprise</th>
                      <th className="px-4 py-2 font-medium">Avg complexity</th>
                      <th className="px-4 py-2 font-medium">Punchline lands at</th>
                      <th className="px-4 py-2 font-medium">Avg tags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.technique_stats.map((t) => (
                      <tr key={t.technique} className="border-b border-gray-50 last:border-0">
                        <td className="px-4 py-2 font-medium text-gray-900">{t.technique}</td>
                        <td className="px-4 py-2 text-gray-600">{t.sample_size}</td>
                        <td className="px-4 py-2 text-gray-600">{t.avg_surprise_score ?? "—"}</td>
                        <td className="px-4 py-2 text-gray-600">{t.avg_complexity_score ?? "—"}</td>
                        <td className="px-4 py-2 text-gray-600">{t.avg_punchline_position_seconds != null ? `${t.avg_punchline_position_seconds}s` : "—"}</td>
                        <td className="px-4 py-2 text-gray-600">{t.avg_tag_count ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h2 className="text-sm font-semibold text-gray-700 mb-1">Top joke shapes</h2>
            <p className="text-xs text-gray-500 mb-3">
              The sequence of structural beats (e.g. SETUP → MISDIRECTION → PUNCHLINE → TAG) that
              scored highest for surprise across analyzed routines — shapes only, never real joke text.
            </p>
            {data.top_structures.length === 0 ? (
              <p className="text-sm text-gray-400 italic">Not enough analyzed jokes yet for honest stats.</p>
            ) : (
              <ul className="space-y-1.5">
                {data.top_structures.map((s) => (
                  <li key={s.structure} className="flex items-center justify-between rounded-lg border border-gray-100 bg-white px-4 py-2 text-sm">
                    <span className="font-mono text-xs text-gray-700">{s.structure}</span>
                    <span className="text-gray-500 text-xs">{s.sample_size}x · avg surprise {s.avg_surprise_score ?? "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
