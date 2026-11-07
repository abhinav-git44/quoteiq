"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Play } from "lucide-react";
import * as React from "react";
import { use } from "react";
import { Chart, DataTable } from "@/components/display";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorBox, Input, Select, Spinner, StatusBadge, Textarea } from "@/components/ui";
import { api, download } from "@/lib/api";
import { cn, compactInr, inr, num } from "@/lib/format";

const PRESETS = [
  { name: "Best single vendor", p: { strategy: "SINGLE_VENDOR" } },
  { name: "Lowest per line (plain)", p: { strategy: "LOWEST_PRICE_SPLIT", discount_aware: false } },
  { name: "Lowest price, discount-aware", p: { strategy: "LOWEST_PRICE_SPLIT" } },
  { name: "Max 2 vendors", p: { strategy: "LOWEST_PRICE_SPLIT", max_vendors: 2 } },
  { name: "Balanced (≤60% share)", p: { strategy: "BALANCED" } },
];

export default function Award({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["scenarios", id], queryFn: () => api<any[]>(`/api/rfx/${id}/award/scenarios`) });
  const comp = useQuery({ queryKey: ["comparison", id], queryFn: () => api(`/api/rfx/${id}/comparison`) });
  const [form, setForm] = React.useState<any>({ strategy: "LOWEST_PRICE_SPLIT", cost_basis: "base", eligible_only: true, include_pending: false, exclude_unverified: false, discount_aware: true, max_vendors: "", max_share_pct: "", exclude_vendor_ids: [] });
  const [sid, setSid] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<any>(null);
  const sc = useQuery({ queryKey: ["scenario", id, sid], queryFn: () => api(`/api/rfx/${id}/award/scenarios/${sid}`), enabled: !!sid });
  const sav = useQuery({ queryKey: ["savings", id, sid], queryFn: () => api(`/api/rfx/${id}/award/scenarios/${sid}/savings`), enabled: !!sid && sc.data?.strategy !== "SINGLE_VENDOR" });

  async function run(p: any) {
    setBusy(true); setErr(null);
    const body = Object.fromEntries(Object.entries({ ...p }).filter(([, v]) => v !== "" && v !== null));
    if (body.max_vendors) body.max_vendors = Number(body.max_vendors);
    if (body.max_share_pct) body.max_share_pct = Number(body.max_share_pct);
    try {
      const s = await api(`/api/rfx/${id}/award/optimize`, { method: "POST", json: body });
      setSid(s.scenario_id);
      qc.invalidateQueries({ queryKey: ["scenarios", id] });
      qc.invalidateQueries({ queryKey: ["scenario", id, s.scenario_id] });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  const s = sc.data;
  const vendors: any[] = comp.data?.vendors || [];
  return (
    <>
      <PageHeader title="Award scenarios" subtitle="Deterministic optimisation over normalized, eligible quotes. The system recommends; a person approves." />
      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          <Card title="Quick scenarios">
            <div className="grid gap-1.5">{PRESETS.map((p) => <Button key={p.name} size="sm" variant="outline" className="justify-start" loading={busy} onClick={() => run(p.p)}><Play className="h-3 w-3" /> {p.name}</Button>)}</div>
          </Card>
          <Card title="Custom scenario">
            <div className="grid gap-2 text-xs">
              <label>Strategy<Select className="w-full" value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}><option value="SINGLE_VENDOR">Single vendor</option><option value="LOWEST_PRICE_SPLIT">Lowest-price split</option><option value="BALANCED">Balanced</option></Select></label>
              <label>Cost basis<Select className="w-full" value={form.cost_basis} onChange={(e) => setForm({ ...form, cost_basis: e.target.value })}><option value="base">Base price (ex-GST)</option><option value="landed">Landed (+ freight)</option></Select></label>
              <div className="grid grid-cols-2 gap-2">
                <label>Max vendors<Input type="number" min={1} max={5} value={form.max_vendors} onChange={(e) => setForm({ ...form, max_vendors: e.target.value })} /></label>
                <label>Max share %<Input type="number" min={1} max={100} value={form.max_share_pct} onChange={(e) => setForm({ ...form, max_share_pct: e.target.value })} /></label>
              </div>
              {[["eligible_only", "Only quality-eligible vendors"], ["include_pending", "Also allow PENDING vendors"], ["exclude_unverified", "Ignore values awaiting verification"], ["discount_aware", "Search patterns that earn conditional discounts"]].map(([k, l]) => (
                <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.checked })} />{l}</label>
              ))}
              <div>Exclude vendors
                <div className="mt-1 flex flex-wrap gap-2">{vendors.map((v) => <label key={v.vendor_id} className="flex items-center gap-1"><input type="checkbox" checked={form.exclude_vendor_ids.includes(v.vendor_id)} onChange={(e) => setForm({ ...form, exclude_vendor_ids: e.target.checked ? [...form.exclude_vendor_ids, v.vendor_id] : form.exclude_vendor_ids.filter((x: string) => x !== v.vendor_id) })} />{v.vendor_name.split(" ")[0]}</label>)}</div>
              </div>
              <Button loading={busy} onClick={() => run(form)}>Run scenario</Button>
            </div>
          </Card>
          <ErrorBox error={err} />
        </div>
        <div className="space-y-4">
          <Card title="Scenarios side by side" subtitle="Compare nets only between scenarios that allocate the same lines">
            {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty>Run a scenario to start.</Empty> : (
              <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
                {list.data.map((x) => (
                  <button key={x.scenario_id} onClick={() => setSid(x.scenario_id)} className={cn("rounded-md border p-3 text-left hover:border-accent", sid === x.scenario_id ? "border-accent ring-1 ring-accent" : "border-slate-200")}>
                    <div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium">{x.name}</span><StatusBadge status={x.status} /></div>
                    <div className="mt-1 text-lg font-semibold num">{compactInr(x.net_total)}</div>
                    <div className="text-2xs text-slate-500">{x.lines_allocated} allocated · {x.lines_unallocated} unallocated · {x.vendors_used} vendor(s){x.review_lines ? ` · ${x.review_lines} to verify` : ""}</div>
                  </button>
                ))}
              </div>
            )}
          </Card>
          {sid && (sc.isLoading ? <Spinner /> : s && <ScenarioDetail rfxId={id} s={s} savings={sav.data} onChanged={() => { qc.invalidateQueries({ queryKey: ["scenario", id, sid] }); qc.invalidateQueries({ queryKey: ["scenarios", id] }); }} />)}
        </div>
      </div>
    </>
  );
}

