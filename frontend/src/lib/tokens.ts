/** Access/refresh token storage with proactive, single-flight refresh. */

const ACCESS = "mr.access";
const REFRESH = "mr.refresh";

type Listener = () => void;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) — session lives in memory only */
  }
}

function expiryOf(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return (payload.exp as number) * 1000;
  } catch {
    return 0;
  }
}

class TokenStore {
  private access: string | null = read(ACCESS);
  private refresh: string | null = read(REFRESH);
  private inflight: Promise<string | null> | null = null;
  private listeners = new Set<Listener>();

  hasSession() {
    return !!this.refresh;
  }

  set(access: string, refresh: string) {
    this.access = access;
    this.refresh = refresh;
    write(ACCESS, access);
    write(REFRESH, refresh);
    this.emit();
  }

  clear() {
    this.access = this.refresh = null;
    write(ACCESS, null);
    write(REFRESH, null);
    this.emit();
  }

  /** Called when the API rejects our credentials. */
  expire() {
    this.clear();
  }

  refreshToken() {
    return this.refresh;
  }

  subscribe(fn: Listener) {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private emit() {
    this.listeners.forEach((l) => l());
  }

  /** Returns a valid access token, refreshing it first if it expires within 30s. */
  async freshAccessToken(): Promise<string | null> {
    if (!this.access) return null;
    if (expiryOf(this.access) - Date.now() > 30_000) return this.access;
    if (!this.refresh) return null;
    if (!this.inflight) {
      this.inflight = (async () => {
        try {
          const r = await fetch("/api/v1/auth/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: this.refresh }),
          });
          if (!r.ok) {
            this.clear();
            return null;
          }
          const data = await r.json();
          this.set(data.access_token, data.refresh_token);
          return data.access_token as string;
        } finally {
          this.inflight = null;
        }
      })();
    }
    return this.inflight;
  }
}

export const tokenStore = new TokenStore();
