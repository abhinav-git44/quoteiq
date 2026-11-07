"use client";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell";
import { Badge, Card, ErrorBox, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function Vendors() {
  const q = useQuery({ queryKey: ["vendors"], queryFn: () => api<any[]>("/api/vendors") });
  return (
    <>
      <PageHeader title="Vendors" subtitle="Vendor master (synthetic). Certifications listed here are claims — QuoteIQ verifies them from the attached certificate per RFx." />
      {q.isLoading ? <Spinner /> : q.error ? <ErrorBox error={q.error} /> : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {q.data!.map((v) => (
            <Card key={v.vendor_id} title={v.name} subtitle={`${v.vendor_id} · ${v.city}`}>
              <dl className="grid grid-cols-2 gap-y-1 text-xs">
                <dt className="text-slate-500">Contact</dt><dd>{v.contact} · {v.email}</dd>
                <dt className="text-slate-500">Capacity</dt><dd>{v.capacity_tpm} t/month</dd>
                <dt className="text-slate-500">Historical score</dt><dd>{v.historical_score}/100</dd>
                <dt className="text-slate-500">Quote format</dt><dd>{v.submission_format}</dd>
              </dl>
              <div className="mt-2 flex flex-wrap gap-1">{v.categories.map((c: string) => <Badge key={c}>{c}</Badge>)}{v.certifications.map((c: string) => <Badge key={c} tone="blue">{c}</Badge>)}</div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
