import { Landmark, Languages, Coins, Users } from "lucide-react";
import type { WorldRegionSummary } from "@/lib/worldTypes";

// Static reference facts (see app/services/world_region_facts.py) — not every region has
// an entry yet, so `facts` can be null; the region page simply omits this strip then.
export default function RegionFactsStrip({ facts }: { facts: WorldRegionSummary["facts"] }) {
  if (!facts) return null;

  const items = [
    { icon: Landmark, label: "Capital", value: facts.capital },
    { icon: Users, label: "Population", value: `~${facts.population_millions.toLocaleString("en-US")}M` },
    { icon: Languages, label: facts.languages.length > 1 ? "Languages" : "Language", value: facts.languages.join(", ") },
    { icon: Coins, label: "Currency", value: `${facts.currency} (${facts.currency_code})` },
  ];

  return (
    <section aria-label="Region facts" className="mb-8 flex flex-wrap gap-3">
      {facts.flag_emoji && (
        <div className="flex items-center rounded-2xl border border-gray-100 bg-white px-4 py-3 text-3xl leading-none shadow-sm">
          <span aria-hidden="true">{facts.flag_emoji}</span>
        </div>
      )}
      {items.map(({ icon: Icon, label, value }) => (
        <div key={label} className="flex items-center gap-2.5 rounded-2xl border border-gray-100 bg-white px-4 py-3 shadow-sm">
          <Icon className="h-4 w-4 shrink-0 text-purple-400" />
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
            <p className="text-sm font-medium text-gray-900">{value}</p>
          </div>
        </div>
      ))}
    </section>
  );
}
