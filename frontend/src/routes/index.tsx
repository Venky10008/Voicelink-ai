import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Sparkles, Loader2, Mail, Lock, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth";
import {
  firebaseConfigError,
  firebaseErrorMessage,
  isFirebaseConfigured,
  resetPasswordErrorMessage,
  sendPasswordResetEmail,
  signInWithEmail,
  signUpWithEmail,
} from "@/lib/firebase";

export const Route = createFileRoute("/")({ component: AuthPage });

function AuthPage() {
  const navigate = useNavigate();
  const { isAuthenticated, signIn } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetSending, setResetSending] = useState(false);
  const [resetSent, setResetSent] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  // Already signed in → skip the login screen
  useEffect(() => {
    if (isAuthenticated === true) navigate({ to: "/dashboard", replace: true });
  }, [isAuthenticated, navigate]);

  // Wire to Firebase Authentication
  const onLogin = async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      if (!isFirebaseConfigured()) throw new Error(firebaseConfigError());
      const result = await signInWithEmail(email, password);
      signIn(result.idToken, { name: result.name, email: result.email });
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(firebaseErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  const onSignup = async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      if (!isFirebaseConfigured()) throw new Error(firebaseConfigError());
      const result = await signUpWithEmail(email, password);
      signIn(result.idToken, { name: result.name, email: result.email });
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(firebaseErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) { setError("Please fill both fields."); return; }
    mode === "login" ? onLogin(email, password) : onSignup(email, password);
  };

  // Wire to Firebase password reset (sends a reset link to the email).
  const onSendReset = async () => {
    const target = resetEmail.trim();
    if (!target) { setResetError("Enter your email first."); return; }
    setResetSending(true);
    setResetError(null);
    setResetSent(false);
    try {
      if (!isFirebaseConfigured()) throw new Error(firebaseConfigError());
      await sendPasswordResetEmail(target);
      setResetSent(true);
    } catch (err) {
      setResetError(resetPasswordErrorMessage(err));
    } finally {
      setResetSending(false);
    }
  };


  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute inset-0 -z-10">
        <div className="absolute top-1/4 left-1/4 h-96 w-96 rounded-full bg-primary/30 blur-[120px] animate-float-slow" />
        <div className="absolute bottom-1/4 right-1/4 h-96 w-96 rounded-full bg-primary-glow/30 blur-[120px] animate-float-slow" style={{ animationDelay: "1.5s" }} />
      </div>

      <div className="w-full max-w-md glass rounded-3xl border shadow-elegant p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="flex flex-col items-center text-center mb-8">
          <div className="h-14 w-14 rounded-2xl bg-gradient-primary shadow-glow flex items-center justify-center mb-4 animate-float-slow">
            <Sparkles className="h-7 w-7 text-primary-foreground" />
          </div>
          <h1 className="font-display text-3xl font-bold">VoiceLink AI</h1>
          <p className="text-sm text-muted-foreground mt-1">Your emotion-aware voice companion</p>
        </div>

        <div className="flex bg-muted rounded-lg p-1 mb-6">
          {(["login", "signup"] as const).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError(null); }}
              className={`flex-1 py-2 text-sm font-medium rounded-md transition-all ${
                mode === m ? "bg-background shadow-sm text-foreground" : "text-muted-foreground"
              }`}
            >
              {m === "login" ? "Log in" : "Sign up"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input id="email" type="email" placeholder="you@voicelink.ai" className="pl-9" disabled={loading}
                value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input id="password" type="password" placeholder="••••••••" className="pl-9" disabled={loading}
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2 animate-in fade-in">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          <Button type="submit" disabled={loading} className="w-full h-11 bg-gradient-primary text-primary-foreground hover:opacity-90 shadow-glow font-medium">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
          </Button>

          <div className="text-center">
            <button
              type="button"
              onClick={() => { setResetOpen(true); setResetEmail(email); setResetSent(false); setResetError(null); }}
              className="text-sm text-muted-foreground hover:text-primary transition-colors"
            >
              Forgot password?
            </button>
          </div>
        </form>

        <p className="text-xs text-center text-muted-foreground mt-6">
          By continuing, you agree to VoiceLink's Terms and Privacy Policy.
        </p>
      </div>

      <Dialog open={resetOpen} onOpenChange={(v) => { setResetOpen(v); if (!v) { setResetSent(false); setResetError(null); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Reset your password</DialogTitle>
            <DialogDescription>
              We'll email you a secure link to create a new password.
            </DialogDescription>
          </DialogHeader>

          {resetSent ? (
            <div className="flex items-start gap-3 rounded-lg border border-primary/40 bg-primary/10 px-4 py-3 text-sm animate-in fade-in">
              <Mail className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span>
                Check your inbox at <span className="font-medium">{resetEmail.trim()}</span>.
                The link expires shortly — if you don't see it, check spam.
              </span>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reset-email">Email</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="reset-email"
                    type="email"
                    placeholder="you@voicelink.ai"
                    className="pl-9"
                    value={resetEmail}
                    onChange={(e) => setResetEmail(e.target.value)}
                    disabled={resetSending}
                  />
                </div>
              </div>

              {resetError && (
                <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2 animate-in fade-in">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {resetError}
                </div>
              )}

              <Button
                onClick={onSendReset}
                disabled={resetSending || !resetEmail.trim()}
                className="w-full bg-gradient-primary text-primary-foreground hover:opacity-90 shadow-glow font-medium"
              >
                {resetSending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send reset link"}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
