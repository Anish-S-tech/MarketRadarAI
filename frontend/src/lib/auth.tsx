import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, call, type Role, type TokenOut, type UserOut } from "@/api/client";
import { tokenStore } from "./tokens";

interface AuthState {
  user: UserOut | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (body: { org_name: string; full_name: string; email: string; password: string }) => Promise<void>;
  acceptTokens: (access: string, refresh: string) => void;
  logout: () => Promise<void>;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [hasSession, setHasSession] = useState(tokenStore.hasSession());

  useEffect(() => tokenStore.subscribe(() => setHasSession(tokenStore.hasSession())), []);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => call(api.GET("/api/v1/auth/me")),
    enabled: hasSession,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const accept = useCallback(
    (t: TokenOut) => {
      tokenStore.set(t.access_token, t.refresh_token);
      qc.setQueryData(["me"], t.user);
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      accept(await call(api.POST("/api/v1/auth/login", { body: { email, password } })));
    },
    [accept],
  );

  const register = useCallback(
    async (body: { org_name: string; full_name: string; email: string; password: string }) => {
      accept(await call(api.POST("/api/v1/auth/register", { body })));
    },
    [accept],
  );

  const acceptTokens = useCallback(
    (access: string, refresh: string) => {
      tokenStore.set(access, refresh);
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    [qc],
  );

  const logout = useCallback(async () => {
    const refresh = tokenStore.refreshToken();
    tokenStore.clear();
    qc.clear();
    if (refresh) await api.POST("/api/v1/auth/logout", { body: { refresh_token: refresh } }).catch(() => undefined);
  }, [qc]);

  const user = hasSession ? (me.data ?? null) : null;
  const hasRole = useCallback(
    (...roles: Role[]) => !!user && (user.role === "admin" || roles.includes(user.role)),
    [user],
  );

  return (
    <AuthContext.Provider
      value={{ user, loading: hasSession && me.isLoading, login, register, acceptTokens, logout, hasRole }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
