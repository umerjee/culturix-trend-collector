"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/cn";

interface Props {
  text: string;
  className?: string;
}

// Click-to-toggle (works on touch, not just hover) info icon + popover —
// relocated from the old InfoTooltip.tsx into the shared ui/ kit; same
// behavior, just the primary color token updated.
export default function Tooltip({ text, className }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onBlur={() => setOpen(false)}
        className="text-gray-300 hover:text-primary-500 transition-colors"
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
