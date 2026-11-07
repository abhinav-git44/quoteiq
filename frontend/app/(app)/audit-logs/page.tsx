"use client";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { PageHeader } from "@/components/shell";
import { Badge, Card, ErrorBox, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { when } from "@/lib/format";

const ACTIONS = ["", "RFX_CREATED", "RFX_UPDATED", "RFX_PUBLISHED", "DOCUMENT_UPLOADED", "EXTRACTION_QUEUED", "EXTRACTION_COMPLETED", "EXTRACTION_REVIEWED", "EXTRACTION_CORRECTED",
  "NORMALIZATION_RECOMPUTED", "QUESTIONNAIRE_EVALUATED", "ANALYST_QUESTION", "AWARD_SCENARIO_GENERATED", "AWARD_APPROVED", "REPORT_EXPORTED", "USER_LOGIN"];

export default function Audit() {
  const [action, setAction] = React.useState("");
  const q = useQuery({ queryKey: ["audit", action], queryFn: () => api<any[]>(`/api/audit-logs?limit=500${action ? `&action=${action}` : ""}`) });
  const [open, setOpen] = React.useState<string | null>(null);
  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only record of who did what, when, with before/after values." actions={<Select value={action} onChange={(e) => setAction(e.target.value)}>{ACTIONS.map((a) => <option key={a} value={a}>{a || "All actions"}</option>)}</Select>} />
      {q.isLoading ? <Spinner /> : q.error ? <ErrorBox error={q.error} /> : (
        <Card>
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1">When</th><th>User</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
            <tbody>
              {q.data!.map((a) => (
                <React.Fragment key={a.id}>
                  <tr className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(open === a.id ? null : a.id)}>
                    <td className="whitespace-nowrap py-1.5">{when(a.at)}</td><td>{a.user}</td><td><Badge tone={a.action.includes("APPROV") ? "green" : a.action.includes("CORRECT") ? "amber" : "slate"}>{a.action}</Badge></td>
                    <td className="font-mono">{a.entity_type}:{(a.entity_id || "").slice(0, 18)}</td>
                    <td className="max-w-md truncate text-slate-500">{JSON.stringify(a.after || a.meta || {})}</td>
                  </tr>
                  {open === a.id && <tr><td colSpan={5}><pre className="m-1 max-h-64 overflow-auto rounded bg-slate-50 p-2 text-2xs">{JSON.stringify({ before: a.before, after: a.after, meta: a.meta, document_id: a.document_id }, null, 2)}</pre></td></tr>}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
