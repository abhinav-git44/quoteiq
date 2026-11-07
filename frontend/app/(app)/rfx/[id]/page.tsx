"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { inr, num } from "@/lib/format";

export default function RfxDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const q = useQuery({ queryKey: ["rfx", id], queryFn: () => api(`/api/rfx/${id}`) });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data;
  return (
    <>
      <PageHeader title={<span>{r.reference} <span className="font-normal text-slate-500">· {r.title}</span></span>} subtitle={`${r.category} · issued ${r.issue_date} · due ${r.submission_deadline} · ${r.delivery_location || ""}`}
        actions={<><StatusBadge status={r.status} />
          {r.status === "DRAFT" ? <Link href={`/rfx/create?id=${r.id}`}><Button variant="outline">Edit in co-pilot</Button></Link> :
            <><Link href={`/submissions/${r.id}`}><Button variant="outline">Submissions</Button></Link><Link href={`/comparison/${r.id}`}><Button>Comparison</Button></Link></>}</>} />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={`Line items (${r.lines.length})`} subtitle="Pricing basis per line is what makes vendor responses comparable">
          <div className="max-h-[560px] overflow-auto scroll-thin">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white text-left text-slate-500"><tr><th className="py-1">Line</th><th>Item</th><th>Spec</th><th className="text-right">Qty</th><th>UOM</th><th className="text-right">Target ₹</th></tr></thead>
              <tbody>
                {r.lines.map((l: any) => (
                  <tr key={l.line_id} className="border-t border-slate-100">
                    <td className="py-1.5 font-mono">{l.line_id}</td><td>{l.name}</td>
                    <td className="text-slate-500">{[l.spec.length_mm && `${l.spec.length_mm}×${l.spec.width_mm}${l.spec.height_mm ? "×" + l.spec.height_mm : ""}`, l.spec.ply && `${l.spec.ply}-ply`, l.spec.board_gsm && `${l.spec.board_gsm} gsm`, l.spec.bursting_strength_kg_cm2 && `BS≥${l.spec.bursting_strength_kg_cm2}`].filter(Boolean).join(" · ")}</td>
                    <td className="text-right num">{num(l.quantity, 0)}</td><td>{l.uom}</td><td className="text-right num">{inr(l.target_price_inr, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Terms">
            <ul className="space-y-1.5 text-sm">{r.terms.map((t: any, i: number) => <li key={i}><Badge>{t.kind}</Badge> <span className="text-slate-700">{t.text}</span></li>)}</ul>
          </Card>
          <Card title={`Quality questionnaire (${r.questionnaire.length})`}>
            <ol className="space-y-1.5 text-xs">{r.questionnaire.map((q: any) => <li key={q.qid}><span className="font-mono text-slate-400">{q.qid}</span> {q.text} {q.mandatory ? <Badge tone="red">mandatory</Badge> : <Badge>optional</Badge>} <span className="text-slate-400">{JSON.stringify(q.pass_rule)}</span></li>)}</ol>
          </Card>
          <Card title="Invited vendors">
            <ul className="text-sm">{r.vendors.map((v: any) => <li key={v.vendor_id} className="flex justify-between border-t border-slate-100 py-1.5 first:border-0"><span>{v.name}</span><span className="text-xs text-slate-500">{v.email}</span></li>)}</ul>
          </Card>
        </div>
      </div>
    </>
  );
}
