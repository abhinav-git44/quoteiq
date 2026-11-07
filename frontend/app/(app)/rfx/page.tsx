"use client";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/shell";
import { Button, Card, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";

export default function RfxList() {
  const q = useQuery({ queryKey: ["rfx-list"], queryFn: () => api<any[]>("/api/rfx") });
  return (
    <>
      <PageHeader title="RFx management" actions={<Link href="/rfx/create"><Button><Plus className="h-4 w-4" /> New RFx</Button></Link>} />
      {q.isLoading ? <Spinner /> : q.error ? <ErrorBox error={q.error} /> : (
        <Card>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Reference</th><th>Title</th><th>Category</th><th>Deadline</th><th>Lines</th><th>Status</th></tr></thead>
            <tbody>
              {q.data!.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="py-2 font-mono text-xs"><Link className="text-accent" href={`/rfx/${r.id}`}>{r.reference}</Link></td>
                  <td>{r.title}</td><td className="text-slate-500">{r.category}</td><td>{r.submission_deadline}</td><td className="num">{r.line_count}</td>
                  <td><StatusBadge status={r.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
