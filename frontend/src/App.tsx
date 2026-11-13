import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import * as React from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ApiError, api, setCsrfToken, setUnauthorizedHandler } from "./lib/api";
import { AIPage } from "./pages/AI";
import { LoginPage, SetupPage } from "./pages/Auth";
import { ConversationsPage } from "./pages/Conversations";
import { DashboardPage } from "./pages/Dashboard";
import { LogsPage } from "./pages/Logs";
import { PacksPage } from "./pages/Packs";
import { SettingsPage } from "./pages/Settings";
import { TelegramPage } from "./pages/Telegram";

interface Me {
  username: string;
  csrf_token: string;
}

function FullScreenLoader() {
  return (
    <div className="flex h-dvh items-center justify-center text-ink-3">
      <Loader2 className="size-6 animate-spin" />
    </div>
  );
}

export function App() {
  const qc = useQueryClient();
  const location = useLocation();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        const data = await api.get<Me>("/api/auth/me", { silent401: true });
        setCsrfToken(data.csrf_token);
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: Infinity,
    retry: 1,
  });
  const setup = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api.get<{ needs_setup: boolean }>("/api/setup/status"),
    enabled: me.data === null,
    staleTime: Infinity,
  });

  React.useEffect(() => {
    // Session expirée pendant l'utilisation : retour à l'écran de connexion.
    setUnauthorizedHandler(() => qc.setQueryData(["me"], null));
  }, [qc]);

  if (me.isPending || (me.data === null && setup.isPending)) return <FullScreenLoader />;
  if (me.isError) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-lg font-semibold">Le serveur ne répond pas</p>
        <p className="max-w-sm text-sm text-ink-2">Vérifiez votre connexion Internet, puis réessayez. Si le problème continue, redémarrez l'application sur votre serveur.</p>
        <button onClick={() => me.refetch()} className="mt-2 text-sm font-medium text-accent hover:underline">
          Réessayer
        </button>
      </div>
    );
  }

  const onAuthenticated = (data: Me) => {
    setCsrfToken(data.csrf_token);
    qc.setQueryData(["me"], data);
    qc.setQueryData(["setup-status"], { needs_setup: false });
  };

  if (!me.data) {
    const needsSetup = setup.data?.needs_setup;
    return (
      <Routes>
        <Route path="/installation" element={needsSetup ? <SetupPage onDone={onAuthenticated} /> : <Navigate to="/connexion" replace />} />
        <Route path="/connexion" element={needsSetup ? <Navigate to="/installation" replace /> : <LoginPage onDone={onAuthenticated} />} />
        <Route path="*" element={<Navigate to={needsSetup ? "/installation" : "/connexion"} replace state={{ from: location.pathname }} />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="conversations/:chatId" element={<ConversationsPage />} />
        <Route path="packs" element={<PacksPage />} />
        <Route path="ia" element={<AIPage />} />
        <Route path="telegram" element={<TelegramPage />} />
        <Route path="parametres" element={<SettingsPage username={me.data.username} />} />
        <Route path="logs" element={<LogsPage />} />
      </Route>
      <Route path="/connexion" element={<Navigate to="/" replace />} />
      <Route path="/installation" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
