import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

// Dedupes the verbatim-identical Chip previously defined separately in
// OnboardingWizard.tsx and SettingsForm.tsx.
export interface ChipProps {
  label: string;
  selected: boolean;
  onClick: () => void;
  className?: string;
}

export default function Chip({ label, selected, onClick, className }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
        selected
          ? "bg-primary-600 border-primary-600 text-white"
          : "bg-white border-gray-200 text-gray-600 hover:border-primary-300 hover:text-primary-600",
        className
      )}
    >
      {selected && <Check className="h-3 w-3" />}
      {label}
    </button>
  );
}
