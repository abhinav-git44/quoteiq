"use client";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink } from "lucide-react";
import * as React from "react";
import { use } from "react";
import { QuoteDrawer } from "@/components/evidence";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, ConfidencePill, Empty, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { api, fileUrl } from "@/lib/api";
import { cn, num, title } from "@/lib/format";

export default function ExtractionReview({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api(`/api/documents/${id}`) });
  const [seg, setSeg] = React.useState<string | null>(null);
  const [sel, setSel] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<string | null>(null);
  const [showOriginal, setShowOriginal] = React.useState(false);
  const segRef = React.useRef<HTMLDivElement>(null);
  const d = doc.data;
  React.useEffect(() => {
    if (!d) return;
    let u: string | null = null;
    const path = d.format === "image" && !showOriginal && d.has_derived_image ? `/api/documents/${id}/file?derived=true` : `/api/documents/${id}/file`;
    if (["image", "pdf"].includes(d.format)) fileUrl(path).then((x) => { u = x; setPreview(x); }).catch(() => setPreview(null));
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [d, id, showOriginal]);
  React.useEffect(() => { segRef.current?.querySelector(`[data-seg="${seg}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [seg]);
  if (doc.isLoading) return <Spinner />;
  if (doc.error) return <ErrorBox error={doc.error} />;
  const ex = d.extraction;
  const lines: any[] = ex?.lines || [];
  const hit = d.segments.find((s: any) => s.id === seg);
  return (
    <>
      <PageHeader title={<span>{d.filename} <span className="font-normal text-slate-400">· {d.vendor.name}</span></span>}
        subtitle={`${title(d.kind)} · ${d.format} · v${d.version} · sha256 ${d.sha256}…`}
        actions={<><StatusBadge status={ex?.status || d.job?.status} />{ex?.model && <Badge>{ex.model}</Badge>}</>} />
      {ex?.error && <div className="mb-3"><ErrorBox error={ex.error} /></div>}
      {ex?.document_warnings?.length > 0 && <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">{ex.document_warnings.join(" · ")}</div>}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Original document" actions={d.format === "image" && <Button size="sm" variant="ghost" onClick={() => setShowOriginal(!showOriginal)}>{showOriginal ? "Show corrected" : "Show original photo"}</Button>}>
          {d.format === "image" && preview && (
            <div className="relative mb-3 max-h-[520px] overflow-auto rounded border scroll-thin">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={preview} alt="document" className="w-full" />
              {!showOriginal && hit?.locator?.bbox && d.has_derived_image && <BBox bbox={hit.locator.bbox} />}
            </div>
          )}
          {d.format === "pdf" && preview && <iframe title="pdf" src={`${preview}#page=${hit?.locator?.page || 1}`} className="mb-3 h-[420px] w-full rounded border" />}
          <div className="mb-1 text-2xs text-slate-500">Parsed text segments — the unit of provenance. Click a field on the right to jump to its source.</div>
          <div ref={segRef} className="max-h-[420px] overflow-auto rounded border border-slate-200 bg-slate-50 font-mono text-[11px] leading-5 scroll-thin">
            {d.segments.map((s: any) => (
              <div key={s.id} data-seg={s.id} onClick={() => setSeg(s.id)} className={cn("cursor-pointer hover:bg-white", s.id === seg && "bg-amber-100 ring-1 ring-amber-400", s.locator?.fine_print && "text-violet-800", s.locator?.quoted_history && "text-slate-400")}>
                <span className="inline-block w-12 select-none px-1 text-right text-slate-400">{s.id}</span>
                <span className="px-1">{s.text}</span>
                {s.locator?.fine_print && <Badge tone="violet" className="ml-1">fine print</Badge>}
                {s.ocr_confidence != null && <span className={cn("ml-1 text-2xs", s.ocr_confidence < 80 ? "text-amber-700" : "text-slate-400")}>ocr {Math.round(s.ocr_confidence)}</span>}
              </div>
            ))}
          </div>
        </Card>
        <div className="space-y-4">
          {!ex ? <Empty>Extraction not run yet.</Empty> : ex.status === "AI_UNAVAILABLE" ? (
            <Empty>AI extraction unavailable (no API key). The document was parsed; no values were extracted or invented.</Empty>
          ) : d.kind === "CERTIFICATE" ? (
            <Card title="Certificate fields">
              <dl className="grid grid-cols-2 gap-1 text-sm">
                <dt className="text-slate-500">Holder</dt><dd>{ex.holder}</dd>
                <dt className="text-slate-500">Number</dt><dd>{ex.number}</dd>
                <dt className="text-slate-500">Valid until</dt><dd><button className="text-accent" onClick={() => setSeg(ex.segment_id)}>{ex.valid_until}</button> <ConfidencePill value={ex.confidence ?? 0} /></dd>
              </dl>
            </Card>
          ) : (
            <>
              <Card title="Header & terms">
                <table className="w-full text-xs"><tbody>
                  {ex.header_fields?.map((f: any) => (
                    <tr key={f.name} className="border-t border-slate-100 first:border-0">
                      <td className="w-40 py-1 text-slate-500">{title(f.name)}</td>
                      <td className="py-1"><button className="text-left hover:text-accent" onClick={() => setSeg(f.segment_id)}>{typeof f.value === "object" && f.value ? Object.entries(f.value).filter(([, v]) => v != null).map(([k, v]) => `${k}: ${v}`).join(", ") : String(f.value ?? "—")}</button></td>
                      <td className="py-1 text-right">{f.value != null && <ConfidencePill value={f.confidence} review={f.review_required} />}</td>
                    </tr>
                  ))}
                </tbody></table>
                {ex.discounts?.length > 0 && (
                  <div className="mt-3 space-y-1">
                    {ex.discounts.map((x: any, i: number) => (
                      <button key={i} onClick={() => setSeg(x.segment_id)} className="block w-full rounded border border-sky-200 bg-sky-50 px-2 py-1 text-left text-xs text-sky-900">
                        {x.kind === "ALTERNATE_PRICE" ? `Alternate price ${x.value}` : `${x.value}% discount`} · {title(x.condition_type)} {x.condition_text ? `— ${x.condition_text}` : ""}
                      </button>
                    ))}
                  </div>
                )}
                {ex.unresolved_references?.length > 0 && ex.unresolved_references.map((u: any, i: number) => (
                  <button key={i} onClick={() => setSeg(u.segment_id)} className="mt-2 flex w-full gap-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-left text-xs text-amber-900">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> “{u.text}” — {u.reason} ({u.rfx_line_ids.length} lines)
                  </button>
                ))}
              </Card>
              <Card title={`Extracted lines (${lines.length})`} subtitle="Confidence is a heuristic from verifiable checks — not a probability">
                <div className="max-h-[520px] overflow-auto scroll-thin">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-white text-left text-slate-500"><tr><th>RFx</th><th>Vendor wording</th><th className="text-right">Price</th><th>Basis</th><th>Flags</th><th>Conf.</th><th></th></tr></thead>
                    <tbody>
                      {lines.map((v: any, i: number) => (
                        <tr key={i} className={cn("border-t border-slate-100 cursor-pointer hover:bg-slate-50", v.review_required && "bg-amber-50/60")} onClick={() => setSeg(v.llm.segment_id)}>
                          <td className="py-1 font-mono">{v.llm.rfx_line_id || "—"}</td>
                          <td className="max-w-[200px] truncate" title={v.llm.vendor_description}>{v.llm.vendor_description}</td>
                          <td className="text-right num">{v.llm.price != null ? num(v.llm.price, 2) : <span className="text-red-600">illegible</span>}</td>
                          <td className="text-slate-500">{v.llm.price_basis_text || v.llm.price_uom}</td>
                          <td>{v.llm.flags.map((f: string) => <Badge key={f} tone="amber" className="mr-0.5">{title(f)}</Badge>)}</td>
                          <td><ConfidencePill value={v.confidence} review={v.review_required} /></td>
                          <td>{v.llm.rfx_line_id && <button className="text-accent" onClick={(e) => { e.stopPropagation(); setSel(v.llm.rfx_line_id); }}>Review</button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 flex flex-wrap gap-1 text-2xs">
                  {Object.entries(ex.coverage || {}).filter(([, s]) => s !== "QUOTED").map(([l, s]) => <Badge key={l} tone={s === "NOT_QUOTED" ? "slate" : "amber"}>{l}: {title(String(s))}</Badge>)}
                </div>
              </Card>
            </>
          )}
          <a className="inline-flex items-center gap-1 text-xs text-accent" href="#" onClick={async (e) => { e.preventDefault(); window.open(await fileUrl(`/api/documents/${id}/file`), "_blank"); }}>Open original file <ExternalLink className="h-3 w-3" /></a>
        </div>
      </div>
      <QuoteDrawer rfxId={d.rfx_id} vendorId={sel ? d.vendor.vendor_id : null} lineId={sel} onClose={() => setSel(null)} />
    </>
  );
}

function BBox({ bbox }: { bbox: number[] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [s, setS] = React.useState<React.CSSProperties>({});
  React.useEffect(() => {
    const img = ref.current?.parentElement?.querySelector("img") as HTMLImageElement | null;
    if (!img) return;
    const place = () => {
      const k = img.clientWidth / img.naturalWidth;
      setS({ left: bbox[0] * k - 3, top: bbox[1] * k - 3, width: (bbox[2] - bbox[0]) * k + 6, height: (bbox[3] - bbox[1]) * k + 6 });
      ref.current?.scrollIntoView({ block: "center" });
    };
    if (img.complete) place(); else img.onload = place;
  }, [bbox]);
  return <div ref={ref} className="pointer-events-none absolute rounded ring-2 ring-amber-500 bg-amber-300/20" style={s} />;
}
