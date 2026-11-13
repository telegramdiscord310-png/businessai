import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { App } from "./App";
import { TooltipProvider } from "./components/ui/tooltip";
import "./index.css";
import { ApiError } from "./lib/api";
import { initTheme } from "./lib/hooks";

initTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TooltipProvider delayDuration={250}>
          <App />
        </TooltipProvider>
      </BrowserRouter>
      <Toaster
        position="top-center"
        theme="system"
        toastOptions={{
          style: { background: "var(--surface-3)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: "14px", fontFamily: "inherit" },
        }}
      />
    </QueryClientProvider>
  </StrictMode>,
);
