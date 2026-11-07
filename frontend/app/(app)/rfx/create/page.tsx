"use client";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plus, Send, Sparkles, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, ErrorBox, Input, Textarea } from "@/components/ui";
import { api } from "@/lib/api";

type Draft = any;
const EMPTY: Draft = { title: "", category: "", description: "", currency: "INR", line_items: [], questionnaire: [], vendor_eligibility_rules: [] };
const EXAMPLE = "I need 30 corrugated packaging products for our Chakan manufacturing plant — boxes in 3, 5 and 7 ply, plus sheets, rolls, partitions and inserts. Invite five suppliers. Products must meet our quality requirements and suppliers should deliver within 15 days.";

function Suspended() {
  const router = useRouter();
  const sp = useSearchParams();
  const editId = sp.get("id");
  const [history, setHistory] = React.useState<any[]>([]);
  const [chat, setChat] = React.useState<{ role: string; text: string }[]>([]);
  const [text, setText] = React.useState("");
  const [draft, setDraft] = React.useState<Draft>(EMPTY);
  const [issues, setIssues] = React.useState<string[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<any>(null);
  const [savedId, setSavedId] = React.useState<string | null>(editId);
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => api<any[]>("/api/vendors") });
  const [invite, setInvite] = React.useState<string[]>([]);

  React.useEffect(() => {
    if (!editId) return;
    api(`/api/rfx/${editId}`).then((r) => {
      setDraft({ title: r.title, category: r.category, description: r.description, business_justification: r.business_justification,
        delivery_location: r.delivery_location, submission_deadline: r.submission_deadline, currency: r.currency, required_delivery_days: r.required_delivery_days,
        payment_terms: r.terms.find((t: any) => t.kind === "PAYMENT")?.text, commercial_terms: r.terms.find((t: any) => t.kind === "COMMERCIAL")?.text,
        line_items: r.lines, questionnaire: r.questionnaire, vendor_eligibility_rules: r.terms.filter((t: any) => t.kind === "ELIGIBILITY_RULE").map((t: any) => t.text) });
      if (r.copilot_transcript) setHistory(r.copilot_transcript);
    });
  }, [editId]);

  async function send() {
    if (!text.trim()) return;
    const msg = text;
    setText(""); setBusy(true); setErr(null);
    setChat((c) => [...c, { role: "user", text: msg }]);
    try {
      const t = await api("/api/rfx/copilot", { method: "POST", json: { history, text: msg, draft: draft.line_items.length || draft.title ? draft : null } });
      setHistory(t.messages);
      setChat((c) => [...c, { role: "assistant", text: t.assistant_text }]);
      if (t.draft) setDraft(t.draft);
      setIssues(t.issues || []);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  async function save(): Promise<string | null> {
    setBusy(true); setErr(null);
    try {
      const body = { draft, copilot_transcript: history };
      const r = savedId ? await api(`/api/rfx/${savedId}`, { method: "PUT", json: body }) : await api("/api/rfx", { method: "POST", json: body });
      setSavedId(r.id); setIssues(r.issues || []);
      return r.id;
    } catch (e) { setErr(e); return null; } finally { setBusy(false); }
  }

  async function publish() {
    const id = await save();
    if (!id) return;
    if (draft.line_items.length === 0) { setErr(new Error("Add line items first")); return; }
    try {
      await api(`/api/rfx/${id}/publish`, { method: "POST", json: { vendor_ids: invite } });
      router.push(`/rfx/${id}`);
    } catch (e) { setErr(e); }
  }

  const setLine = (i: number, patch: any) => setDraft((d: Draft) => ({ ...d, line_items: d.line_items.map((l: any, j: number) => (j === i ? { ...l, ...patch } : l)) }));
  const addLine = () => setDraft((d: Draft) => ({ ...d, line_items: [...d.line_items, { line_id: `L${String(d.line_items.length + 1).padStart(2, "0")}`, item_code: "", name: "", description: "", spec: {}, quantity: 1, uom: "pcs", mandatory: true }] }));

  return (
    <>
      <PageHeader title="RFx co-pilot" subtitle="Talk the RFx into existence. The co-pilot insists on one pricing basis per line — that is what makes vendor answers comparable later."
        actions={<><Button variant="outline" onClick={save} loading={busy}>Save as draft</Button></>} />
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-2" title={<span className="inline-flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-accent" /> Conversation</span>}>
          <div className="mb-3 max-h-[520px] min-h-[200px] space-y-3 overflow-y-auto scroll-thin">
            {chat.length === 0 && (
              <button className="w-full rounded-md border border-dashed border-slate-300 p-3 text-left text-xs text-slate-600 hover:bg-slate-50" onClick={() => setText(EXAMPLE)}>
                Try: “{EXAMPLE}”
              </button>
            )}
            {chat.map((m, i) => (
              <div key={i} className={m.role === "user" ? "ml-8 rounded-lg bg-navy-800 px-3 py-2 text-sm text-white" : "mr-8 rounded-lg bg-slate-100 px-3 py-2 text-sm whitespace-pre-wrap"}>{m.text}</div>
            ))}
            {busy && <div className="mr-8 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-500">Drafting…</div>}
          </div>
          <div className="flex gap-2">
            <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe what you need, or ask to change the draft…" onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} />
            <Button onClick={send} loading={busy} className="self-end"><Send className="h-4 w-4" /></Button>
          </div>
          <div className="mt-2"><ErrorBox error={err} /></div>
        </Card>
        <div className="space-y-4 xl:col-span-3">
          {issues.length > 0 && (
            <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {issues.map((i) => <div key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{i}</div>)}
            </div>
          )}
          <Card title="Draft">
            <div className="grid gap-2 md:grid-cols-2">
              <label className="text-xs">Title<Input value={draft.title || ""} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
              <label className="text-xs">Category<Input value={draft.category || ""} onChange={(e) => setDraft({ ...draft, category: e.target.value })} /></label>
              <label className="text-xs md:col-span-2">Description<Textarea rows={2} value={draft.description || ""} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
              <label className="text-xs">Delivery location<Input value={draft.delivery_location || ""} onChange={(e) => setDraft({ ...draft, delivery_location: e.target.value })} /></label>
              <label className="text-xs">Submission deadline<Input type="date" value={draft.submission_deadline || ""} onChange={(e) => setDraft({ ...draft, submission_deadline: e.target.value })} /></label>
              <label className="text-xs">Payment terms<Input value={draft.payment_terms || ""} onChange={(e) => setDraft({ ...draft, payment_terms: e.target.value })} /></label>
              <label className="text-xs">Pricing basis / commercial terms<Input value={draft.commercial_terms || ""} onChange={(e) => setDraft({ ...draft, commercial_terms: e.target.value })} /></label>
            </div>
          </Card>
          <Card title={<span>Line items <Badge tone={draft.line_items.length === 30 ? "green" : "amber"}>{draft.line_items.length}</Badge></span>} actions={<Button size="sm" variant="outline" onClick={addLine}><Plus className="h-3.5 w-3.5" /> Add line</Button>}>
            <div className="max-h-[420px] overflow-auto scroll-thin">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-white text-left text-slate-500"><tr><th>Line</th><th>Item</th><th>Spec (JSON)</th><th>Qty</th><th>UOM</th><th></th></tr></thead>
                <tbody>
                  {draft.line_items.map((l: any, i: number) => (
                    <tr key={i} className="border-t border-slate-100 align-top">
                      <td className="py-1 font-mono">{l.line_id}</td>
                      <td className="py-1"><Input className="h-7 text-xs" value={l.name} onChange={(e) => setLine(i, { name: e.target.value })} /></td>
                      <td className="py-1"><Input className="h-7 font-mono text-2xs" defaultValue={JSON.stringify(l.spec)} onBlur={(e) => { try { setLine(i, { spec: JSON.parse(e.target.value) }); } catch { /* keep */ } }} /></td>
                      <td className="py-1"><Input className="h-7 w-24 text-xs" type="number" value={l.quantity} onChange={(e) => setLine(i, { quantity: Number(e.target.value) })} /></td>
                      <td className="py-1">{l.uom}</td>
                      <td className="py-1"><button onClick={() => setDraft((d: Draft) => ({ ...d, line_items: d.line_items.filter((_: any, j: number) => j !== i) }))}><Trash2 className="h-3.5 w-3.5 text-slate-400 hover:text-red-600" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={`Questionnaire (${draft.questionnaire.length})`}>
            <ol className="space-y-1 text-xs">{draft.questionnaire.map((q: any, i: number) => (
              <li key={i} className="flex items-center gap-2"><span className="font-mono text-slate-400">{q.qid}</span>
                <Input className="h-7 text-xs" value={q.text} onChange={(e) => setDraft({ ...draft, questionnaire: draft.questionnaire.map((x: any, j: number) => (j === i ? { ...x, text: e.target.value } : x)) })} />
                <label className="flex items-center gap-1 whitespace-nowrap"><input type="checkbox" checked={q.mandatory} onChange={(e) => setDraft({ ...draft, questionnaire: draft.questionnaire.map((x: any, j: number) => (j === i ? { ...x, mandatory: e.target.checked } : x)) })} /> mandatory</label>
              </li>))}
            </ol>
          </Card>
          <Card title="Publish" subtitle="Email sending is stubbed in this build: invitations are recorded, nothing is sent.">
            <div className="flex flex-wrap gap-3 text-sm">
              {vendors.data?.map((v) => (
                <label key={v.vendor_id} className="flex items-center gap-1.5"><input type="checkbox" checked={invite.includes(v.vendor_id)} onChange={(e) => setInvite(e.target.checked ? [...invite, v.vendor_id] : invite.filter((x) => x !== v.vendor_id))} />{v.name}</label>
              ))}
            </div>
            <Button className="mt-3" onClick={publish} disabled={!invite.length || !draft.line_items.length}>Save & publish to {invite.length} vendor(s)</Button>
          </Card>
        </div>
      </div>
    </>
  );
}

export default function CreateRfx() {
  return <React.Suspense fallback={null}><Suspended /></React.Suspense>;
}
