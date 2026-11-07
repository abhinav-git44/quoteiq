"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import * as React from "react";
import { PageHeader, useRfx } from "@/components/shell";
import { Button, Card, Empty, ErrorBox, Spinner } from "@/components/ui";
import { api, download } from "@/lib/api";
import { title, when } from "@/lib/format";

const KINDS = [
  { kind: "comparison_xlsx", label: "Vendor comparison (XLSX)", icon: FileSpreadsheet, hint: "Normalized matrix with trace comments, original quotes, coverage, assumptions" },
  { kind: "exceptions_xlsx", label: "Extraction exceptions (XLSX)", icon: FileSpreadsheet, hint: "Every value awaiting verification, with source locations" },
  { kind: "quality_pdf", label: "Quality evaluation (PDF)", icon: FileText, hint: "Questionnaire results and eligibility reasons" },
  { kind: "audit_csv", label: "Audit log (CSV)", icon: FileText, hint: "Every upload, extraction, correction, scenario and approval" },
];

export default function Reports() {
  const { rfxId } = useRfx();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["reports", rfxId], queryFn: () => api<any[]>(`/api/reports${rfxId ? `?rfx_id=${rfxId}` : ""}`) });
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<any>(null);
  async function make(kind: string) {
    if (!rfxId) return;
    setBusy(kind); setErr(null);
    try {
      const r = await api(`/api/rfx/${rfxId}/reports`, { method: "POST", json: { kind } });
      await download(r.download_url, r.filename);
      qc.invalidateQueries({ queryKey: ["reports", rfxId] });
    } catch (e) { setErr(e); } finally { setBusy(null); }
  }
  return (
    <>
      <PageHeader title="Reports" subtitle="Generated from persisted, normalized data — never from model prose. Award PDFs are created from the Award page." />
      <ErrorBox error={err} />
      <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {KINDS.map((k) => (
          <Card key={k.kind}>
            <div className="flex items-start gap-2"><k.icon className="h-5 w-5 text-accent" /><div><div className="text-sm font-medium">{k.label}</div><div className="text-xs text-slate-500">{k.hint}</div></div></div>
            <Button size="sm" className="mt-3" loading={busy === k.kind} disabled={!rfxId} onClick={() => make(k.kind)}><Download className="h-3.5 w-3.5" /> Generate</Button>
          </Card>
        ))}
      </div>
      <Card title="Generated reports">
        {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty>No reports yet.</Empty> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">File</th><th>Kind</th><th>Scenario</th><th>Created</th><th></th></tr></thead>
            <tbody>{list.data.map((r) => (
              <tr key={r.id} className="border-t border-slate-100"><td className="py-1.5">{r.filename}</td><td>{title(r.kind)}</td><td className="font-mono text-xs">{r.scenario_id || "—"}</td><td>{when(r.created_at)}</td>
                <td className="text-right"><button className="text-accent" onClick={() => download(r.download_url, r.filename)}>Download</button></td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </>
  );
}
