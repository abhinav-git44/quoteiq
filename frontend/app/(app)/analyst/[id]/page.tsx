"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, ChevronDown, ChevronRight, MessageSquarePlus, Send, ShieldCheck, Wrench } from "lucide-react";
import * as React from "react";
import { use } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DisplayView } from "@/components/display";
import { PageHeader } from "@/components/shell";
import { Badge, Button, ErrorBox, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";

type Msg = { id?: string; role: "user" | "assistant"; content: string; tool_calls?: any[]; displays?: any[]; ungrounded_numbers?: string[]; model?: string };

export default function Analyst({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const sugg = useQuery({ queryKey: ["sugg", id], queryFn: () => api<string[]>(`/api/rfx/${id}/analyst/suggestions`) });
  const convs = useQuery({ queryKey: ["convs", id], queryFn: () => api<any[]>(`/api/rfx/${id}/analyst/conversations`) });
  const [cid, setCid] = React.useState<string | null>(null);
  const [msgs, setMsgs] = React.useState<Msg[]>([]);
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<any>(null);
  const end = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setText(""); setErr(null); setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: question }]);
    try {
      const r = await api(`/api/rfx/${id}/analyst/chat`, { method: "POST", json: { question, conversation_id: cid } });
      setCid(r.conversation_id);
      setMsgs((m) => [...m, r.message]);
      qc.invalidateQueries({ queryKey: ["convs", id] });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function open(c: string) {
    const r = await api(`/api/analyst/conversations/${c}`);
    setCid(c); setMsgs(r.messages);
  }
  return (
    <>
      <PageHeader title="AI procurement analyst" subtitle="Ask in plain language. Answers come only from restricted tools over the normalized data; every number is checked against tool output." />
      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <aside className="hidden space-y-1 lg:block">
          <Button size="sm" variant="outline" className="w-full" onClick={() => { setCid(null); setMsgs([]); }}><MessageSquarePlus className="h-3.5 w-3.5" /> New conversation</Button>
          <div className="pt-2 text-2xs font-medium uppercase text-slate-400">History</div>
          {convs.data?.map((c) => (
            <button key={c.id} onClick={() => open(c.id)} className={cn("block w-full truncate rounded px-2 py-1.5 text-left text-xs hover:bg-white", c.id === cid && "bg-white font-medium")}>{c.title}</button>
          ))}
        </aside>
        <div className="flex min-h-[70vh] flex-col rounded-lg border border-slate-200 bg-white">
          <div className="flex-1 space-y-5 overflow-y-auto p-4 scroll-thin">
            {msgs.length === 0 && (
              <div className="mx-auto max-w-2xl py-6">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium text-navy-900"><Bot className="h-4 w-4 text-accent" /> Questions worth asking</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {sugg.data?.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-md border border-slate-200 px-3 py-2 text-left text-xs hover:border-accent hover:bg-accent-soft">{s}</button>)}
                </div>
              </div>
            )}
            {msgs.map((m, i) => m.role === "user" ? (
              <div key={i} className="ml-auto max-w-2xl rounded-lg bg-navy-800 px-3 py-2 text-sm text-white">{m.content}</div>
            ) : <AssistantMsg key={i} m={m} />)}
            {busy && <div className="flex items-center gap-2 text-xs text-slate-500"><Wrench className="h-3.5 w-3.5 animate-pulse" /> Running tools over the comparison…</div>}
            <ErrorBox error={err} />
            <div ref={end} />
          </div>
          <div className="border-t border-slate-200 p-3">
            <div className="flex gap-2">
              <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. What if we split it, cheapest per line, but only among vendors who cleared the quality questionnaire?"
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }} />
              <Button onClick={() => ask(text)} loading={busy} className="self-end"><Send className="h-4 w-4" /></Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function AssistantMsg({ m }: { m: Msg }) {
  const [showTools, setShowTools] = React.useState(false);
  return (
    <div className="max-w-5xl space-y-3">
      <div className="prose-answer text-sm text-slate-800"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>
      {m.ungrounded_numbers && m.ungrounded_numbers.length > 0 ? (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>These figures could not be traced to a tool result and may be the model's own arithmetic — verify before use: <b>{m.ungrounded_numbers.join(", ")}</b></span>
        </div>
      ) : (m.tool_calls?.length ?? 0) > 0 && (
        <div className="inline-flex items-center gap-1 text-2xs text-emerald-700"><ShieldCheck className="h-3.5 w-3.5" /> Every figure in this answer traces to a tool result</div>
      )}
      {m.displays?.map((d, i) => <DisplayView key={i} d={d} />)}
      {(m.tool_calls?.length ?? 0) > 0 && (
        <div className="rounded-md border border-slate-200 text-xs">
          <button className="flex w-full items-center gap-1.5 px-3 py-1.5 text-slate-600" onClick={() => setShowTools(!showTools)}>
            {showTools ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            {m.tool_calls!.length} tool call(s): {m.tool_calls!.map((t) => t.name).join(" → ")} {m.model && <Badge className="ml-auto">{m.model}</Badge>}
          </button>
          {showTools && (
            <ul className="divide-y divide-slate-100 border-t">
              {m.tool_calls!.map((t, i) => (
                <li key={i} className="px-3 py-2">
                  <div className="flex items-center gap-2"><span className="font-mono font-medium">{t.name}</span>{t.ok ? <Badge tone="green">ok</Badge> : <Badge tone="red">error</Badge>}<span className="text-slate-400">{t.ms} ms</span></div>
                  <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-1.5 text-2xs">{JSON.stringify(t.input)}</pre>
                  {t.error && <div className="mt-1 text-red-700">{t.error}</div>}
                  {t.result && <details className="mt-1"><summary className="cursor-pointer text-slate-500">result</summary><pre className="max-h-64 overflow-auto rounded bg-slate-50 p-1.5 text-2xs scroll-thin">{JSON.stringify(t.result, null, 1)}</pre></details>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
