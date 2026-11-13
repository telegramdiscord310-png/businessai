import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  MoreHorizontal,
  Package,
  ScrollText,
  Send,
  Settings,
  Sparkles,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { useRealtime, useStatus, useToggleAI } from "@/lib/hooks";
import type { Status } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Switch } from "./ui/form";
import { Tooltip } from "./ui/tooltip";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/conversations", label: "Conversations", icon: MessagesSquare },
  { to: "/packs", label: "Packs", icon: Package },
  { to: "/ia", label: "IA", icon: Sparkles },
  { to: "/telegram", label: "Telegram", icon: Send },
  { to: "/parametres", label: "Paramètres", icon: Settings },
  { to: "/logs", label: "Logs", icon: ScrollText },
];

const TITLES: [string, string][] = [
  ["/conversations", "Conversations"],
  ["/packs", "Packs"],
  ["/ia", "IA"],
  ["/telegram", "Telegram"],
  ["/parametres", "Paramètres"],
  ["/logs", "Logs"],
  ["/", "Dashboard"],
];

function useLogout() {
  const qc = useQueryClient();
  return async () => {
    try {
      await api.post("/api/auth/logout");
    } catch (error) {
      toast.error(errorMessage(error));
    }
    qc.clear();
    window.location.href = "/connexion";
  };
}

function CountBadge({ count, className }: { count: number; className?: string }) {
  if (!count) return null;
  return (
    <span className={cn("tabular flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-fg", className)}>
      {count > 99 ? "99+" : count}
    </span>
  );
}

function Sidebar({ status }: { status?: Status }) {
  const logout = useLogout();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface lg:flex">
      <Link to="/" className="flex h-16 items-center gap-2.5 px-5">
        <span className="flex size-8 items-center justify-center rounded-xl bg-accent text-accent-fg">
          <Send className="size-4 -translate-x-px translate-y-px" />
        </span>
        <span className="text-[15px] font-semibold tracking-tight">BusinessAI</span>
      </Link>
      <nav className="flex-1 space-y-0.5 px-3 pt-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "group flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors duration-150",
                isActive ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
              )
            }
          >
            <item.icon className="size-[18px]" />
            <span className="flex-1">{item.label}</span>
            {item.to === "/conversations" && <CountBadge count={status?.unread ?? 0} />}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-line p-3">
        <button
          onClick={logout}
          className="flex h-10 w-full items-center gap-3 rounded-xl px-3 text-sm font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <LogOut className="size-[18px]" />
          Se déconnecter
        </button>
      </div>
    </aside>
  );
}

function BottomNav({ status }: { status?: Status }) {
  const logout = useLogout();
  const location = useLocation();
  const primary = NAV.slice(0, 4);
  const more = NAV.slice(4);
  const moreActive = more.some((item) => location.pathname.startsWith(item.to));
  const itemClass = (active: boolean) =>
    cn("relative flex flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors", active ? "text-accent" : "text-ink-3");
  return (
    <nav className="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur lg:hidden">
      <div className="flex h-16">
        {primary.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => itemClass(isActive)}>
            <span className="relative">
              <item.icon className="size-[22px]" />
              {item.to === "/conversations" && <CountBadge count={status?.unread ?? 0} className="absolute -top-1.5 -right-3 h-4 min-w-4 px-1 text-[10px]" />}
            </span>
            {item.label}
          </NavLink>
        ))}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className={cn(itemClass(moreActive), "focus:outline-none")}>
            <MoreHorizontal className="size-[22px]" />
            Plus
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              side="top"
              align="end"
              sideOffset={10}
              className="z-50 mr-2 w-56 animate-fade rounded-2xl border border-line bg-surface p-1.5 shadow-pop"
            >
              {more.map((item) => (
                <DropdownMenu.Item key={item.to} asChild>
                  <Link
                    to={item.to}
                    className={cn(
                      "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium outline-none data-[highlighted]:bg-surface-2",
                      location.pathname.startsWith(item.to) ? "text-accent" : "text-ink",
                    )}
                  >
                    <item.icon className="size-[18px]" />
                    {item.label}
                  </Link>
                </DropdownMenu.Item>
              ))}
              <DropdownMenu.Separator className="my-1.5 h-px bg-line" />
              <DropdownMenu.Item
                onSelect={logout}
                className="flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium text-ink-2 outline-none data-[highlighted]:bg-surface-2"
              >
                <LogOut className="size-[18px]" />
                Se déconnecter
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </nav>
  );
}

