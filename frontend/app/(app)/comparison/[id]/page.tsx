"use client";
import { useQuery } from "@tanstack/react-query";
import { ColumnDef, flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, SortingState, useReactTable } from "@tanstack/react-table";
import { AlertTriangle, ArrowUpDown, Download, Info } from "lucide-react";
import * as React from "react";
import { use } from "react";
import { QuoteDrawer } from "@/components/evidence";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Input, Spinner, StatusBadge, Toggle } from "@/components/ui";
import { api, download } from "@/lib/api";
import { cn, compactInr, num, title } from "@/lib/format";

export default function Comparison({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const q = useQuery({ queryKey: ["comparison", id], queryFn: () => api(`/api/rfx/${id}/comparison`) });
  const quality = useQuery({ queryKey: ["quality", id], queryFn: () => api(`/api/rfx/${id}/quality`) });
  const [view, setView] = React.useState("commercial");
  const [basis, setBasis] = React.useState("unit");
  const [display, setDisplay] = React.useState("normalized");
  const [filter, setFilter] = React.useState("all");
  const [eligibleOnly, setEligibleOnly] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [sel, setSel] = React.useState<{ v: string | null; l: string | null }>({ v: null, l: null });
  const [exporting, setExporting] = React.useState(false);
  const data = q.data;
  const vendors: any[] = data?.vendors || [];
  const elig = Object.fromEntries(vendors.map((v) => [v.vendor_id, v.quality_status]));

  const rows = React.useMemo(() => {
    if (!data) return [];
    return data.lines
      .map((l: any) => {
        const vals = Object.entries(l.quotes).map(([vid, qq]: any) => ({ vid, p: qq.status === "QUOTED" ? (basis === "landed" ? qq.landed : qq.unit) : null, review: qq.review }));
        const valid = vals.filter((x) => x.p != null && (!eligibleOnly || elig[x.vid] === "ELIGIBLE"));
        const low = valid.length ? valid.reduce((a, b) => (b.p! < a.p! ? b : a)) : null;
        const hasIssue = Object.values(l.quotes).some((qq: any) => qq.review || ["NEEDS_CLARIFICATION", "NOT_COMPARABLE", "UNREADABLE"].includes(qq.status));
        const missing = Object.values(l.quotes).some((qq: any) => qq.status === "NOT_QUOTED");
        const all = vals.filter((x) => x.p != null).map((x) => x.p!);
        const spread = all.length > 1 ? (Math.max(...all) - Math.min(...all)) / Math.min(...all) : null;
        return { ...l, low, hasIssue, missing, spread };
      })
      .filter((r: any) => (filter === "issues" ? r.hasIssue : filter === "missing" ? r.missing : true));
  }, [data, basis, eligibleOnly, filter, elig]);

  const columns = React.useMemo<ColumnDef<any>[]>(() => {
    const cols: ColumnDef<any>[] = [
      { id: "line", header: "Line", accessorKey: "line_id", cell: (c) => <span className="font-mono">{c.getValue() as string}</span> },
      { id: "name", header: "Item", accessorFn: (r) => `${r.name} ${r.item_code}`, cell: (c) => <span title={c.row.original.description} className="block max-w-[220px] truncate">{c.row.original.name}</span> },
      { id: "qty", header: "Qty", accessorKey: "quantity", cell: (c) => <span className="num">{num(c.getValue() as number, 0)} <span className="text-slate-400">{c.row.original.uom}</span></span> },
    ];
    for (const v of vendors) {
      cols.push({
        id: v.vendor_id,
        header: () => (
          <div className="min-w-[110px]">
            <div className="truncate">{v.vendor_name}</div>
            <div className="mt-0.5 flex gap-1"><StatusBadge status={v.quality_status} />{v.currency !== "INR" && <Badge tone="violet">{v.currency}</Badge>}</div>
          </div>
        ),
        accessorFn: (r) => { const qq = r.quotes[v.vendor_id]; return qq?.status === "QUOTED" ? (basis === "landed" ? qq.landed : qq.unit) : Number.POSITIVE_INFINITY; },
        sortingFn: "basic",
        cell: (c) => {
          const r = c.row.original;
          const qq = r.quotes[v.vendor_id];
          if (!qq) return <span className="text-slate-300">—</span>;
          const isLow = r.low?.vid === v.vendor_id;
          const inel = elig[v.vendor_id] !== "ELIGIBLE";
          if (qq.status !== "QUOTED") {
            return (
              <button onClick={() => setSel({ v: v.vendor_id, l: r.line_id })} title={qq.reason || ""}
                className={cn("w-full rounded px-1.5 py-1 text-left text-2xs italic", qq.status === "NOT_QUOTED" ? "text-slate-400" : "bg-violet-50 text-violet-700")}>
                {title(qq.status)}
              </button>
            );
          }
          const shown = display === "original" ? `${num(qq.orig, qq.orig < 10 ? 2 : 2)} ${qq.ccy} ${qq.basis || ""}`.trim() : num(basis === "landed" ? qq.landed : qq.unit, 2);
          return (
            <button onClick={() => setSel({ v: v.vendor_id, l: r.line_id })}
              className={cn("flex w-full items-center justify-end gap-1 rounded px-1.5 py-1 text-right num hover:ring-1 hover:ring-accent",
                isLow && "bg-emerald-50 font-semibold text-emerald-800", qq.review && "bg-amber-50 text-amber-900", inel && "opacity-60")}
              title={`${qq.conv ? title(qq.conv) + " · " : ""}confidence ${qq.conf}${qq.review ? " · needs verification" : ""}${inel ? " · vendor not quality-eligible" : ""}`}>
              {qq.review && <AlertTriangle className="h-3 w-3 shrink-0 text-amber-600" />}
              {qq.conv === "DERIVED_WEIGHT" && <span className="text-2xs text-violet-600">kg→</span>}
              {qq.offers?.length > 0 && <span className="text-2xs text-sky-600" title={`Conditional offer: ${qq.offers[0].value} if ${qq.offers[0].condition}`}>◆</span>}
              <span className={display === "original" ? "text-2xs" : ""}>{shown}</span>
            </button>
          );
        },
      });
    }
    cols.push({ id: "low", header: eligibleOnly ? "Lowest eligible" : "Lowest", accessorFn: (r) => r.low?.vid || "", cell: (c) => { const r = c.row.original; return r.low ? <span className="text-xs">{vendors.find((v) => v.vendor_id === r.low.vid)?.vendor_name}</span> : <Badge tone="red">none valid</Badge>; } });
    cols.push({ id: "spread", header: "Spread", accessorFn: (r) => r.spread ?? -1, cell: (c) => { const s = c.row.original.spread; return s == null ? "—" : <span className={cn("num", s > 0.15 && "text-amber-700")}>{(s * 100).toFixed(0)}%</span>; } });
    return cols;
  }, [vendors, basis, display, eligibleOnly, elig]);

  const table = useReactTable({ data: rows, columns, state: { sorting, globalFilter: search }, onSortingChange: setSorting, onGlobalFilterChange: setSearch,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(), globalFilterFn: "includesString" });

  if (q.isLoading) return <Spinner label="Normalizing quotes…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const coverages = new Set(vendors.map((v) => v.coverage_pct));
  return (
    <>
      <PageHeader title="Bid comparison" subtitle={`${data.rfx.reference} · ${data.lines.length} lines × ${vendors.length} vendors · ${data.policy.base_currency} per RFx unit, ex-GST, after unconditional discounts`}
        actions={<>
          <Toggle value={view} onChange={setView} options={[{ value: "commercial", label: "Commercial" }, { value: "quality", label: "Quality & compliance" }]} />
          <Button variant="outline" loading={exporting} onClick={async () => { setExporting(true); try { const r = await api(`/api/rfx/${id}/reports`, { method: "POST", json: { kind: "comparison_xlsx" } }); await download(r.download_url, r.filename); } finally { setExporting(false); } }}><Download className="h-4 w-4" /> Excel</Button>
        </>} />
      <div className="mb-4 grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        {vendors.map((v) => (
          <div key={v.vendor_id} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="truncate text-sm font-semibold">{v.vendor_name}</div>
              <StatusBadge status={v.quality_status} />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-y-0.5 text-2xs text-slate-600">
              <span>Coverage</span><span className={cn("text-right num", v.coverage_pct < 100 && "text-amber-700 font-medium")}>{v.quoted_lines}/{data.lines.length} · {v.comparable_lines} comparable</span>
              <span>Own-lines total</span><span className="text-right num">{compactInr(v.total_own_comparable)}</span>
              <span>Lowest on</span><span className="text-right num">{v.lowest_lines} lines</span>
              <span>To verify</span><span className={cn("text-right num", v.review_required_lines > 0 && "text-amber-700 font-medium")}>{v.review_required_lines}</span>
              <span>Freight</span><span className="truncate text-right" title={v.freight_note}>{title(v.freight_basis)}</span>
              <span>Payment</span><span className="text-right">{v.payment_days ?? "—"} days</span>
            </div>
            {v.conditional_discounts?.length > 0 && <div className="mt-1.5 text-2xs text-sky-700">◆ {v.conditional_discounts.map((d: any) => `${d.value}${d.kind === "PERCENT" ? "%" : ""} ${title(d.condition_type)}`).join(" · ")}</div>}
            {v.quality_status !== "ELIGIBLE" && <div className="mt-1.5 line-clamp-2 text-2xs text-red-700" title={v.quality_reasons.join("; ")}>{v.quality_reasons[0]}</div>}
          </div>
        ))}
      </div>
      {coverages.size > 1 && (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0" /> Vendors quoted different sets of lines, so their totals are not like-for-like. No grand total is shown here; use Award scenarios or ask the analyst for a common-lines comparison.
        </div>
      )}
      {view === "quality" ? <QualityView data={quality.data} /> : (
        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Input className="h-8 w-56" placeholder="Search item / code…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Toggle value={basis} onChange={setBasis} options={[{ value: "unit", label: "Base price" }, { value: "landed", label: "Landed (+freight)" }]} />
            <Toggle value={display} onChange={setDisplay} options={[{ value: "normalized", label: "Normalized ₹" }, { value: "original", label: "As quoted" }]} />
            <Toggle value={filter} onChange={setFilter} options={[{ value: "all", label: "All lines" }, { value: "issues", label: "Needs attention" }, { value: "missing", label: "Missing quotes" }]} />
            <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={eligibleOnly} onChange={(e) => setEligibleOnly(e.target.checked)} /> Lowest among quality-eligible only</label>
            <div className="ml-auto flex flex-wrap gap-2 text-2xs text-slate-500">
              <span className="rounded bg-emerald-50 px-1.5 text-emerald-800">lowest</span>
              <span className="rounded bg-amber-50 px-1.5 text-amber-900">⚠ needs verification</span>
              <span className="text-violet-600">kg→ derived from weight</span><span className="text-sky-600">◆ conditional offer</span>
              <span className="opacity-60">faded = not quality-eligible</span>
            </div>
          </div>
          <div className="max-h-[70vh] overflow-auto rounded border border-slate-200 scroll-thin">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-20 bg-slate-50">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h, i) => (
                      <th key={h.id} onClick={h.column.getToggleSortingHandler()} className={cn("cursor-pointer select-none border-b border-slate-200 px-2 py-2 text-left align-bottom font-medium text-slate-600", i < 2 && "sticky z-10 bg-slate-50", i === 0 && "left-0", i === 1 && "left-[52px]")}>
                        <div className="flex items-end gap-1">{flexRender(h.column.columnDef.header, h.getContext())}<ArrowUpDown className="h-3 w-3 shrink-0 text-slate-300" /></div>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50/50">
                    {r.getVisibleCells().map((c, i) => (
                      <td key={c.id} className={cn("px-2 py-1", i < 2 && "sticky z-10 bg-white", i === 0 && "left-0 w-[52px]", i === 1 && "left-[52px]")}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-2xs text-slate-500">FX: {data.fx.map((f: any) => `${f.from_currency}→${f.to_currency} ${f.rate} (${f.source})`).join(" · ")} · Freight-at-actuals assumption {data.policy.freight_at_actuals_assumed_pct}% · Early-payment discounts {data.policy.apply_early_payment_discounts ? "applied" : "excluded"}</div>
        </Card>
      )}
      <QuoteDrawer rfxId={id} vendorId={sel.v} lineId={sel.l} onClose={() => setSel({ v: null, l: null })} />
    </>
  );
}

function QualityView({ data }: { data: any }) {
  if (!data) return <Spinner />;
  return (
    <Card title="Quality questionnaire" subtitle={data.policy}>
      <div className="overflow-auto scroll-thin">
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Question</th>{data.vendors.map((v: any) => <th key={v.vendor_id} className="px-2">{v.name}<div><StatusBadge status={v.status} /></div></th>)}</tr></thead>
          <tbody>
            {data.questionnaire.map((q: any) => (
              <tr key={q.qid} className="border-t border-slate-100 align-top">
                <td className="max-w-xs py-1.5"><span className="font-mono text-slate-400">{q.qid}</span> {q.text} {q.mandatory && <Badge tone="red">mandatory</Badge>}</td>
                {data.vendors.map((v: any) => {
                  const a = v.answers.find((x: any) => x.qid === q.qid);
                  return (
                    <td key={v.vendor_id} className="px-2 py-1.5" title={a?.reason}>
                      <StatusBadge status={a?.status} /> <span className="text-slate-500">{a?.answer === true ? "Yes" : a?.answer === false ? "No" : a?.answer ?? "—"}</span>
                      {a && a.status !== "PASS" && <div className="mt-0.5 text-2xs text-slate-500">{a.reason}</div>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
