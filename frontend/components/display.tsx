"use client";
import { Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { download } from "@/lib/api";
import { compactInr, num } from "@/lib/format";

const PALETTE = ["#4F5BD5", "#0EA5A4", "#F59E0B", "#E25C5C", "#7C8BA1", "#8B5CF6"];

export type Display =
  | { type: "table"; title: string; columns: string[]; rows: any[][]; note?: string }
  | { type: "chart"; chart: "bar" | "stacked_bar" | "grouped_bar" | "pie"; title: string; x: string[]; series: { name: string; data: (number | null)[] }[]; y_label?: string; note?: string }
  | { type: "file"; title: string; url: string };

function fmtCell(v: any) {
  if (v === null || v === undefined || v === "") return <span className="text-slate-300">—</span>;
  if (typeof v === "number") return <span className="num">{Math.abs(v) >= 1000 ? num(v, 0) : num(v, 2)}</span>;
  const s = String(v);
  if (s.endsWith(" ⚠")) return <span className="rounded bg-amber-50 px-1 text-amber-800 num">{s}</span>;
  if (/^(Not Quoted|Needs Clarification|Not Comparable|Unreadable|UNALLOCATED)$/i.test(s)) return <span className="text-slate-400 italic">{s}</span>;
  return s;
}

export function DataTable({ d }: { d: Extract<Display, { type: "table" }> }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
        <div className="text-xs font-semibold text-navy-900">{d.title}</div>
        <span className="text-2xs text-slate-400">{d.rows.length} rows</span>
      </div>
      <div className="max-h-[420px] overflow-auto scroll-thin">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-50">
            <tr>{d.columns.map((c) => <th key={c} className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium text-slate-600">{c}</th>)}</tr>
          </thead>
          <tbody>
            {d.rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100 hover:bg-slate-50/60">
                {r.map((c, j) => <td key={j} className="whitespace-nowrap px-2.5 py-1.5">{fmtCell(c)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.note && <div className="border-t border-slate-100 px-3 py-1.5 text-2xs text-slate-500">{d.note}</div>}
    </div>
  );
}

export function Chart({ d }: { d: Extract<Display, { type: "chart" }> }) {
  const data = d.x.map((x, i) => {
    const row: any = { x };
    d.series.forEach((s) => (row[s.name] = s.data[i]));
    return row;
  });
  const money = (d.y_label || "").includes("₹") || d.series.some((s) => s.name.includes("₹"));
  const tick = (v: any) => (money ? compactInr(v) : num(v, 0));
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-2 text-xs font-semibold text-navy-900">{d.title}</div>
      <div className="h-64">
        <ResponsiveContainer>
          {d.chart === "pie" ? (
            <PieChart>
              <Pie data={data} dataKey={d.series[0].name} nameKey="x" outerRadius={90} label={(e: any) => `${e.x}`}>
                {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Pie>
              <Tooltip formatter={(v: any) => tick(v)} />
            </PieChart>
          ) : (
            <BarChart data={data} margin={{ left: 8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="x" tick={{ fontSize: 10 }} interval={0} angle={d.x.length > 8 ? -35 : 0} textAnchor={d.x.length > 8 ? "end" : "middle"} height={d.x.length > 8 ? 50 : 24} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={tick} width={70} />
              <Tooltip formatter={(v: any) => (v === null ? "—" : tick(v))} />
              {d.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {d.series.map((s, i) => (
                <Bar key={s.name} dataKey={s.name} stackId={d.chart === "stacked_bar" ? "a" : undefined} fill={PALETTE[i % PALETTE.length]} radius={d.chart === "stacked_bar" ? 0 : [3, 3, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {d.note && <div className="mt-1 text-2xs text-slate-500">{d.note}</div>}
    </div>
  );
}

export function DisplayView({ d }: { d: Display }) {
  if (d.type === "table") return <DataTable d={d} />;
  if (d.type === "chart") return <Chart d={d} />;
  if (d.type === "file")
    return (
      <button onClick={() => download(d.url, d.title)} className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium hover:bg-slate-50">
        <Download className="h-3.5 w-3.5" /> {d.title}
      </button>
    );
  return null;
}