const TG_LABEL: Record<string, { label: string; short: string; tone: string }> = {
  connected: { label: "Telegram connecté", short: "Connecté", tone: "bg-success" },
  connecting: { label: "Telegram : connexion…", short: "Connexion…", tone: "bg-warning animate-pulse" },
  code_sent: { label: "Telegram : code attendu", short: "Code attendu", tone: "bg-warning" },
  password_needed: { label: "Telegram : mot de passe attendu", short: "À finir", tone: "bg-warning" },
  error: { label: "Telegram : erreur", short: "Erreur", tone: "bg-danger" },
  disconnected: { label: "Telegram déconnecté", short: "Déconnecté", tone: "bg-ink-3" },
};

/** Indicateur permanent : état de Telegram et de l'IA, avec l'interrupteur global. */
function StatusBar({ status }: { status?: Status }) {
  const toggle = useToggleAI();
  if (!status) return <div className="skeleton h-9 w-56 rounded-full" />;
  const tg = TG_LABEL[status.telegram.status] ?? TG_LABEL.disconnected;
  const aiOn = status.ai.enabled;
  const id = "ai-global-switch";
  return (
    <div className="flex items-center gap-2">
      <Tooltip side="bottom" label={status.telegram.error || (status.telegram.status === "connected" ? `Compte : ${status.telegram.name ?? ""}` : "Ouvrir la page Telegram")}>
        <Link
          to="/telegram"
          className="flex h-9 items-center gap-2 rounded-full border border-line bg-surface px-3 text-[13px] font-medium text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <span className={cn("size-2 shrink-0 rounded-full", tg.tone)} />
          <span className="hidden sm:inline">{tg.label}</span>
          <span className="sm:hidden">{tg.short}</span>
        </Link>
      </Tooltip>
      <div className="flex h-9 items-center gap-2 rounded-full border border-line bg-surface pr-1.5 pl-3">
        <Tooltip
          side="bottom"
          label={
            aiOn
              ? status.ai.draft_mode
                ? "Mode brouillon : l'IA rédige, vous validez avant l'envoi."
                : "L'IA répond automatiquement aux messages privés."
              : "L'IA ne répond à personne tant qu'elle est en pause."
          }
        >
          <label htmlFor={id} className="flex cursor-pointer items-center gap-1.5 text-[13px] font-medium text-ink-2">
            <Bot className={cn("size-4", aiOn ? "text-accent" : "text-ink-3")} />
            <span className="hidden sm:inline">{aiOn ? (status.ai.draft_mode ? "IA en mode brouillon" : "IA active") : "IA en pause"}</span>
            <span className="sm:hidden">{aiOn ? "IA active" : "IA en pause"}</span>
          </label>
        </Tooltip>
        <Switch id={id} checked={aiOn} onCheckedChange={(v) => toggle.mutate(v)} aria-label="Activer ou mettre en pause les réponses automatiques" />
      </div>
    </div>
  );
}

export function AppShell() {
  const { data: status } = useStatus();
  const online = useRealtime();
  const location = useLocation();
  const title = TITLES.find(([prefix]) => (prefix === "/" ? true : location.pathname.startsWith(prefix)))?.[1] ?? "BusinessAI";
  // La page Conversations occupe tout l'écran (deux colonnes façon messagerie).
  const fullBleed = location.pathname.startsWith("/conversations");
  const inThread = /^\/conversations\/.+/.test(location.pathname);

  React.useEffect(() => {
    document.title = `${title} · BusinessAI`;
  }, [title]);

  return (
    <div className="flex h-dvh flex-col lg:pl-60">
      <Sidebar status={status} />
      <header className={cn("z-20 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur sm:px-6 lg:px-8")}>
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-lg font-semibold tracking-tight sm:text-xl">{title}</h1>
          {!online && (
            <Tooltip side="bottom" label="Connexion temps réel interrompue. Reconnexion automatique en cours…">
              <span className="flex items-center gap-1.5 rounded-full bg-warning-soft px-2 py-1 text-xs font-medium text-warning">
                <WifiOff className="size-3.5" />
                <span className="hidden md:inline">Hors ligne</span>
              </span>
            </Tooltip>
          )}
        </div>
        <StatusBar status={status} />
      </header>
      <main className={cn("min-h-0 flex-1", fullBleed ? "overflow-hidden" : "scroll-thin overflow-y-auto", !inThread && "max-lg:pb-16")}>
        {fullBleed ? (
          <Outlet />
        ) : (
          <div className="mx-auto w-full max-w-[1320px] animate-in px-4 py-6 sm:px-6 lg:px-8 lg:py-8" key={location.pathname}>
            <Outlet />
          </div>
        )}
      </main>
      {!inThread && <BottomNav status={status} />}
    </div>
  );
}
