import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";
import { api, errorMessage } from "./api";
import { stars } from "./format";
import type { Status } from "./types";

export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 30_000 });
}

export function useToggleAI() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.post<{ enabled: boolean }>("/api/ai/toggle", { enabled }),
    onMutate: async (enabled) => {
      await qc.cancelQueries({ queryKey: ["status"] });
      const previous = qc.getQueryData<Status>(["status"]);
      if (previous) qc.setQueryData<Status>(["status"], { ...previous, ai: { ...previous.ai, enabled } });
      return { previous };
    },
    onError: (error, _enabled, context) => {
      if (context?.previous) qc.setQueryData(["status"], context.previous);
      toast.error(errorMessage(error));
    },
    onSuccess: (data) => {
      toast.success(data.enabled ? "Réponses automatiques activées" : "Réponses automatiques en pause");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

/** Temps réel : le serveur pousse les nouveaux messages, ventes et changements d'état (SSE). */
export function useRealtime() {
  const qc = useQueryClient();
  const [online, setOnline] = React.useState(true);
  React.useEffect(() => {
    const source = new EventSource("/api/events", { withCredentials: true });
    source.onopen = () => setOnline(true);
    source.onerror = () => setOnline(false); // le navigateur se reconnecte tout seul
    source.onmessage = (raw) => {
      let event: { type: string; chat_id?: number | string; kind?: string; stars?: number };
      try {
        event = JSON.parse(raw.data);
      } catch {
        return;
      }
      const chatId = event.chat_id != null ? String(event.chat_id) : undefined;
      switch (event.type) {
        case "message":
          qc.invalidateQueries({ queryKey: ["messages", chatId] });
          qc.invalidateQueries({ queryKey: ["chats"] });
          qc.invalidateQueries({ queryKey: ["status"] });
          break;
        case "chat":
          qc.invalidateQueries({ queryKey: ["chats"] });
          qc.invalidateQueries({ queryKey: ["chat", chatId] });
          qc.invalidateQueries({ queryKey: ["messages", chatId] });
          qc.invalidateQueries({ queryKey: ["status"] });
          break;
        case "sale":
          for (const key of ["dashboard", "sales", "packs", "chats"]) qc.invalidateQueries({ queryKey: [key] });
          qc.invalidateQueries({ queryKey: ["chat", chatId] });
          if (event.kind === "new") toast.success(`Nouvelle vente : ${stars(event.stars ?? 0)}`);
          if (event.kind === "failed") toast.error("Une livraison a échoué. Consultez le tableau de bord.");
          break;
        case "telegram":
        case "status":
          qc.invalidateQueries({ queryKey: ["status"] });
          qc.invalidateQueries({ queryKey: ["telegram"] });
          qc.invalidateQueries({ queryKey: ["settings"] });
          break;
        case "resync":
          qc.invalidateQueries();
          break;
      }
    };
    return () => source.close();
  }, [qc]);
  return online;
}

export type Theme = "dark" | "light";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = React.useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || "dark");
  const setTheme = React.useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* stockage indisponible : le choix vaut pour cette visite */
    }
    setThemeState(next);
  }, []);
  return [theme, setTheme];
}

export function initTheme() {
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch {
    /* thème sombre par défaut */
  }
}

export function useDocumentTitle(title: string) {
  React.useEffect(() => {
    document.title = `${title} · BusinessAI`;
  }, [title]);
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = React.useState(() => window.matchMedia(query).matches);
  React.useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
