"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, FileSearch } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge, Button, ConfidencePill, Drawer, ErrorBox, Input, Select, Spinner, StatusBadge, Textarea } from "@/components/ui";
import { api, fileUrl } from "@/lib/api";
import { inr, num, title } from "@/lib/format";

/** Shows the source of a value: the exact segment, highlighted in context; for photos the OCR box on the corrected image. */
export function SourcePreview({ documentId, segmentId, locator }: { documentId?: string | null; segmentId?: string | null; locator?: any }) {
  const doc = useQuery({ queryKey: ["doc", documentId], queryFn: () => api(`/api/documents/${documentId}`), enabled: !!documentId });
  const [img, setImg] = React.useState<string | null>(null);
  const isImage = doc.data?.format === "image";
  React.useEffect(() => {
    let url: string | null = null;
    if (isImage && doc.data?.has_derived_image) fileUrl(`/api/documents/${documentId}/file?derived=true`).then((u) => { url = u; setImg(u); }).catch(() => {});
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [isImage, documentId, doc.data?.has_derived_image]);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { ref.current?.querySelector("[data-hit=true]")?.scrollIntoView({ block: "center" }); }, [doc.data, segmentId]);
  if (!documentId) return <div className="text-xs text-slate-500">No source document (value entered manually).</div>;
  if (doc.isLoading) return <Spinner />;
  const segs: any[] = doc.data?.segments || [];
  const hit = segs.find((s) => s.id === segmentId);
  const bbox = (locator || hit?.locator)?.bbox;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">{doc.data?.filename}</span>
        <Link className="inline-flex items-center gap-1 text-accent" href={`/extraction-review/${documentId}`}>Open review <ExternalLink className="h-3 w-3" /></Link>
      </div>
      {isImage && img && bbox && <ImageBox src={img} bbox={bbox} />}
      <div ref={ref} className="max-h-72 overflow-auto rounded border border-slate-200 bg-slate-50 font-mono text-[11px] leading-5 scroll-thin">
        {segs.map((s) => (
          <div key={s.id} data-hit={s.id === segmentId} className={s.id === segmentId ? "bg-amber-100 ring-1 ring-amber-400" : ""}>
            <span className="inline-block w-12 select-none px-1 text-right text-slate-400">{s.id}</span>
            <span className="px-1">{s.text}</span>
            {s.ocr_confidence != null && <span className={`ml-1 text-2xs ${s.ocr_confidence < 80 ? "text-amber-700" : "text-slate-400"}`}>ocr {Math.round(s.ocr_confidence)}</span>}
          </div>
        ))}
      </div>
      {hit && <div className="text-2xs text-slate-500">Location: {Object.entries(hit.locator).filter(([k]) => !["bbox", "page_size", "kind"].includes(k)).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>}
    </div>
  );
}

