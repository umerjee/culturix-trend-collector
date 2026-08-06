"use client";

import { useEffect, useState } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import type { CharacterBrand, BrandUsage } from "@/lib/types";

interface Props {
  brand: CharacterBrand;
  onBrandUpdated: (brand: CharacterBrand) => void;
}

function BudgetBar({ label, spend, budget }: { label: string; spend: number; budget: number | null }) {
  if (!budget) {
    return (
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span>${spend.toFixed(2)} spent — no cap set</span>
      </div>
    );
  }
  const ratio = Math.min(spend / budget, 1);
  const color = ratio >= 1 ? "bg-red-500" : ratio >= 0.8 ? "bg-amber-500" : "bg-blue-500";
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
        <span>{label}</span>
        <span>${spend.toFixed(2)} / ${budget.toFixed(2)}</span>
      </div>
      <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export default function UsageBudgetPanel({ brand, onBrandUpdated }: Props) {
  const [usage, setUsage] = useState<BrandUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [dailyBudgetDraft, setDailyBudgetDraft] = useState(brand.daily_budget?.toString() ?? "");
  const [monthlyBudgetDraft, setMonthlyBudgetDraft] = useState(brand.monthly_budget?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    fetch(`/api/culturetoons/brands/${brand.id}/usage`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then(setUsage)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    setDailyBudgetDraft(brand.daily_budget?.toString() ?? "");
    setMonthlyBudgetDraft(brand.monthly_budget?.toString() ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brand.id]);

  async function saveBudgets(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/culturetoons/brands/${brand.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          daily_budget: dailyBudgetDraft.trim() ? parseFloat(dailyBudgetDraft) : null,
          monthly_budget: monthlyBudgetDraft.trim() ? parseFloat(monthlyBudgetDraft) : null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Failed to save budget");
        return;
      }
      onBrandUpdated(data as CharacterBrand);
      load();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Spend this period</h3>
        <p className="text-xs text-gray-400 mb-4">
          Costs shown are estimates — some generation types don&apos;t yet have a confirmed real price
          (most notably the Qwen-Image fallback tier), so actual spend may be higher than shown below.
        </p>
        {loading || !usage ? (
          <div className="flex items-center gap-2 text-xs text-gray-400 py-4">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
          </div>
        ) : (
          <div className="space-y-4">
            {usage.warning && (
              <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-100 px-3 py-2">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500 mt-0.5 shrink-0" />
                <p className="text-xs text-amber-700">{usage.warning}</p>
              </div>
            )}
            <BudgetBar label="Today" spend={usage.daily_spend} budget={usage.daily_budget} />
            <BudgetBar label="This month" spend={usage.monthly_spend} budget={usage.monthly_budget} />

            {usage.this_month_by_type.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1.5">This month, by type</p>
                <div className="space-y-1">
                  {usage.this_month_by_type.map((row) => (
                    <div key={row.generation_type} className="flex items-center justify-between text-xs text-gray-600">
                      <span className="capitalize">{row.generation_type.replace(/_/g, " ")} ({row.count})</span>
                      <span>${row.cost_usd.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {usage.unpriced_generations_this_month > 0 && (
              <p className="text-[11px] text-gray-400">
                {usage.unpriced_generations_this_month} generation(s) this month have no confirmed price yet and
                aren&apos;t included in the totals above.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="rounded-2xl bg-white border border-gray-100 p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Budget caps</h3>
        <p className="text-xs text-gray-400 mb-4">
          Optional — leave blank for no cap. Generation is blocked once a set cap is reached, with a warning
          shown starting at 80% spent.
        </p>
        <form onSubmit={saveBudgets} className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-gray-500">
            Daily budget ($)
            <input
              type="number" step="0.01" min="0" value={dailyBudgetDraft}
              onChange={(e) => setDailyBudgetDraft(e.target.value)}
              placeholder="No cap"
              className="block mt-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs w-32"
            />
          </label>
          <label className="text-xs text-gray-500">
            Monthly budget ($)
            <input
              type="number" step="0.01" min="0" value={monthlyBudgetDraft}
              onChange={(e) => setMonthlyBudgetDraft(e.target.value)}
              placeholder="No cap"
              className="block mt-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs w-32"
            />
          </label>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-gray-800 transition-colors disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </button>
        </form>
        {error && <p className="text-[11px] text-red-500 mt-2">{error}</p>}
      </div>
    </div>
  );
}
