"use client";

import { PERSONA_TAGS } from "@/lib/types";
import { Check } from "lucide-react";

interface Props {
  selected: string[];
  onChange: (tags: string[]) => void;
  readOnly?: boolean;
}

export default function PersonaChips({ selected, onChange, readOnly = false }: Props) {
  function toggle(tag: string) {
    if (readOnly) return;
    onChange(
      selected.includes(tag) ? selected.filter((t) => t !== tag) : [...selected, tag]
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {PERSONA_TAGS.map((tag) => {
        const active = selected.includes(tag);
        return (
          <button
            key={tag}
            type="button"
            onClick={() => toggle(tag)}
            disabled={readOnly}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              active
                ? "bg-blue-600 border-blue-600 text-white"
                : readOnly
                ? "bg-gray-50 border-gray-200 text-gray-400 cursor-default"
                : "bg-white border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600"
            }`}
          >
            {active && <Check className="h-3 w-3" />}
            {tag}
          </button>
        );
      })}
    </div>
  );
}
