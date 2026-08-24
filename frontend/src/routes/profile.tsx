import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { LogOut, Moon, Sun, Mail, User as UserIcon, Loader2, Brain, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useTheme } from "@/lib/theme";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { signOutFirebase } from "@/lib/firebase";

export const Route = createFileRoute("/profile")({ component: ProfilePage });

type ProfileResponse = {
  name: string | null;
  email: string | null;
  settings: {
    voice_id: string | null;
    speed: number;
    pitch: number;
    personality_id: string | null;
    updated_at: string;
  };
};

function ProfilePage({
  user: initialUser,
  loading: initialLoading = false,
}: { user?: { name: string; email: string }; loading?: boolean }) {
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const { signOut, token } = useAuth();
  const [user, setUser] = useState(initialUser ?? { name: "Your Name", email: "you@voicelink.ai" });
  const [name, setName] = useState(user.name);
  const [loading, setLoading] = useState(initialLoading);
  const [saving, setSaving] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [memories, setMemories] = useState<{ key: string; value: string }[]>([]);
  const [memoryInput, setMemoryInput] = useState("");
  const [memoryBusy, setMemoryBusy] = useState(false);

  // Load profile info (Firebase email + saved name/settings) from the backend.
  useEffect(() => {
    if (initialUser) return; // data provided externally — don't fetch
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await apiFetch<ProfileResponse>("/profile", { token });
        if (!cancelled) {
          const nextUser = {
            name: data.name ?? "Your Name",
            email: data.email ?? "you@voicelink.ai",
          };
          setUser(nextUser);
          setName(nextUser.name);
        }
      } catch (err) {
        if (!cancelled) toast.error(err instanceof Error ? err.message : "Could not load profile.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialUser, token]);

  // Load everything VoiceLink remembers about the user.
  useEffect(() => {
    if (initialUser) return;
    if (loading) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<{
          memories: { key: string; value: string; updated_at: string }[];
        }>("/memory", { token });
        if (!cancelled) setMemories(data.memories);
      } catch {
        /* best-effort — memory card just starts empty */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialUser, loading, token]);

  const onAddMemory = async () => {
    const value = memoryInput.trim();
    if (!value) return;
    setMemoryBusy(true);
    try {
      const data = await apiFetch<{ key: string; value: string }>("/memory", {
        method: "POST",
        body: { key: `fact-${Date.now()}`, value },
        token,
      });
      setMemories((m) => [...m, data]);
      setMemoryInput("");
      toast.success("Remembered.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save this memory.");
    } finally {
      setMemoryBusy(false);
    }
  };

  const onDeleteMemory = async (key: string) => {
    try {
      await apiFetch(`/memory?key=${encodeURIComponent(key)}`, {
        method: "DELETE",
        token,
      });
      setMemories((m) => m.filter((mem) => mem.key !== key));
      toast.success("Forgotten.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete this memory.");
    }
  };

  // Save the display name to the backend (email is read-only from Firebase).
  const onSaveProfile = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      toast.error("Name cannot be empty.");
      return;
    }
    setSaving(true);
    try {
      await apiFetch("/profile", { method: "PUT", body: { name: trimmed }, token });
      setUser((u) => ({ ...u, name: trimmed }));
      toast.success("Profile updated.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update profile.");
    } finally {
      setSaving(false);
    }
  };
  const onLogout = async () => {
    setLoggingOut(true);
    try {
      await signOutFirebase();
    } catch {
      /* sign out locally even if the Firebase call fails */
    }
    signOut();
    navigate({ to: "/", replace: true });
  };

  if (loading) {
    return (
      <AppShell title="Profile">
        <div className="p-6 sm:p-8 max-w-2xl mx-auto space-y-6">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass border rounded-2xl p-6 space-y-4">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-2/3" />
            </div>
          ))}
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Profile">
      <div className="p-6 sm:p-8 max-w-2xl mx-auto space-y-6">
        <div className="glass border rounded-2xl p-6">
          <div className="flex items-center gap-4 mb-6">
            <Avatar className="h-16 w-16">
              <AvatarFallback className="bg-gradient-primary text-primary-foreground text-xl">
                {user.name[0]}
              </AvatarFallback>
            </Avatar>
            <div>
              <div className="font-display text-xl font-semibold">{user.name}</div>
              <div className="text-sm text-muted-foreground">{user.email}</div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <div className="relative">
                <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} className="pl-9" disabled={saving} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="email" defaultValue={user.email} className="pl-9" disabled={saving} />
              </div>
            </div>
            <Button onClick={onSaveProfile} disabled={saving || !name.trim()}
              className="bg-gradient-primary text-primary-foreground shadow-glow">
              {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>

        <div className="glass border rounded-2xl p-6">
          <h2 className="font-display font-semibold text-lg mb-1 flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" /> What I remember
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Facts you add here help me talk with you naturally — and I also save
            important things you tell me automatically.
          </p>

          <div className="flex gap-2 mb-4">
            <Input
              value={memoryInput}
              onChange={(e) => setMemoryInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onAddMemory(); } }}
              placeholder="e.g. I love reading sci-fi books"
              disabled={memoryBusy}
            />
            <Button
              onClick={onAddMemory}
              disabled={memoryBusy || !memoryInput.trim()}
              className="shrink-0 gap-1.5 bg-gradient-primary text-primary-foreground shadow-glow"
            >
              {memoryBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Add
            </Button>
          </div>

          {memories.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing remembered yet. Add a fact above.</p>
          ) : (
            <ul className="space-y-2">
              {memories.map((mem) => (
                <li key={mem.key} className="flex items-center justify-between gap-3 rounded-lg border bg-card/50 px-3 py-2.5">
                  <div className="flex items-center gap-2 min-w-0">
                    {mem.key.startsWith("auto-") && (
                      <Badge variant="secondary" className="text-[10px] shrink-0" title="Saved automatically from our conversations">
                        auto
                      </Badge>
                    )}
                    <span className="text-sm">{mem.value}</span>
                  </div>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 shrink-0 text-destructive hover:text-destructive"
                    onClick={() => onDeleteMemory(mem.key)}
                    aria-label="Delete this memory"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="glass border rounded-2xl p-6">
          <h2 className="font-display font-semibold text-lg mb-4">Appearance</h2>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {theme === "dark" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
              <div>
                <div className="text-sm font-medium">Dark mode</div>
                <div className="text-xs text-muted-foreground">Switch between light and dark themes.</div>
              </div>
            </div>
            <Switch checked={theme === "dark"} onCheckedChange={toggle} />
          </div>
        </div>

        <div className="glass border rounded-2xl p-6">
          <h2 className="font-display font-semibold text-lg mb-4">Account</h2>
          <Separator className="mb-4" />
          <Button variant="destructive" onClick={onLogout} disabled={loggingOut} className="gap-2">
            {loggingOut ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />} Log out
          </Button>
        </div>

      </div>
    </AppShell>
  );
}
