import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

// Standardizes the dashed-border empty-state pattern previously copy-pasted
// across dashboard/page.tsx, dashboard/performance/page.tsx, etc.
export default function EmptyState({ icon: Icon, title, description, action, className }: Props) {
  return (
    <div className={cn("rounded-2xl border-2 border-dashed border-gray-200 py-20 text-center", className)}>
      <Icon className="h-10 w-10 text-gray-300 mx-auto mb-4" />
      <h3 className="font-semibold text-gray-700 mb-2">{title}</h3>
      {description && <p className="text-sm text-gray-400 max-w-xs mx-auto">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
