"use client";

import { useState } from "react";
import { Captions, Loader2 } from "lucide-react";
import { DIGEST_LANGUAGES } from "@/lib/worldTypes";

// The video's real narration as text — English by default, machine-translated on request. Exists
// because dubbing every video into a dozen languages is neither cheap nor reliable; the narration
// text is already real (the exact lines the audio speaks), and translating text is what this
// platform's translation service already does well (see app/routers/world.py::get_world_feature).
// `initialLang`/`initialLines` let a parent that already fetched the site-language translation
// start the transcript there instead of in English. `initial` stays the English original.
export default function FeatureTranscript({
  featureId, initial, initialLang = "en", initialLines, initialFailed = false,
}: {
  featureId: string; initial: string[]; initialLang?: string; initialLines?: string[]; initialFailed?: boolean;
}) {
  const [lines, setLines] = useState(initialLines ?? initial);
  const [lang, setLang] = useState(initialLang);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(initialFailed);

  async function onLanguageChange(next: string) {
    setLang(next);
    if (next === "en" && initialLang === "en") { setLines(initial); setFailed(false); return; }
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

  if (lines.length === 0 && initial.length === 0) return null;

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
            className="min-h-[44px] rounded-lg border border-gray-200 bg-white px-2 text-xs text-gray-700 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500"
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