function ImageBox({ src, bbox }: { src: string; bbox: number[] }) {
  const [dim, setDim] = React.useState<{ w: number; h: number } | null>(null);
  const pad = 30;
  const crop = { x: Math.max(0, bbox[0] - pad), y: Math.max(0, bbox[1] - pad * 2), w: bbox[2] - bbox[0] + pad * 2, h: bbox[3] - bbox[1] + pad * 4 };
  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <div className="relative" style={{ width: "100%", aspectRatio: `${crop.w} / ${crop.h}`, overflow: "hidden" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="source crop" onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
          style={dim ? { position: "absolute", width: `${(dim.w / crop.w) * 100}%`, left: `${(-crop.x / crop.w) * 100}%`, top: `${(-crop.y / crop.h) * 100}%`, maxWidth: "none" } : { opacity: 0 }} />
        <div className="absolute rounded-sm ring-2 ring-amber-500" style={{ left: `${((bbox[0] - crop.x) / crop.w) * 100}%`, top: `${((bbox[1] - crop.y) / crop.h) * 100}%`, width: `${((bbox[2] - bbox[0]) / crop.w) * 100}%`, height: `${((bbox[3] - bbox[1]) / crop.h) * 100}%` }} />
      </div>
      <div className="border-t px-2 py-1 text-2xs text-slate-500">Perspective-corrected photo · OCR line box</div>
    </div>
  );
}

/** Drawer: one vendor × line — original quote, every calculation step, checks, source, and review actions. */
export function QuoteDrawer({ rfxId, vendorId, lineId, onClose }: { rfxId: string; vendorId: string | null; lineId: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const open = !!(vendorId && lineId);
  const q = useQuery({ queryKey: ["quote", rfxId, vendorId, lineId], queryFn: () => api(`/api/rfx/${rfxId}/quotes/${vendorId}/${lineId}`), enabled: open });
  const [mode, setMode] = React.useState<null | "correct">(null);
  const [form, setForm] = React.useState<any>({});
  const [comment, setComment] = React.useState("");
  const [err, setErr] = React.useState<any>(null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { setMode(null); setErr(null); setComment(""); }, [vendorId, lineId]);
  const quote = q.data?.quote;
  async function act(action: string, after?: any) {
    setBusy(true); setErr(null);
    try {
      await api(`/api/rfx/${rfxId}/reviews`, { method: "POST", json: { vendor_id: vendorId, line_id: lineId, action, after, comment: comment || undefined } });
      await Promise.all([qc.invalidateQueries({ queryKey: ["quote"] }), qc.invalidateQueries({ queryKey: ["comparison"] }), qc.invalidateQueries({ queryKey: ["exceptions"] })]);
      setMode(null);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <Drawer open={open} onClose={onClose} wide title={<span>{q.data?.vendor} · {lineId} {q.data?.line?.name ? `— ${q.data.line.name}` : ""}</span>}>
      {q.isLoading || !quote ? <Spinner /> : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={quote.status} />
              {quote.status === "QUOTED" && <ConfidencePill value={quote.confidence} review={quote.review_required} />}
              {quote.review_required && <Badge tone="amber"><AlertTriangle className="h-3 w-3" /> Needs verification</Badge>}
              {quote.conversion_kind && <Badge tone="violet">{title(quote.conversion_kind)}</Badge>}
              {quote.flags?.map((f: string) => <Badge key={f} tone="amber">{title(f)}</Badge>)}
            </div>
            {quote.reason && <p className="text-sm text-slate-700">{quote.reason}</p>}
            <div className="rounded-md border border-slate-200">
              <div className="border-b bg-slate-50 px-3 py-1.5 text-xs font-semibold">Calculation trace</div>
              <table className="w-full text-xs">
                <tbody>
                  {(quote.trace || []).map((s: any, i: number) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="w-36 px-3 py-1.5 text-slate-500">{s.label}</td>
                      <td className="px-3 py-1.5">{s.detail}</td>
                      <td className="px-3 py-1.5 text-right num font-medium">{s.value != null ? num(s.value, 4) : ""}</td>
                    </tr>
                  ))}
                  {!quote.trace?.length && <tr><td className="px-3 py-2 text-slate-500" colSpan={3}>No calculation — value not comparable.</td></tr>}
                </tbody>
              </table>
            </div>
            {quote.assumptions?.length > 0 && (
              <div className="rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-900">
                <div className="mb-1 font-semibold">Assumptions</div>
                <ul className="list-disc pl-4">{quote.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul>
              </div>
            )}
            {quote.conditional_offers?.length > 0 && (
              <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
                {quote.conditional_offers.map((o: any, i: number) => <div key={i}>Conditional offer: {inr(o.value, 2)} if {o.condition}</div>)}
              </div>
            )}
            {q.data?.checks?.length > 0 && (
              <div className="rounded-md border border-slate-200">
                <div className="border-b bg-slate-50 px-3 py-1.5 text-xs font-semibold">Verification checks</div>
                <ul className="divide-y divide-slate-100 text-xs">
                  {q.data.checks.map((c: any, i: number) => (
                    <li key={i} className="flex items-start gap-2 px-3 py-1.5">
                      {c.passed === false ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />}
                      <span className="flex-1">{c.detail || c.name}</span>
                      {c.penalty > 0 && <span className="text-2xs text-slate-400">−{c.penalty}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="rounded-md border border-slate-200 p-3">
              <div className="mb-2 text-xs font-semibold">Buyer review</div>
              <Textarea rows={2} placeholder="Comment (required for corrections) — e.g. 'Confirmed by phone with vendor, 29 Oct'" value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="mt-2 flex flex-wrap gap-2">
                {quote.status === "QUOTED" && <Button size="sm" onClick={() => act("CONFIRM")} loading={busy}>Confirm value</Button>}
                {quote.conversion_kind === "DERIVED_WEIGHT" && <Button size="sm" variant="secondary" onClick={() => act("ACCEPT_ASSUMPTION", { assumption: "DERIVED_WEIGHT" })} loading={busy}>Accept weight assumption</Button>}
                <Button size="sm" variant="outline" onClick={() => { setMode("correct"); setForm({ price: quote.original_price, price_uom: quote.original_uom || "PIECE", units_per_price_uom: q.data?.input?.units_per_price_uom ?? "", currency: quote.original_currency || "INR" }); }}>Correct…</Button>
                <Button size="sm" variant="ghost" onClick={() => act("MARK_NOT_QUOTED")} loading={busy}>Mark not quoted</Button>
                <Button size="sm" variant="ghost" onClick={() => act("MARK_NEEDS_CLARIFICATION")} loading={busy}>Needs clarification</Button>
              </div>
              {mode === "correct" && (
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <label>Price as quoted<Input type="number" step="any" value={form.price ?? ""} onChange={(e) => setForm({ ...form, price: e.target.value })} /></label>
                  <label>Currency<Select className="w-full" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{["INR", "USD", "EUR", "GBP"].map((c) => <option key={c}>{c}</option>)}</Select></label>
                  <label>Price unit<Select className="w-full" value={form.price_uom} onChange={(e) => setForm({ ...form, price_uom: e.target.value })}>{["PIECE", "SET", "ROLL", "HUNDRED", "THOUSAND", "KG", "BUNDLE", "BOX", "PACK", "CARTON"].map((c) => <option key={c}>{c}</option>)}</Select></label>
                  <label>Units per price unit<Input type="number" step="any" value={form.units_per_price_uom ?? ""} onChange={(e) => setForm({ ...form, units_per_price_uom: e.target.value })} placeholder="e.g. 20 per box" /></label>
                  <div className="col-span-2 flex gap-2">
                    <Button size="sm" loading={busy} onClick={() => act("CORRECT", Object.fromEntries(Object.entries({ price: Number(form.price), currency: form.currency, price_uom: form.price_uom, units_per_price_uom: form.units_per_price_uom === "" ? undefined : Number(form.units_per_price_uom) }).filter(([, v]) => v !== undefined)))}>Save correction</Button>
                    <Button size="sm" variant="ghost" onClick={() => setMode(null)}>Cancel</Button>
                  </div>
                </div>
              )}
              <div className="mt-2"><ErrorBox error={err} /></div>
              {q.data?.review_history?.length > 0 && (
                <ul className="mt-3 space-y-1 border-t pt-2 text-2xs text-slate-500">
                  {q.data.review_history.map((h: any, i: number) => <li key={i}>{new Date(h.at).toLocaleString()}: {title(h.action)} {h.after ? JSON.stringify(h.after) : ""} {h.comment ? `— “${h.comment}”` : ""}</li>)}
                </ul>
              )}
            </div>
          </div>
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><FileSearch className="h-3.5 w-3.5" /> Source evidence</div>
            {quote.evidence?.text && <blockquote className="mb-2 rounded border-l-4 border-amber-400 bg-amber-50 px-3 py-2 font-mono text-xs">{quote.evidence.text}</blockquote>}
            <SourcePreview documentId={q.data?.document_id} segmentId={quote.evidence?.segment_id} locator={quote.evidence?.locator} />
          </div>
        </div>
      )}
    </Drawer>
  );
}