function ScenarioDetail({ rfxId, s, savings, onChanged }: { rfxId: string; s: any; savings: any; onChanged: () => void }) {
  const [comment, setComment] = React.useState("");
  const [ack, setAck] = React.useState(false);
  const [err, setErr] = React.useState<any>(null);
  const [busy, setBusy] = React.useState(false);
  async function approve() {
    setBusy(true); setErr(null);
    try { await api(`/api/rfx/${rfxId}/award/scenarios/${s.scenario_id}/approve`, { method: "POST", json: { comment, acknowledge_unallocated: ack } }); onChanged(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function pdf() {
    const r = await api(`/api/rfx/${rfxId}/reports`, { method: "POST", json: { kind: "award_pdf", scenario_id: s.scenario_id } });
    await download(r.download_url, r.filename);
  }
  const unverified = s.allocations.filter((a: any) => a.review_required).length;
  const rows = [
    ...s.allocations.map((a: any) => [a.line_id, a.line_name, a.vendor_name, num(a.quantity, 0), a.unit_price, a.value, a.runner_up_unit_price, a.review_required ? "⚠ verify" : ""]),
    ...s.unallocated.map((u: any) => [u.line_id, u.line_name, "UNALLOCATED", num(u.quantity, 0), null, null, null, u.reason]),
  ];
  return (
    <Card title={<span>{s.name} <span className="font-mono text-xs font-normal text-slate-400">{s.scenario_id}</span></span>} subtitle={`${s.cost_basis_label} · solver: ${s.solver}`}
      actions={<><StatusBadge status={s.status} /><Button size="sm" variant="outline" onClick={pdf}><Download className="h-3.5 w-3.5" /> Award PDF</Button></>}>
      <div className="grid gap-3 md:grid-cols-4">
        <div><div className="text-2xs uppercase text-slate-500">Net total</div><div className="text-xl font-semibold num">{inr(s.net_total)}</div><div className="text-2xs text-slate-500">gross {inr(s.gross_total)}</div></div>
        <div><div className="text-2xs uppercase text-slate-500">Lines</div><div className="text-xl font-semibold">{s.lines_allocated}<span className="text-sm text-slate-400"> / {s.lines_allocated + s.lines_unallocated}</span></div>{s.lines_unallocated > 0 && <div className="text-2xs text-red-700">{s.lines_unallocated} unallocated</div>}</div>
        <div><div className="text-2xs uppercase text-slate-500">vs best single vendor</div>{savings ? <><div className={cn("text-xl font-semibold num", savings.savings >= 0 ? "text-emerald-700" : "text-red-700")}>{compactInr(savings.savings)}</div><div className="text-2xs text-slate-500">{savings.savings_pct}% on {savings.common_lines} common lines vs {savings.baseline_vendor}</div></> : <div className="text-sm text-slate-400">—</div>}</div>
        <div><div className="text-2xs uppercase text-slate-500">vs last-contract target</div><div className="text-xl font-semibold num">{compactInr(s.target_total_allocated - s.net_total)}</div><div className="text-2xs text-slate-500">target {compactInr(s.target_total_allocated)}</div></div>
      </div>
      {s.discounts_applied?.length > 0 && (
        <div className="mt-3 space-y-1">{s.discounts_applied.map((d: any, i: number) => (
          <div key={i} className={cn("rounded px-2 py-1 text-xs", d.applied ? "bg-emerald-50 text-emerald-900" : "bg-slate-50 text-slate-600")}>{d.applied ? <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> : "◇ "}{d.vendor_name}: {d.pct}% if {d.condition} — {d.applied ? `earned ${inr(d.amount)}` : "not earned"} ({d.why})</div>
        ))}</div>
      )}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Chart d={{ type: "chart", chart: "pie", title: "Share of awarded value", x: s.vendor_shares.map((v: any) => `${v.vendor_name} (${v.pct}%)`), series: [{ name: "₹", data: s.vendor_shares.map((v: any) => v.value) }] }} />
        <div className="space-y-3 text-xs">
          {s.risks?.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><div className="mb-1 font-semibold text-amber-900">Risks</div><ul className="list-disc space-y-0.5 pl-4 text-amber-900">{s.risks.map((r: string) => <li key={r}>{r}</li>)}</ul></div>}
          <div className="rounded-md border border-slate-200 p-3"><div className="mb-1 font-semibold">Assumptions</div><ul className="list-disc space-y-0.5 pl-4 text-slate-700">{s.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul></div>
          {s.excluded_vendors?.length > 0 && <div className="rounded-md border border-slate-200 p-3"><div className="mb-1 font-semibold">Excluded vendors</div><ul className="space-y-0.5 text-slate-700">{s.excluded_vendors.map((e: any) => <li key={e.vendor_id}><b>{e.vendor_id}</b>: {e.reason}</li>)}</ul></div>}
        </div>
      </div>
      <div className="mt-4"><DataTable d={{ type: "table", title: "Line allocation", columns: ["Line", "Item", "Awarded to", "Qty", "Unit ₹", "Value ₹", "Runner-up ₹", "Flag"], rows }} /></div>
      <div className="mt-4 rounded-md border border-slate-200 p-3">
        <div className="mb-2 text-sm font-semibold">Human approval</div>
        {s.status === "APPROVED" ? <div className="text-sm text-emerald-800"><CheckCircle2 className="mr-1 inline h-4 w-4" />Approved {new Date(s.approved_at).toLocaleString()} — “{s.approval_comment}”</div> : (
          <>
            {unverified > 0 && <div className="mb-2 flex items-start gap-1.5 text-xs text-amber-900"><AlertTriangle className="h-4 w-4 shrink-0" /> {unverified} awarded value(s) still need verification. Approval is blocked until they are confirmed or corrected — or re-run with “Ignore values awaiting verification”.</div>}
            <Textarea rows={2} placeholder="Approval note (required) — rationale for the award" value={comment} onChange={(e) => setComment(e.target.value)} />
            {s.lines_unallocated > 0 && <label className="mt-2 flex items-center gap-1.5 text-xs"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I acknowledge {s.lines_unallocated} line(s) remain unallocated (partial award)</label>}
            <div className="mt-2 flex items-center gap-2"><Button onClick={approve} loading={busy} disabled={!comment.trim()}>Approve award</Button><Badge>Recorded in audit log</Badge></div>
            <div className="mt-2"><ErrorBox error={err} /></div>
          </>
        )}
      </div>
    </Card>
  );
}
