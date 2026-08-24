import { createFileRoute, Link } from "@tanstack/react-router";
import { MessageSquare, Phone, Library, Sparkles, Shield, User, History, ArrowRight } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/dashboard")({ component: Dashboard });

const tiles = [
  { to: "/chat", label: "Text Chat", desc: "Type-first conversations", icon: MessageSquare, color: "from-fuchsia-500 to-pink-500" },
  { to: "/call", label: "Voice Call", desc: "Talk in real time", icon: Phone, color: "from-violet-500 to-indigo-500" },
  { to: "/voices", label: "Voice Library", desc: "Choose how AI sounds", icon: Library, color: "from-sky-500 to-cyan-500" },
  { to: "/personalities", label: "Personalities", desc: "Friend, mentor, coach…", icon: Sparkles, color: "from-amber-500 to-orange-500" },
  { to: "/permissions", label: "Permissions", desc: "Share voice safely", icon: Shield, color: "from-emerald-500 to-teal-500" },
  { to: "/history", label: "History", desc: "Past conversations", icon: History, color: "from-rose-500 to-red-500" },
  { to: "/profile", label: "Profile", desc: "Account & settings", icon: User, color: "from-slate-500 to-zinc-500" },
];

function Dashboard({ userName: initialUserName }: { userName?: string }) {
  const { user } = useAuth();
  const userName =
    initialUserName ??
    user?.name?.split(" ")[0] ??
    user?.email?.split("@")[0] ??
    "there";
  return (
    <AppShell title="Dashboard">
      <div className="p-6 sm:p-8 max-w-6xl mx-auto">
        <div className="mb-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
          <p className="text-sm text-muted-foreground">Welcome back</p>
          <h1 className="font-display text-3xl sm:text-4xl font-bold mt-1">
            Hey <span className="bg-gradient-primary bg-clip-text text-transparent">{userName}</span> 👋
          </h1>
          <p className="text-muted-foreground mt-2">What would you like to do today?</p>
        </div>

        <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tiles.map((t, i) => {
            const Icon = t.icon;
            return (
              <Link
                key={t.to}
                to={t.to}
                className="group glass border rounded-2xl p-5 hover:shadow-elegant hover:-translate-y-1 transition-all duration-300 animate-in fade-in slide-in-from-bottom-4"
                style={{ animationDelay: `${i * 60}ms`, animationFillMode: "backwards" }}
              >
                <div className={`h-12 w-12 rounded-xl bg-gradient-to-br ${t.color} flex items-center justify-center mb-4 shadow-lg group-hover:scale-110 transition-transform`}>
                  <Icon className="h-6 w-6 text-white" />
                </div>
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-display font-semibold text-lg">{t.label}</div>
                    <div className="text-sm text-muted-foreground mt-0.5">{t.desc}</div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary group-hover:translate-x-1 transition-all mt-1" />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
