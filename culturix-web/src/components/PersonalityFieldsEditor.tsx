"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { PERSONALITY_TRAITS } from "@/lib/types";

// Extracted from CharacterVariantManager.tsx's Personality panel so
// CharacterCreationWizard.tsx and CastPlanWizard.tsx can reuse the exact
// same traits/rules editing UI for their own AI-drafted personality review
// steps, instead of duplicating ~120 lines of slider/rule-list markup.

interface Props {
  traits: Record<string, number>;
  onTraitsChange: React.Dispatch<React.SetStateAction<Record<string, number>>>;
  behavioralRules: string[];
  onBehavioralRulesChange: React.Dispatch<React.SetStateAction<string[]>>;
  speechRules: string[];
  onSpeechRulesChange: React.Dispatch<React.SetStateAction<string[]>>;
}

function RuleList({
  rules, onChange, placeholder,
}: {
  rules: string[];
  onChange: React.Dispatch<React.SetStateAction<string[]>>;
  placeholder: string;
}) {
  const [newRule, setNewRule] = useState("");

  function addRule() {
    if (!newRule.trim()) return;
    onChange((prev) => [...prev, newRule.trim()]);
    setNewRule("");
  }

  return (
    <>
      <div className="space-y-1 mb-2">
        {rules.map((rule, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs text-gray-600 bg-gray-50 rounded-lg px-2 py-1.5">
            <span className="flex-1">{rule}</span>
            <button onClick={() => onChange((prev) => prev.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500">
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          type="text" value={newRule} onChange={(e) => setNewRule(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRule(); } }}
          placeholder={placeholder}
          className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <button onClick={addRule} className="rounded-lg bg-gray-100 text-gray-600 px-2.5 hover:bg-gray-200 transition-colors">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </>
  );
}

export default function PersonalityFieldsEditor({
  traits, onTraitsChange, behavioralRules, onBehavioralRulesChange, speechRules, onSpeechRulesChange,
}: Props) {
  return (
    <>
      <div>
        <p className="text-[11px] font-medium text-gray-500 mb-2">Traits</p>
        <div className="space-y-2">
          {PERSONALITY_TRAITS.map((trait) => (
            <div key={trait} className="flex items-center gap-2">
              <span className="text-xs text-gray-600 w-28 capitalize shrink-0">{trait.replace("_", " ")}</span>
              <input
                type="range" min={0} max={1} step={0.05}
                value={traits[trait] ?? 0.5}
                onChange={(e) => onTraitsChange((prev) => ({ ...prev, [trait]: parseFloat(e.target.value) }))}
                className="flex-1"
              />
              <span className="text-[11px] text-gray-400 w-8 text-right">{(traits[trait] ?? 0.5).toFixed(2)}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="text-[11px] font-medium text-gray-500 mb-2">Behavioral rules</p>
        <RuleList rules={behavioralRules} onChange={onBehavioralRulesChange} placeholder="e.g. tries to negotiate when prices seem high" />
      </div>

      <div>
        <p className="text-[11px] font-medium text-gray-500 mb-2">Speech rules</p>
        <RuleList rules={speechRules} onChange={onSpeechRulesChange} placeholder="e.g. uses short sentences" />
      </div>
    </>
  );
}
