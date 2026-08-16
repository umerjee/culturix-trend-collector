"use client";

import { CheckCircle2, Circle, ChevronDown, ChevronUp, ArrowRight } from "lucide-react";

export interface SetupStep<TAction> {
  label: string;
  hint: string;
  done: boolean;
  action: TAction;
}

export interface OptionalSetupStep<TAction> {
  label: string;
  hint: string;
  action: TAction;
}

interface Props<TAction> {
  title: string;
  steps: SetupStep<TAction>[];
  optionalSteps?: OptionalSetupStep<TAction>[];
  optionalLabel?: string;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate: (action: TAction) => void;
}

// Generalized getting-started checklist, extracted from CultureToons'
// GettingStartedChecklist (the only product that had one) so Posting
// Ideation and Shopify can get the same pattern instead of each product
// inventing its own onboarding-nudge shape. Purely presentational — data
// fetching, polling, and the collapsed/expanded decision stay with each
// product's own adapter component, since those genuinely differ per product.
export default function ProductSetupStatus<TAction>({
  title, steps, optionalSteps, optionalLabel = "Optional, once you're comfortable",
  collapsed, onToggleCollapsed, onNavigate,
}: Props<TAction>) {
  const doneCount = steps.filter((s) => s.done).length;
  const allDone = doneCount === steps.length;
  const firstIncompleteIndex = steps.findIndex((s) => !s.done);

  return (
    <div className="rounded-2xl bg-white border border-gray-100 p-4">
      <button
        onClick={onToggleCollapsed}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900">
            {allDone ? "You're set up" : title}
          </span>
          <span className="text-[11px] text-gray-400">{doneCount}/{steps.length}</span>
        </span>
        {collapsed ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronUp className="h-4 w-4 text-gray-400" />}
      </button>

      {!collapsed && (
        <div className="mt-3 space-y-4">
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={step.label}>
                <button
                  onClick={() => onNavigate(step.action)}
                  className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors ${
                    i === firstIncompleteIndex ? "bg-primary-50 hover:bg-primary-100" : "hover:bg-gray-50"
                  }`}
                >
                  {step.done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
                  ) : (
                    <Circle className={`h-4 w-4 shrink-0 mt-0.5 ${i === firstIncompleteIndex ? "text-primary-400" : "text-gray-300"}`} />
                  )}
                  <span className="flex-1 min-w-0">
                    <span className={`text-xs font-medium ${step.done ? "text-gray-400 line-through" : "text-gray-800"}`}>
                      {step.label}
                    </span>
                    <span className="block text-[11px] text-gray-400">{step.hint}</span>
                  </span>
                  {i === firstIncompleteIndex && <ArrowRight className="h-3.5 w-3.5 text-primary-400 shrink-0 mt-0.5" />}
                </button>
              </li>
            ))}
          </ol>

          {optionalSteps && optionalSteps.length > 0 && (
            <div className="pt-3 border-t border-gray-100">
              <p className="text-[11px] font-medium text-gray-500 mb-1.5">{optionalLabel}</p>
              <div className="flex flex-wrap gap-1.5">
                {optionalSteps.map((o) => (
                  <button
                    key={o.label}
                    onClick={() => onNavigate(o.action)}
                    title={o.hint}
                    className="rounded-full border border-gray-200 text-gray-500 hover:border-primary-300 hover:text-primary-600 text-[11px] px-2.5 py-1 transition-colors"
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
