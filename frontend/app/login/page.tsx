"use client";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Button, ErrorBox, Input } from "@/components/ui";
import { api, setSession } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = React.useState("buyer@kaveri.example");
  const [password, setPassword] = React.useState("quoteiq-demo");
  const [err, setErr] = React.useState<any>(null);
  const [busy, setBusy] = React.useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api("/api/auth/login", { method: "POST", json: { email, password } });
      setSession(r.token, r.user);
      router.push("/dashboard");
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <div className="grid min-h-screen place-items-center bg-navy-950 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-5 flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded bg-accent text-sm font-bold text-white">Q</div>
          <div>
            <div className="font-semibold text-navy-900">QuoteIQ</div>
            <div className="text-xs text-slate-500">From vendor quotations to confident procurement decisions</div>
          </div>
        </div>
        <label className="text-xs font-medium text-slate-600">Email</label>
        <Input value={email} onChange={(e) => setEmail(e.target.value)} className="mb-3 mt-1" autoComplete="username" />
        <label className="text-xs font-medium text-slate-600">Password</label>
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mb-4 mt-1" autoComplete="current-password" placeholder="password" />
        <ErrorBox error={err} />
        <Button type="submit" loading={busy} className="mt-3 w-full">Sign in</Button>
        <div className="mt-4 rounded-md bg-slate-50 px-3 py-2 text-center text-xs text-slate-600">
          Demo login (pre-filled): <b>buyer@kaveri.example</b> / <b>quoteiq-demo</b>
          <div className="mt-0.5 text-2xs text-slate-400">First load may take ~50 s while the free server wakes up.</div>
        </div>
        <p className="mt-3 text-center text-2xs text-slate-400">Synthetic demonstration data · Aerchain take-home</p>
      </form>
    </div>
  );
}
