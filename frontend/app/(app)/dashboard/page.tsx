"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, FileWarning, Plus } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorBox, Spinner, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { compactInr, title } from "@/lib/format";

export default function Dashboard() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api("/api/dashboard"), refetchInterval: 8000 });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  const live = d.rfx.find((r: any) => r.vendors) || d.rfx[0];
  const best = live?.scenarios?.length ? Math.min(...live.scenarios.map((s: any) => s.net)) : null;
  const worst = live?.scenarios?.length ? Math.max(...live.scenarios.map((s: any) => s.net)) : null;
  return (
    <>
      <PageHeader title="Good to see you" subtitle="Where every open sourcing event stands — and what needs your judgement."
        actions={<Link href="/rfx/create"><Button><Plus className="h-4 w-4" /> New RFx with co-pilot</Button></Link>} />
      {!d.ai_enabled && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          AI is not configured (ANTHROPIC_API_KEY). Documents are parsed and viewable, but nothing is extracted or analysed — QuoteIQ never substitutes invented values.
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Active RFx" value={d.kpis.active_rfx} />
        <Stat label="Vendors" value={d.kpis.vendors} />
        <Stat label="Quotes received" value={live?.quotations_received ?? "—"} hint={live ? `of ${live.vendors?.length ?? 0} invited` : undefined} />
        <Stat label="Extraction success" value={d.kpis.extraction.success_rate != null ? `${d.kpis.extraction.success_rate}%` : "—"} hint={Object.entries(d.kpis.extraction.by_status || {}).map(([k, v]) => `${title(k)} ${v}`).join(" · ")} />
        <Stat label="Values to verify" value={live?.review_queue ?? "—"} tone={live?.review_queue ? "amber" : undefined} hint="Before an award can be approved" />
        <Stat label="Scenario spread" value={best != null && worst != null && worst > best ? compactInr(worst - best) : "—"} hint="Between saved award scenarios" />
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Sourcing events">
          {!d.rfx.length ? <Empty>No RFx yet. Seed the demo or create one with the co-pilot.</Empty> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Reference</th><th>Title</th><th>Status</th><th>Lines</th><th>Avg coverage</th><th></th></tr></thead>
              <tbody>
                {d.rfx.map((r: any) => (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">{r.reference}</td>
                    <td className="max-w-xs truncate">{r.title}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="num">{r.line_count}</td>
                    <td className="num">{r.avg_coverage != null ? `${r.avg_coverage}%` : "—"}</td>
                    <td className="text-right"><Link className="inline-flex items-center gap-1 text-xs text-accent" href={r.status === "DRAFT" ? `/rfx/${r.id}` : `/comparison/${r.id}`}>Open <ArrowRight className="h-3 w-3" /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Vendor submissions" subtitle={live?.reference}>
          {!live?.vendors ? <Empty>No submissions yet.</Empty> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {live.vendors.map((v: any) => (
                <li key={v.vendor_id} className="flex items-center justify-between py-2">
                  <div>
                    <div className="font-medium">{v.name}</div>
                    <div className="text-2xs text-slate-500">coverage {v.coverage_pct}% · {v.review} to verify</div>
                  </div>
                  <div className="flex flex-col items-end gap-1"><StatusBadge status={v.status} /><StatusBadge status={v.quality} /></div>
                </li>
              ))}
            </ul>
          )}
          {live && (
            <div className="mt-3 flex gap-2">
              <Link href={`/submissions/${live.id}`}><Button size="sm" variant="outline"><FileWarning className="h-3.5 w-3.5" /> Review queue</Button></Link>
              <Link href={`/analyst/${live.id}`}><Button size="sm" variant="secondary"><Bot className="h-3.5 w-3.5" /> Ask the analyst</Button></Link>
            </div>
          )}
        </Card>
      </div>
      <p className="mt-6 text-2xs text-slate-400">All companies, people and figures are synthetic demonstration data. <Badge>Demo</Badge></p>
    </>
  );
}
