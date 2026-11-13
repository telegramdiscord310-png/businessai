import { useMutation } from "@tanstack/react-query";
import { KeyRound, Send, ShieldCheck } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { api, errorMessage } from "@/lib/api";
import { useDocumentTitle } from "@/lib/hooks";

interface Me {
  username: string;
  csrf_token: string;
}

function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-[400px] animate-in">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="mb-5 flex size-12 items-center justify-center rounded-2xl bg-accent text-accent-fg">
            <Send className="size-5 -translate-x-px translate-y-px" />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-2">{subtitle}</p>
        </div>
        <div className="rounded-3xl border border-line bg-surface p-6 sm:p-7">{children}</div>
      </div>
    </div>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] leading-snug text-ink">
      {message}
    </div>
  );
}

export function LoginPage({ onDone }: { onDone: (me: Me) => void }) {
  useDocumentTitle("Connexion");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const login = useMutation({
    mutationFn: () => api.post<Me>("/api/auth/login", { username: username.trim(), password }, { silent401: true }),
    onSuccess: onDone,
  });
  return (
    <AuthLayout title="Connexion" subtitle="Accédez à votre espace BusinessAI.">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
      >
        <Field label="Identifiant" htmlFor="username">
          <Input id="username" autoComplete="username" autoFocus required value={username} onChange={(e) => setUsername(e.target.value)} />
        </Field>
        <Field label="Mot de passe" htmlFor="password">
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <FormError message={login.isError ? errorMessage(login.error) : null} />
        <Button type="submit" size="lg" className="w-full" loading={login.isPending}>
          Se connecter
        </Button>
      </form>
    </AuthLayout>
  );
}

export function SetupPage({ onDone }: { onDone: (me: Me) => void }) {
  useDocumentTitle("Installation");
  const [form, setForm] = React.useState({ setup_token: "", username: "", password: "", confirm: "" });
  const [localError, setLocalError] = React.useState<string | null>(null);
  const setup = useMutation({
    mutationFn: () => api.post<Me>("/api/setup", { setup_token: form.setup_token.trim(), username: form.username.trim(), password: form.password }, { silent401: true }),
    onSuccess: onDone,
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));
  return (
    <AuthLayout title="Bienvenue" subtitle="Créez votre compte administrateur. Cette page disparaît ensuite.">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (form.password !== form.confirm) return setLocalError("Les deux mots de passe ne sont pas identiques.");
          if (form.password.length < 10) return setLocalError("Le mot de passe doit contenir au moins 10 caractères.");
          setLocalError(null);
          setup.mutate();
        }}
      >
        <Field label="Code d'installation" htmlFor="setup_token" hint="C'est la valeur de SETUP_TOKEN dans le fichier .env de votre serveur. Il prouve que c'est bien vous.">
          <div className="relative">
            <KeyRound className="pointer-events-none absolute top-3 left-3.5 size-4 text-ink-3" />
            <Input id="setup_token" className="pl-10" required autoFocus autoComplete="off" value={form.setup_token} onChange={set("setup_token")} />
          </div>
        </Field>
        <Field label="Identifiant" htmlFor="username">
          <Input id="username" required minLength={3} autoComplete="username" value={form.username} onChange={set("username")} />
        </Field>
        <Field label="Mot de passe" htmlFor="password" hint="10 caractères minimum. Une phrase facile à retenir fait très bien l'affaire.">
          <Input id="password" type="password" required autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirmez le mot de passe" htmlFor="confirm">
          <Input id="confirm" type="password" required autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </Field>
        <FormError message={localError ?? (setup.isError ? errorMessage(setup.error) : null)} />
        <Button type="submit" size="lg" className="w-full" loading={setup.isPending}>
          <ShieldCheck />
          Créer mon compte
        </Button>
      </form>
    </AuthLayout>
  );
}
