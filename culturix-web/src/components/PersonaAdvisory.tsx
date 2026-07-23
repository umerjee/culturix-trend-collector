import { ArrowRight } from "lucide-react";

interface Props {
  declining: { name: string }[];
  dormant: { name: string }[];
  settingsHref: string;
}

// Same visual/nudge pattern as PublishingSetupStatus's compact variant —
// amber card, renders null when nothing's wrong, links out to fix it.
export default function PersonaAdvisory({ declining, dormant, settingsHref }: Props) {
  if (declining.length === 0 && dormant.length === 0) return null;

  const names = [...declining, ...dormant].map((p) => p.name);
  const plural = names.length > 1;
  const summary = dormant.length > 0
    ? `${plural ? "haven't" : "hasn't"} shown up in trends lately`
    : "declining";

  return (
    <a
      href={settingsHref}
      className="mb-6 -mt-2 flex items-center justify-between gap-2 rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 text-xs text-amber-700 hover:border-amber-200 transition-colors"
    >
      <span>
        <span className="font-semibold">Audience persona losing steam</span> — {names.join(", ")}{" "}
        {plural ? "are" : "is"} {summary}.
      </span>
      <span className="inline-flex items-center gap-1 font-medium shrink-0">
        Review in Settings <ArrowRight className="h-3 w-3" />
      </span>
    </a>
  );
}
