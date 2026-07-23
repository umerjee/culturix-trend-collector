"use client";

import { useEffect, useState } from "react";
import { PERSONA_TAGS, type PersonaTag } from "@/lib/types";
import { Check, ArrowUpRight, ArrowDownRight } from "lucide-react";

interface Props {
  selected: string[];
  onChange: (tags: string[]) => void;
  readOnly?: boolean;
}

function MomentumDot({ momentum }: { momentum: PersonaTag["momentum"] }) {
  if (momentum === "up") return <ArrowUpRight className="h-3 w-3 text-green-500" />;
  if (momentum === "down") return <ArrowDownRight className="h-3 w-3 text-red-400" />;
  return null;
}

export default function PersonaChips({ selected, onChange, readOnly = false }: Props) {
  const [tags, setTags] = useState<PersonaTag[]>([]);

  useEffect(() => {
    fetch("/api/personas/active")
      .then((r) => (r.ok ? r.json() : []))
      .then((data: PersonaTag[]) => setTags(Array.isArray(data) ? data : []))
      .catch(() => setTags([]));
  }, []);

  // Falls back to the static list (no description/momentum) if the live
  // catalog is empty or unreachable — see PERSONA_TAGS's deprecation note.
  const catalog: PersonaTag[] = tags.length > 0
    ? tags
    : PERSONA_TAGS.map((name) => ({ name, description: "", momentum: null }));

  // Any already-selected tag not currently in the catalog (e.g. an
  // AVATAR_TYPES preset's persona_tags naming an archetype that isn't
  // among today's live-promoted ones, or a tag that's since gone dormant)
  // still gets a chip appended so it's visible and deselectable — without
  // this, a preset selection could silently render as "nothing selected"
  // even though the value is still saved and still fed to the LLM.
  const effective: PersonaTag[] = [
    ...catalog,
    ...selected
      .filter((name) => !catalog.some((t) => t.name === name))
      .map((name) => ({ name, description: "", momentum: null })),
  ];

  function toggle(tag: string) {
    if (readOnly) return;
    onChange(
      selected.includes(tag) ? selected.filter((t) => t !== tag) : [...selected, tag]
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {effective.map((tag) => {
        const active = selected.includes(tag.name);
        return (
          <button
            key={tag.name}
            type="button"
            onClick={() => toggle(tag.name)}
            disabled={readOnly}
            title={tag.description || undefined}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              active
                ? "bg-blue-600 border-blue-600 text-white"
                : readOnly
                ? "bg-gray-50 border-gray-200 text-gray-400 cursor-default"
                : "bg-white border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600"
            }`}
          >
            {active && <Check className="h-3 w-3" />}
            {tag.name}
            <MomentumDot momentum={tag.momentum} />
          </button>
        );
      })}
    </div>
  );
}
