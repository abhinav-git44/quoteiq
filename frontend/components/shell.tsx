"use client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BarChart3, Bot, Building2, ClipboardList, FileStack, FileText, Gauge, HelpCircle, LogOut, Scale, ScrollText, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";
import { api, setSession, token } from "@/lib/api";
import { cn } from "@/lib/format";

const RfxCtx = React.createContext<{ rfxId: string | null; setRfxId: (id: string) => void }>({ rfxId: null, setRfxId: () => {} });
export const useRfx = () => React.useContext(RfxCtx);

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = React.useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } }));
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [ready, setReady] = React.useState(false);
  const [rfxId, setRfxIdState] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!token()) router.replace("/login");
    else setReady(true);
    try {
      setRfxIdState(localStorage.getItem("quoteiq_rfx"));
    } catch {}
  }, [router]);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api("/api/auth/me"), enabled: ready });
  const rfxList = useQuery({ queryKey: ["rfx-list"], queryFn: () => api<any[]>("/api/rfx"), enabled: ready });
  React.useEffect(() => {
    const m = path.match(/^\/(rfx|comparison|analyst|award|submissions)\/([0-9a-f-]{36})/);
    if (m) setRfxId(m[2]);
    else if (!rfxId && rfxList.data?.length) {
      const live = rfxList.data.find((r) => r.status !== "DRAFT") || rfxList.data[0];
      setRfxId(live.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, rfxList.data]);
  const setRfxId = (id: string) => {
    setRfxIdState(id);
    try {
      localStorage.setItem("quoteiq_rfx", id);
    } catch {}
  };
  if (!ready) return null;
  const r = rfxId || "";
  const nav = [
    { href: "/dashboard", label: "Overview", icon: Gauge },
    { href: "/rfx", label: "RFx Management", icon: ClipboardList },
    { href: "/vendors", label: "Vendors", icon: Building2 },
    { href: `/submissions/${r}`, label: "Submissions", icon: FileStack, needs: true },
    { href: `/comparison/${r}`, label: "Comparison", icon: BarChart3, needs: true },
    { href: `/analyst/${r}`, label: "AI Analyst", icon: Bot, needs: true },
    { href: `/award/${r}`, label: "Award", icon: Scale, needs: true },
    { href: "/reports", label: "Reports", icon: FileText },
    { href: "/audit-logs", label: "Audit Logs", icon: ScrollText },
  ];
  const current = rfxList.data?.find((x) => x.id === rfxId);
  return (
    <RfxCtx.Provider value={{ rfxId, setRfxId }}>
      <div className="flex min-h-screen">
        <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col bg-navy-950 text-slate-300 md:flex">
          <div className="flex items-center gap-2 px-4 py-4">
            <div className="grid h-7 w-7 place-items-center rounded bg-accent text-xs font-bold text-white">Q</div>
            <div>
              <div className="text-sm font-semibold text-white">QuoteIQ</div>
              <div className="text-2xs text-slate-400">Quotes → confident decisions</div>
            </div>
          </div>
          <nav className="mt-2 flex-1 space-y-0.5 px-2">
            {nav.map((n) => {
              const active = path === n.href || (n.href !== "/dashboard" && path.startsWith(n.href.split("/").slice(0, 2).join("/")));
              const disabled = n.needs && !rfxId;
              return (
                <Link key={n.label} href={disabled ? "#" : n.href} className={cn("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm", active ? "bg-navy-800 text-white" : "hover:bg-navy-900 hover:text-white", disabled && "opacity-40")}>
                  <n.icon className="h-4 w-4" /> {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-navy-800 px-4 py-3 text-2xs text-slate-400">
            <div className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Synthetic demo data</div>
            <div className="mt-1">{me.data?.ai_enabled ? `AI: ${me.data.model}` : <span className="text-amber-300">AI disabled — set ANTHROPIC_API_KEY</span>}</div>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col md:pl-56">
          <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur">
            <select className="h-8 max-w-xs rounded-md border border-slate-200 bg-slate-50 px-2 text-xs" value="org" onChange={() => {}} aria-label="Organization">
              <option value="org">Kaveri Home Appliances (fictional)</option>
            </select>
            {rfxList.data && rfxList.data.length > 0 && (
              <select className="h-8 max-w-sm rounded-md border border-slate-200 bg-white px-2 text-xs" value={rfxId || ""} onChange={(e) => setRfxId(e.target.value)} aria-label="Current RFx">
                {rfxList.data.map((x) => <option key={x.id} value={x.id}>{x.reference} · {x.title.slice(0, 40)}</option>)}
              </select>
            )}
            <div className="relative ml-2 hidden flex-1 lg:block">
              <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input placeholder="Search lines, vendors… (press / in comparison)" className="h-8 w-full max-w-sm rounded-md border border-slate-200 bg-slate-50 pl-8 text-xs" />
            </div>
            <div className="ml-auto flex items-center gap-3 text-xs text-slate-600">
              {current && <span className="hidden xl:inline text-slate-400">{current.status}</span>}
              <a href="https://github.com" onClick={(e) => e.preventDefault()} title="See docs/DEMO_SCRIPT.md"><HelpCircle className="h-4 w-4" /></a>
              <span className="font-medium">{me.data?.name}</span>
              <button title="Sign out" onClick={() => { setSession(null); router.push("/login"); }}><LogOut className="h-4 w-4" /></button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 md:px-6">{children}</main>
        </div>
      </div>
    </RfxCtx.Provider>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold text-navy-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}
