"use client";

import { useState } from "react";
import { Info } from "lucide-react";

interface Props {
  text: string;
  className?: string;
}

// Click-to-toggle (works on touch, not just hover) info icon + popover —
// no reusable tooltip primitive existed anywhere in this codebase before
// this, every prior "hint" was either a static paragraph or a native
// title="" attribute (no touch support, easy to miss). Self-contained, no
// new dependency.
export default function InfoTooltip({ text, className }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <span className={`relative inline-flex ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onBlur={() => setOpen(false)}
        className="text-gray-300 hover:text-blue-500 transition-colors"
        aria-label="More info"
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute z-20 left-1/2 -translate-x-1/2 bottom-full mb-1.5 w-56 rounded-lg bg-gray-900 text-white text-[11px] leading-snug px-2.5 py-2 shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}
