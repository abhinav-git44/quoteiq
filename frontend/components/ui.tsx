"use client";
import { Loader2 } from "lucide-react";
import * as React from "react";
import { cn, STATUS_TONE, title } from "@/lib/format";

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "outline";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...p }: BtnProps) {
  const v = {
    primary: "bg-navy-800 text-white hover:bg-navy-700 shadow-sm",
    secondary: "bg-accent-soft text-accent hover:bg-indigo-100",
    outline: "border border-slate-300 bg-white text-ink hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  const s = size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm";
  return (
    <button
      className={cn("inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none", v, s, className)}
      disabled={disabled || loading}
      {...p}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

const TONES = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
};

export function Badge({ tone = "slate", children, className, title: t }: { tone?: keyof typeof TONES; children: React.ReactNode; className?: string; title?: string }) {
  return (
    <span title={t} className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs font-medium ring-1 ring-inset whitespace-nowrap", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function StatusBadge({ status, className }: { status?: string | null; className?: string }) {
  if (!status) return null;
  return <Badge tone={STATUS_TONE[status] || "slate"} className={className}>{title(status)}</Badge>;
}

export function Card({ className, children, title: t, actions, subtitle }: { className?: string; children: React.ReactNode; title?: React.ReactNode; actions?: React.ReactNode; subtitle?: React.ReactNode }) {
  return (
    <section className={cn("rounded-lg border border-slate-200 bg-white", className)}>
      {(t || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
          <div>
            <h3 className="text-sm font-semibold text-navy-900">{t}</h3>
            {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "amber" | "red" | "green" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-2xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cn("mt-1 text-xl font-semibold num", tone === "amber" && "text-amber-700", tone === "red" && "text-red-700", tone === "green" && "text-emerald-700")}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn("h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20", className)} {...p} />;
});

export function Textarea({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/20", className)} {...p} />;
}

export function Select({ className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn("h-9 rounded-md border border-slate-300 bg-white px-2 text-sm outline-none focus:border-accent", className)} {...p}>{children}</select>;
}

export function Toggle({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 text-xs">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)} className={cn("rounded px-2.5 py-1 font-medium", value === o.value ? "bg-navy-800 text-white" : "text-slate-600 hover:bg-slate-100")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-slate-500 justify-center">
      <Loader2 className="h-4 w-4 animate-spin" /> {label || "Loading…"}
    </div>
  );
}

export function ErrorBox({ error }: { error: any }) {
  if (!error) return null;
  const d = error?.detail;
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {typeof d === "object" && d?.message ? (
        <>
          {d.message} {d.lines && <span className="font-mono text-xs">({d.lines.join(", ")})</span>}
        </>
      ) : (
        String(error?.message || error)
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">{children}</div>;
}

export function Drawer({ open, onClose, children, title: t, wide }: { open: boolean; onClose: () => void; children: React.ReactNode; title?: React.ReactNode; wide?: boolean }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-navy-950/30" onClick={onClose}>
      <aside className={cn("h-full overflow-y-auto bg-white shadow-xl scroll-thin", wide ? "w-full max-w-4xl" : "w-full max-w-xl")} onClick={(e) => e.stopPropagation()}>
        <header className="sticky top-0 z-10 flex items-center justify-between border-b bg-white px-5 py-3">
          <div className="text-sm font-semibold">{t}</div>
          <button onClick={onClose} className="text-slate-500 hover:text-ink text-lg leading-none">×</button>
        </header>
        <div className="p-5">{children}</div>
      </aside>
    </div>
  );
}

export function ConfidencePill({ value, review }: { value: number; review?: boolean }) {
  const tone = review ? "amber" : value >= 90 ? "green" : value >= 70 ? "blue" : "amber";
  return <Badge tone={tone} title="Heuristic confidence (0–100) from source checks; not a calibrated probability">{Math.round(value)}</Badge>;
}
