"use client";

import { useEffect, useState } from "react";
import { REGIONS } from "@/lib/types";
import { Check } from "lucide-react";

interface Props {
  selected: string[];
  onChange: (regions: string[]) => void;
}

// Fetches the canonical region catalog (app/regions.py, via GET /api/regions)
// so this picker can never offer a label the backend's region filter
// (persona_mapper.py) doesn't actually know how to match — falls back to the
// static REGIONS array (see its deprecation note) only if the fetch fails.
export default function RegionChips({ selected, onChange }: Props) {
  const [regions, setRegions] = useState<string[]>([]);

  useEffect(() => {
    fetch("/api/regions")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: { label: string }[]) => setRegions(Array.isArray(data) ? data.map((d) => d.label) : []))
      .catch(() => setRegions([]));
  }, []);

  const effective = regions.length > 0 ? regions : [...REGIONS];

  function toggle(label: string) {
    onChange(selected.includes(label) ? selected.filter((v) => v !== label) : [...selected, label]);
  }

  return (
    <div className="flex flex-wrap gap-2">
      {effective.map((label) => {
        const active = selected.includes(label);
        return (
          <button
            key={label}
            type="button"
            onClick={() => toggle(label)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              active
                ? "bg-blue-600 border-blue-600 text-white"
                : "bg-white border-gray-200 text-gray-600 hover:border-blue-300"
            }`}
          >
            {active && <Check className="h-3 w-3" />}
            {label}
          </button>
        );
      })}
    </div>
  );
}
