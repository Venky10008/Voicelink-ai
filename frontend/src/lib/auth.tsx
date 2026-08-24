import { useNavigate } from "@tanstack/react-router";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
  type Context,
} from "react";
import { Skeleton } from "@/components/ui/skeleton";

const STORAGE_KEY = "voicelink.auth";

export type AuthUser = { name?: string; email?: string } | null;

type AuthState = {
  /** null while the stored session is being read on the client */
  isAuthenticated: boolean | null;
  token: string | null;
  user: AuthUser;
  /** Call after your backend login/signup succeeds */
  signIn: (token: string, user?: AuthUser) => void;
  signOut: () => void;
};

const g = globalThis as unknown as { __voicelinkAuthCtx?: Context<AuthState | null> };
const AuthContext =
  g.__voicelinkAuthCtx ?? (g.__voicelinkAuthCtx = createContext<AuthState | null>(null));

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let unsubFirebase: (() => void) | null = null;
    let everSeenLiveSession = false;

    // 1) Restore whatever token was stored on this device (may be stale).
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as { token: string; user?: AuthUser };
        if (parsed?.token) {
          setToken(parsed.token);
          setUser(parsed.user ?? null);
        }
      }
    } catch {
      /* ignore malformed storage */
    }

    // 2) Keep that session FRESH. Firebase ID tokens expire every hour, so a
    // stored token goes stale and the backend rejects it. Subscribing to
    // Firebase's token refreshes re-mints a valid token from the persisted
    // session (immediately on load, then again whenever the SDK rotates it).
    (async () => {
      try {
        const { subscribeIdToken } = await import("@/lib/firebase");
        unsubFirebase = await subscribeIdToken((nextToken, nextUser) => {
          if (nextToken) {
            everSeenLiveSession = true;
            setToken(nextToken);
            setUser(nextUser ?? null);
            try {
              localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({ token: nextToken, user: nextUser ?? null }),
              );
            } catch {
              /* ignore */
            }
          } else if (everSeenLiveSession) {
            // A real sign-out after a live session — drop the stored token.
            // (The first null fire before session restore is left alone.)
            setToken(null);
            setUser(null);
            try {
              localStorage.removeItem(STORAGE_KEY);
            } catch {
              /* ignore */
            }
          }
        });
      } catch {
        /* Firebase not configured — keep whatever was stored */
      }
    })();

    setReady(true);
    return () => {
      unsubFirebase?.();
    };
  }, []);

  const signIn = useCallback((nextToken: string, nextUser: AuthUser = null) => {
    setToken(nextToken);
    setUser(nextUser);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: nextToken, user: nextUser }));
    } catch {
      /* ignore */
    }
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    // End the Firebase session too, otherwise it silently restores on reload
    // and the app signs the user back in against their wishes.
    import("@/lib/firebase").then((m) => m.signOutFirebase()).catch(() => {});
  }, []);

  const value = useMemo<AuthState>(
    () => ({ isAuthenticated: ready ? Boolean(token) : null, token, user, signIn, signOut }),
    [ready, token, user, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

const FALLBACK_AUTH: AuthState = {
  isAuthenticated: null,
  token: null,
  user: null,
  signIn: () => {},
  signOut: () => {},
};

export function useAuth() {
  const ctx = useContext(AuthContext);
  return ctx ?? FALLBACK_AUTH;
}

function AuthGateSkeleton() {
  return (
    <div className="min-h-screen p-6 sm:p-8 space-y-4">
      <Skeleton className="h-10 w-56" />
      <Skeleton className="h-4 w-72" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-2xl" />
        ))}
      </div>
    </div>
  );
}

/** Client-side route guard: redirects to the login screen when signed out. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated === false) {
      navigate({ to: "/", replace: true });
    }
  }, [isAuthenticated, navigate]);

  if (isAuthenticated !== true) return <AuthGateSkeleton />;
  return <>{children}</>;
}
