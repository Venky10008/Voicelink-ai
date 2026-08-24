import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Heart, GraduationCap, BookOpen, Briefcase, Users, Map, Languages, Check, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PERSONALITY_KEY, writeSelection } from "@/lib/selection";
import { ActiveSelectionBanner } from "@/components/active-selection-banner";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";


export const Route = createFileRoute("/personalities")({ component: PersonalitiesPage });

export type Personality = { id: string; name: string; desc: string; icon: React.ComponentType<{ className?: string }>; color: string };

const defaults: Personality[] = [
  { id: "girlfriend", name: "Girlfriend", desc: "Warm, loving, playful — your partner.", icon: Heart, color: "from-rose-500 to-pink-600" },
  { id: "friend", name: "Friend", desc: "Warm, supportive, always up for a chat.", icon: Heart, color: "from-pink-500 to-rose-500" },
  { id: "mentor", name: "Mentor", desc: "Wise guidance for life and career.", icon: GraduationCap, color: "from-violet-500 to-indigo-500" },
  { id: "teacher", name: "Teacher", desc: "Patient explanations, any subject.", icon: BookOpen, color: "from-sky-500 to-cyan-500" },
  { id: "coach", name: "Interview Coach", desc: "Practice interviews with feedback.", icon: Briefcase, color: "from-amber-500 to-orange-500" },
  { id: "study", name: "Study Partner", desc: "Focus sessions and quick quizzes.", icon: Users, color: "from-emerald-500 to-teal-500" },
  { id: "travel", name: "Travel Guide", desc: "Places, tips, and local secrets.", icon: Map, color: "from-fuchsia-500 to-pink-500" },
  { id: "language", name: "Language Tutor", desc: "Speak and learn any language.", icon: Languages, color: "from-red-500 to-orange-500" },
];

function PersonalitiesPage({
  personalities = defaults,
  loading = false,
}: { personalities?: Personality[]; loading?: boolean }) {
  const navigate = useNavigate();
  const { token } = useAuth();
  const [selected, setSelected] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  // Save the personality to the backend settings, then persist locally.
  const onSelectPersonality = async (id: string) => {
    setSelecting(id);
    try {
      await apiFetch("/profile/settings", {
        method: "PUT",
        body: { personality_id: id },
        token,
      });
      setSelected(id);
      const name = personalities.find((p) => p.id === id)?.name ?? "Personality";
      writeSelection(PERSONALITY_KEY, { id, name });
      setBanner(name);
      toast.success(`${name} selected`, { description: "Opening Text Chat with this personality…" });
      navigate({ to: "/chat" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save this personality.");
    } finally {
      setSelecting(null);
    }
  };

  return (
    <AppShell title="Personalities">
      <div className="p-6 sm:p-8 max-w-6xl mx-auto">
        <div className="mb-6">
          <h1 className="font-display text-3xl font-bold">Choose a Personality</h1>
          <p className="text-muted-foreground mt-1">Shape how VoiceLink talks with you.</p>
          <ActiveSelectionBanner className="mt-4 justify-start" />
        </div>

        {banner && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-primary/40 bg-primary/10 px-4 py-3 text-sm animate-in fade-in slide-in-from-top-1">
            <Sparkles className="h-4 w-4 text-primary shrink-0" />
            <span>
              <span className="font-medium">{banner}</span> is now your active personality — taking you to Text Chat…
            </span>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {loading &&
            Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="glass border rounded-2xl p-5 space-y-3">
                <Skeleton className="h-12 w-12 rounded-xl" />
                <Skeleton className="h-5 w-28" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-9 w-full rounded-md" />
              </div>
            ))}
          {!loading && personalities.map((p, i) => {
            const Icon = p.icon;
            const isSel = selected === p.id;
            return (
              <div key={p.id}
                className={`glass border rounded-2xl p-5 transition-all animate-in fade-in slide-in-from-bottom-2 ${
                  isSel ? "ring-2 ring-primary shadow-glow" : "hover:-translate-y-0.5"
                }`}
                style={{ animationDelay: `${i * 50}ms`, animationFillMode: "backwards" }}
              >
                <div className={`h-12 w-12 rounded-xl bg-gradient-to-br ${p.color} flex items-center justify-center mb-4 shadow-lg`}>
                  <Icon className="h-6 w-6 text-white" />
                </div>
                <div className="font-display font-semibold text-lg">{p.name}</div>
                <p className="text-sm text-muted-foreground mt-1 mb-4">{p.desc}</p>
                <Button
                  onClick={() => onSelectPersonality(p.id)}
                  disabled={selecting === p.id}
                  className={`w-full ${isSel ? "bg-gradient-primary text-primary-foreground shadow-glow" : ""}`}
                  variant={isSel ? "default" : "outline"}
                >
                  {selecting === p.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : isSel ? (
                    <><Check className="h-4 w-4 mr-1" /> Selected</>
                  ) : (
                    "Select"
                  )}
                </Button>
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
