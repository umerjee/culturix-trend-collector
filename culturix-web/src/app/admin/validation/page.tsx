"use client";

import { useEffect, useState } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import { fetchAdminData } from "@/lib/admin/fetchAdmin";
import type { ValidationLogEntry, ContentCheckLogEntry } from "@/lib/admin/types";
import { fmt } from "@/lib/admin/types";

const PAGE_SIZE = 500;

export default function ValidationPage() {
  const [log, setLog] = useState<ValidationLogEntry[]>([]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [checkLog, setCheckLog] = useState<ContentCheckLogEntry[]>([]);

  useEffect(() => {
    setLoading(true);
    fetchAdminData<ValidationLogEntry[]>("validation", { limit })
      .then(setLog)
      .catch(() => setLog([]))
      .finally(() => { setLoading(false); setLoadingMore(false); });
  }, [limit]);

  useEffect(() => {
    fetchAdminData<ContentCheckLogEntry[]>("content-check-log").then(setCheckLog).catch(() => setCheckLog([]));
  }, []);

  const filtered = log.filter((v) => {
    if (statusFilter !== "all" && v.status !== statusFilter) return false;
    if (sourceFilter !== "all" && v.source !== sourceFilter) return false;
    return true;
  });
  const approvedCount = log.filter((v) => v.status === "approved").length;
  const rejectedCount = log.filter((v) => v.status === "rejected").length;

  if (loading && log.length === 0) return <p className="text-sm text-gray-400 text-center py-16">Loading…</p>;

  return (
    <div className="space-y-6">
      <h1 className="font-bold text-gray-900 text-xl">Validation</h1>

      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <p className="text-2xl font-bold text-gray-900">{log.length}</p>
            <span className="text-xs text-gray-500">Checked</span>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <p className="text-2xl font-bold text-emerald-600">{approvedCount}</p>
            <span className="text-xs text-gray-500">Approved</span>
          </div>
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <p className="text-2xl font-bold text-red-600">{rejectedCount}</p>
            <span className="text-xs text-gray-500">Rejected</span>
          </div>
        </div>

        <div className="flex gap-3 flex-wrap">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="all">All statuses</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="all">All sources</option>
            <option value="cluster">Cluster</option>
            <option value="idea">Idea</option>
          </select>
          <span className="text-sm text-gray-400 self-center">{filtered.length} entries</span>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-50 bg-gray-50">
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Source</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Subject</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Reason</th>
                <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Checked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-10 text-center text-sm text-gray-400">No validation records yet.</td>
                </tr>
              )}
              {filtered.map((v) => (
                <tr key={v.id} className="hover:bg-gray-50 align-top">
                  <td className="px-6 py-3 whitespace-nowrap">
                    {v.status === "approved" ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-emerald-50 text-emerald-700">
                        <CheckCircle className="h-3 w-3" /> Approved
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-red-50 text-red-700">
                        <XCircle className="h-3 w-3" /> Rejected
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-3 text-gray-500 capitalize whitespace-nowrap">{v.source}</td>
                  <td className="px-6 py-3 max-w-xs text-gray-800">{v.subject || "(untitled)"}</td>
                  <td className="px-6 py-3 max-w-sm text-gray-500">{v.reason || "—"}</td>
                  <td className="px-6 py-3 text-gray-400 text-xs whitespace-nowrap">{fmt(v.checked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {log.length >= limit && (
          <div className="text-center">
            <button
              onClick={() => { setLoadingMore(true); setLimit((l) => l + PAGE_SIZE); }}
              disabled={loadingMore}
              className="px-4 py-2 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 disabled:opacity-50 transition"
            >
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>

      {/* Content-check scoring log — previously invisible in the UI. */}
      {checkLog.length > 0 && (
        <div>
          <h2 className="font-semibold text-gray-900 text-sm mb-3">Content check log</h2>
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50 bg-gray-50">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Score change</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Trend / Freshness / Persona</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status change</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Action</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Checked</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {checkLog.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3 text-gray-700 whitespace-nowrap">{c.previous_score ?? "—"} → {c.new_score ?? "—"}</td>
                    <td className="px-6 py-3 text-gray-500 whitespace-nowrap text-xs">
                      {c.trend_score ?? "—"} / {c.freshness_score ?? "—"} / {c.persona_score ?? "—"}
                    </td>
                    <td className="px-6 py-3 text-gray-500 whitespace-nowrap capitalize">{c.previous_status ?? "—"} → {c.new_status ?? "—"}</td>
                    <td className="px-6 py-3 text-gray-500">{c.action_taken ?? "—"}</td>
                    <td className="px-6 py-3 text-gray-400 text-xs whitespace-nowrap">{fmt(c.checked_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
