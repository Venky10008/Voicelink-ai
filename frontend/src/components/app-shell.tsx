import { Link, useRouterState } from "@tanstack/react-router";
import { memo, type ReactNode } from "react";
import {
  MessageSquare,
  Phone,
  Library,
  Sparkles,
  Shield,
  User,
  History,
  LayoutDashboard,
  Moon,
  Sun,
  Menu,
} from "lucide-react";
import { useTheme } from "@/lib/theme";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { RequireAuth } from "@/lib/auth";

const nav = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/call", label: "Voice Call", icon: Phone },
  { to: "/voices", label: "Voice Library", icon: Library },
  { to: "/personalities", label: "Personalities", icon: Sparkles },
  { to: "/permissions", label: "My Voice", icon: Shield },
  { to: "/history", label: "History", icon: History },
  { to: "/profile", label: "Profile", icon: User },
];

const NavList = memo(function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav className="flex flex-col gap-1 p-3">
      <Link to="/dashboard" onClick={onNavigate} className="flex items-center gap-2 px-3 py-4 mb-2">
        <div className="h-9 w-9 rounded-xl bg-gradient-primary shadow-glow flex items-center justify-center">
          <Sparkles className="h-5 w-5 text-primary-foreground" />
        </div>
        <div>
          <div className="font-display font-bold text-lg leading-none">VoiceLink</div>
          <div className="text-xs text-muted-foreground">AI Companion</div>
        </div>
      </Link>
      {nav.map((item) => {
        const Icon = item.icon;
        const active = pathname === item.to;
        return (
          <Link
            key={item.to}
            to={item.to}
            preload="intent"
            onClick={onNavigate}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150 ${
              active
                ? "bg-gradient-primary text-primary-foreground shadow-glow"
                : "text-muted-foreground hover:text-foreground hover:bg-accent"
            }`}
          >
            <Icon className="h-4 w-4" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
});


export function AppShell({ children, title }: { children: ReactNode; title?: string }) {
  const { theme, toggle } = useTheme();

  return (
    <div className="min-h-screen flex w-full">
      <aside className="hidden lg:flex w-64 border-r border-border/50 glass flex-col shrink-0">
        <NavList />
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 border-b border-border/50 glass flex items-center justify-between px-4 sm:px-6 sticky top-0 z-20">
          <div className="flex items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="lg:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="p-0 w-72">
                <NavList />
              </SheetContent>
            </Sheet>
            {title && <h1 className="font-display font-semibold text-lg">{title}</h1>}
          </div>
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
        </header>

        <main className="flex-1 min-w-0">
          <RequireAuth>{children}</RequireAuth>
        </main>
      </div>
    </div>
  );
}
