import { ArrowRight } from "lucide-react";

interface Props {
  declining: { name: string }[];
  dormant: { name: string }[];
  settingsHref: string;
}

// Same visual/nudge pattern as PublishingSetupStatus's compact variant —
// amber card, renders null when nothing's wrong, links out to fix it.
function clause(names: { name: string }[], verbPhrase: (plural: boolean) => string): string | null {
  if (names.length === 0) return null;
  const plural = names.length > 1;
  return `${names.map((p) => p.name).join(", ")} ${verbPhrase(plural)}`;
}

export default function PersonaAdvisory({ declining, dormant, settingsHref }: Props) {
  if (declining.length === 0 && dormant.length === 0) return null;

  // Built as separate clauses (rather than one combined sentence over all
  // names) so a profile with both declining and dormant tags doesn't end up
  // describing the declining ones as "haven't shown up" or vice versa.
  const clauses = [
    clause(declining, (plural) => (plural ? "are declining" : "is declining")),
    clause(dormant, (plural) => (plural ? "haven't shown up in trends lately" : "hasn't shown up in trends lately")),
  ].filter((c): c is string => c !== null);

  return (
    <a
      href={settingsHref}
      className="mb-6 -mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 text-xs text-amber-700 hover:border-amber-200 transition-colors"
    >
      <span className="flex-1 min-w-[14rem]">
        <span className="font-semibold">Audience persona losing steam</span> — {clauses.join("; ")}.
      </span>
      <span className="inline-flex items-center gap-1 font-medium shrink-0">
        Review in Settings <ArrowRight className="h-3 w-3" />
      </span>
    </a>
  );
}
