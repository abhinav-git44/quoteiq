"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { use } from "react";
import { QuoteDrawer } from "@/components/evidence";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Select, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { title, when } from "@/lib/format";

export default function Submissions({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const subs = useQuery({ queryKey: ["subs", id], queryFn: () => api<any[]>(`/api/rfx/${id}/submissions`),
    refetchInterval: (q) => (q.state.data?.some((s: any) => s.documents.some((d: any) => ["QUEUED", "RUNNING"].includes(d.job?.status))) ? 2000 : false) });
  const exc = useQuery({ queryKey: ["exceptions", id], queryFn: () => api(`/api/rfx/${id}/exceptions`) });
  const [err, setErr] = React.useState<any>(null);
  const [sel, setSel] = React.useState<{ v: string | null; l: string | null }>({ v: null, l: null });

  async function upload(vendorId: string, file: File, kind: string) {
    setErr(null);
    const fd = new FormData();
    fd.append("file", file); fd.append("kind", kind);
    try {
      await api(`/api/rfx/${id}/vendors/${vendorId}/documents`, { method: "POST", body: fd });
      qc.invalidateQueries({ queryKey: ["subs", id] });
    } catch (e) { setErr(e); }
  }
  async function retry(jobId: string) {
    try { await api(`/api/extraction/${jobId}/retry`, { method: "POST" }); qc.invalidateQueries({ queryKey: ["subs", id] }); } catch (e) { setErr(e); }
  }
  if (subs.isLoading) return <Spinner />;
  const items: any[] = exc.data?.items || [];
  return (
    <>
      <PageHeader title="Vendor submissions" subtitle="Vendors reply however they like. Every file goes through the same pipeline: parse → Claude extraction with citations → deterministic source checks." />
      <ErrorBox error={err || subs.error} />
      <div className="grid gap-4 xl:grid-cols-5">
        <div className="space-y-3 xl:col-span-3">
          {subs.data?.map((s) => <SubmissionCard key={s.id} s={s} onUpload={upload} onRetry={retry} />)}
        </div>
        <Card className="xl:col-span-2" title={<span>Review queue <Badge tone={items.length ? "amber" : "green"}>{items.length}</Badge></span>} subtitle="Values QuoteIQ is not sure about — nothing here enters an approved award until a person resolves it">
          {exc.isLoading ? <Spinner /> : (
            <ul className="max-h-[720px] divide-y divide-slate-100 overflow-y-auto text-xs scroll-thin">
              {items.map((it, i) => (
                <li key={i} className="py-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{it.vendor_id}</span>
                    {it.line_id ? <span className="font-mono">{it.line_id}</span> : <Badge>document</Badge>}
                    <StatusBadge status={it.status || it.severity} />
                    {it.confidence != null && <Badge tone="amber">conf {it.confidence}</Badge>}
                    {it.line_id && <button className="ml-auto text-accent" onClick={() => setSel({ v: it.vendor_id, l: it.line_id })}>Review →</button>}
                  </div>
                  <div className="mt-0.5 text-slate-600">{(it.why || [it.message]).join("; ")}</div>
                  {it.source_text && <div className="mt-0.5 truncate font-mono text-2xs text-slate-400">{it.segment}: {it.source_text}</div>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <QuoteDrawer rfxId={id} vendorId={sel.v} lineId={sel.l} onClose={() => setSel({ v: null, l: null })} />
    </>
  );
}

function SubmissionCard({ s, onUpload, onRetry }: { s: any; onUpload: (v: string, f: File, k: string) => void; onRetry: (j: string) => void }) {
  const input = React.useRef<HTMLInputElement>(null);
  const [kind, setKind] = React.useState("QUOTATION");
  const current = s.documents.filter((d: any) => !d.superseded);
  return (
    <Card title={<span>{s.vendor.name} <span className="font-normal text-slate-400">· {s.vendor.vendor_id}</span></span>} subtitle={s.received_at ? `Received ${when(s.received_at)}` : "Awaiting response"}
      actions={<><StatusBadge status={s.status} />
        <Select className="h-7 text-xs" value={kind} onChange={(e) => setKind(e.target.value)}><option value="QUOTATION">Quotation</option><option value="CERTIFICATE">Certificate</option><option value="OTHER">Other</option></Select>
        <Button size="sm" variant="outline" onClick={() => input.current?.click()}><Upload className="h-3.5 w-3.5" /> Upload</Button>
        <input ref={input} type="file" hidden accept=".xlsx,.xls,.pdf,.docx,.jpg,.jpeg,.png,.txt,.eml" onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(s.vendor.vendor_id, f, kind); e.target.value = ""; }} /></>}>
      {current.length === 0 ? <div className="text-sm text-slate-500">No documents yet.</div> : (
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th className="py-1">File</th><th>Kind</th><th>Format</th><th>Ver.</th><th>Extraction</th><th>Model</th><th></th></tr></thead>
          <tbody>
            {current.map((d: any) => (
              <tr key={d.id} className="border-t border-slate-100">
                <td className="py-1.5 max-w-[220px] truncate" title={`sha256 ${d.sha256}…`}>{d.filename}</td>
                <td>{title(d.kind)}</td><td>{d.format}</td><td>v{d.version}</td>
                <td><StatusBadge status={d.job?.status || "—"} />{d.job?.error && <div className="mt-0.5 max-w-[220px] truncate text-2xs text-red-700" title={d.job.error}>{d.job.error}</div>}</td>
                <td className="text-slate-400">{d.job?.model || ""}</td>
                <td className="whitespace-nowrap text-right">
                  {d.job && ["FAILED", "AI_UNAVAILABLE", "NEEDS_REVIEW", "SUCCEEDED"].includes(d.job.status) && <button title="Re-run extraction" onClick={() => onRetry(d.job.id)} className="mr-2 text-slate-400 hover:text-accent"><RefreshCw className="h-3.5 w-3.5" /></button>}
                  <Link className="inline-flex items-center gap-1 text-accent" href={`/extraction-review/${d.id}`}><FileSearch className="h-3.5 w-3.5" /> Review</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
