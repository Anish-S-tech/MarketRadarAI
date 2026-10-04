import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows, Radar, Search, Target } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, call } from "@/api/client";
import { Button, ErrorNote, Field, Input } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";

const AGENTS: { icon: ReactNode; name: string; text: string }[] = [
  { icon: <Radar className="size-4" />, name: "Scout", text: "Watches pricing pages, blogs, news and filings around the clock" },
  { icon: <GitCompareArrows className="size-4" />, name: "Change Detection", text: "Separates real moves from cosmetic noise" },
  { icon: <Search className="size-4" />, name: "Research & Verification", text: "Corroborates every claim with scored evidence" },
  { icon: <Target className="size-4" />, name: "Impact & Alerts", text: "Explains what it means for you, per role, prioritised" },
];

/** Concentric radar rings with a sweep and blips — decorative brand illustration. */
function RadarArt() {
  return (
    <svg viewBox="0 0 200 200" className="size-full" aria-hidden="true">
      <defs>
        <radialGradient id="sweep" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(100 100) scale(96)">
          <stop offset="0" stopColor="#5eead4" stopOpacity="0.55" />
          <stop offset="1" stopColor="#5eead4" stopOpacity="0" />
        </radialGradient>
      </defs>
      {[96, 72, 48, 24].map((r) => (
        <circle key={r} cx="100" cy="100" r={r} fill="none" stroke="#99f6e4" strokeOpacity="0.22" />
      ))}
      <path d="M100 100 L100 4 A96 96 0 0 1 183 52 Z" fill="url(#sweep)" className="origin-center animate-[spin_6s_linear_infinite]" style={{ transformOrigin: "100px 100px" }} />
      <line x1="4" y1="100" x2="196" y2="100" stroke="#99f6e4" strokeOpacity="0.15" />
      <line x1="100" y1="4" x2="100" y2="196" stroke="#99f6e4" strokeOpacity="0.15" />
      {[
        [140, 62, "#f87171"],
        [62, 128, "#fbbf24"],
        [128, 146, "#5eead4"],
        [72, 70, "#5eead4"],
      ].map(([x, y, c], i) => (
        <g key={i}>
          <circle cx={x as number} cy={y as number} r="9" fill={c as string} opacity="0.18" className="animate-ping" style={{ transformOrigin: `${x}px ${y}px`, animationDuration: `${2.4 + i * 0.6}s` }} />
          <circle cx={x as number} cy={y as number} r="3.5" fill={c as string} />
        </g>
      ))}
    </svg>
  );
}

function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-brand-900 via-brand-800 to-slate-900 p-12 text-white lg:flex lg:flex-col">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20">
            <Radar className="size-5" />
          </span>
          <span className="text-lg font-semibold tracking-tight">MarketRadar</span>
          <span className="rounded bg-white/10 px-1.5 text-[11px] font-semibold text-brand-200">AI</span>
        </div>
        <div className="pointer-events-none absolute -right-24 top-1/2 size-[520px] -translate-y-1/2 opacity-90">
          <RadarArt />
        </div>
        <div className="relative mt-auto max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            Know what your competitors did — before your customers tell you.
          </h2>
          <p className="mt-3 text-brand-100/80">
            Autonomous agents monitor, verify and explain competitor moves, then brief each team on what to do next.
          </p>
          <ul className="mt-8 space-y-4">
            {AGENTS.map((a) => (
              <li key={a.name} className="flex gap-3">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-brand-200 ring-1 ring-white/15">
                  {a.icon}
                </span>
                <div>
                  <p className="text-sm font-semibold">{a.name}</p>
                  <p className="text-sm text-brand-100/70">{a.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <main className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <span className="mb-5 flex size-10 items-center justify-center rounded-xl bg-brand-700 text-white shadow-sm lg:hidden">
              <Radar className="size-5" />
            </span>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-1.5 text-sm text-muted">{subtitle}</p>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}

function useAuthConfig() {
  return useQuery({ queryKey: ["auth-config"], queryFn: () => call(api.GET("/api/v1/auth/config")) });
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const config = useAuthConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={(location.state as { from?: string })?.from ?? "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate((location.state as { from?: string })?.from ?? "/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to see what changed while you were away">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email">
          <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" variant="primary" className="h-10 w-full" loading={busy}>
          Sign in
        </Button>
      </form>
      {config.data?.oidc_enabled && (
        <a href="/api/v1/auth/oidc/login" className="mt-3 block">
          <Button className="w-full">Continue with {config.data.oidc_name}</Button>
        </a>
      )}
      {config.data?.allow_signup && (
        <p className="mt-5 text-center text-sm text-muted">
          New here?{" "}
          <Link to="/register" className="font-medium text-brand-700 hover:underline dark:text-brand-300">
            Create an organisation
          </Link>
        </p>
      )}
    </AuthLayout>
  );
}

export function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ org_name: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(form);
      navigate("/settings?tab=company", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout title="Create your organisation" subtitle="You'll be the admin; invite your team afterwards">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Company name">
          <Input required value={form.org_name} onChange={set("org_name")} />
        </Field>
        <Field label="Your name">
          <Input required value={form.full_name} onChange={set("full_name")} />
        </Field>
        <Field label="Work email">
          <Input type="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" hint="At least 10 characters">
          <Input type="password" minLength={10} required value={form.password} onChange={set("password")} />
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" variant="primary" className="h-10 w-full" loading={busy}>
          Create organisation
        </Button>
      </form>
      <p className="mt-5 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-brand-700 hover:underline dark:text-brand-300">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}

export function OidcCallback() {
  const { acceptTokens } = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const access = params.get("access_token");
    const refresh = params.get("refresh_token");
    if (access && refresh) acceptTokens(access, refresh);
    navigate("/", { replace: true });
  }, [acceptTokens, navigate]);
  return null;
}
