"use client";

import { useState } from "react";
import { Captions, Loader2 } from "lucide-react";
import { DIGEST_LANGUAGES } from "@/lib/worldTypes";

// The video's real narration as text — English by default, machine-translated on request. Exists
// because dubbing every video into a dozen languages is neither cheap nor reliable; the narration
// text is already real (the exact lines the audio speaks), and translating text is what this
// platform's translation service already does well (see app/routers/world.py::get_world_feature).
export default function FeatureTranscript({ featureId, initial }: { featureId: string; initial: string[] }) {
  const [lines, setLines] = useState(initial);
  const [lang, setLang] = useState("en");
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function onLanguageChange(next: string) {
    setLang(next);
    if (next === "en") { setLines(initial); setFailed(false); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/world/features/${featureId}?lang=${encodeURIComponent(next)}`);
      const data = await res.json().catch(() => ({}));
      if (res.ok && Array.isArray(data.transcript)) {
        setLines(data.transcript);
        setFailed(Boolean(data.translation_failed));
      } else {
        setFailed(true);
      }
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  if (initial.length === 0) return null;

  return (
    <section aria-label="Video transcript" className="mt-6 rounded-2xl border border-gray-100 bg-gray-50/60 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
          <Captions className="h-4 w-4 text-purple-500" /> Transcript
        </h2>
        <label className="flex items-center gap-2 text-xs text-gray-500">
          <span className="sr-only">Transcript language</span>
          <select
            value={lang}
            onChange={(e) => onLanguageChange(e.target.value)}
            disabled={loading}
            className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 disabled:opacity-60"
          >
            {DIGEST_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-400" />}
        </label>
      </div>

      {failed && (
        <p role="status" className="mt-2 text-xs text-amber-700">
          Translation is temporarily unavailable, so this is shown in English.
        </p>
      )}

      <ol className="mt-3 space-y-2 text-sm leading-relaxed text-gray-700">
        {lines.map((line, i) => (
          <li key={i} className="[overflow-wrap:anywhere]">{line}</li>
        ))}
      </ol>
    </section>
  );
}
