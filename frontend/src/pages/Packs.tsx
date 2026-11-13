import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, ImageIcon, Link2, Package, Pencil, Plus, Star, Trash2, Type, Upload, X } from "lucide-react";
import * as React from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, SwitchRow, Textarea } from "@/components/ui/form";
import { api, errorMessage } from "@/lib/api";
import { euros, fileSize, number, stars } from "@/lib/format";
import type { AppSettings, Pack, PackFile } from "@/lib/types";
import { cn } from "@/lib/utils";

const isImage = (f: PackFile) => (f.mime ?? "").startsWith("image/");

function PackCover({ pack }: { pack: Pack }) {
  const image = pack.files.find(isImage);
  return (
    <div className="relative aspect-[16/9] overflow-hidden rounded-t-2xl bg-surface-2">
      {image ? (
        <img src={`/api/packs/${pack.id}/files/${image.id}`} alt="" loading="lazy" className={cn("size-full object-cover", !pack.active && "opacity-50 grayscale")} />
      ) : (
        <div className="flex size-full items-center justify-center bg-[radial-gradient(circle_at_30%_20%,var(--accent-soft),transparent_60%)]">
          <Package className={cn("size-10", pack.active ? "text-accent/70" : "text-ink-3")} strokeWidth={1.5} />
        </div>
      )}
      <div className="absolute top-3 left-3">{pack.active ? <Badge tone="success" className="backdrop-blur">En vente</Badge> : <Badge className="bg-surface-3/90 backdrop-blur">Hors vente</Badge>}</div>
    </div>
  );
}

function PackCard({ pack, rate, onEdit, onDelete }: { pack: Pack; rate: number; onEdit: () => void; onDelete: () => void }) {
  const contents = [
    pack.files.length > 0 && { icon: <FileText />, label: `${pack.files.length} ${pack.files.length > 1 ? "fichiers" : "fichier"}` },
    pack.content_text && { icon: <Type />, label: "Texte" },
    pack.content_link && { icon: <Link2 />, label: "Lien" },
  ].filter(Boolean) as { icon: React.ReactNode; label: string }[];
  return (
    <Card className="group flex flex-col transition-colors duration-150 hover:border-line-strong">
      <PackCover pack={pack} />
      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-[15px] leading-snug font-semibold">{pack.name}</h3>
          <div className="shrink-0 text-right">
            <p className="tabular flex items-center justify-end gap-1 text-[15px] font-semibold">
              {number(pack.price_stars)}
              <Star className="size-3.5 fill-warning text-warning" />
            </p>
            <p className="tabular text-xs text-ink-3">≈ {euros(pack.price_stars * rate)}</p>
          </div>
        </div>
        <p className="mt-1.5 line-clamp-2 min-h-[2.5rem] text-[13px] leading-snug text-ink-3">{pack.description || "Pas de description."}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {contents.length ? (
            contents.map((c) => (
              <Badge key={c.label}>
                {c.icon}
                {c.label}
              </Badge>
            ))
          ) : (
            <Badge tone="warning">Aucun contenu à livrer</Badge>
          )}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-line pt-3.5">
          <p className="text-[13px] text-ink-2">
            <span className="tabular font-semibold text-ink">{number(pack.sales_count)}</span> {pack.sales_count > 1 ? "ventes" : "vente"}
            {pack.sales_stars > 0 && <span className="tabular text-ink-3"> · {euros(pack.sales_stars * rate)}</span>}
          </p>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={onEdit}>
              <Pencil />
              Modifier
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label={`Supprimer ${pack.name}`} className="hover:bg-danger-soft hover:text-danger" onClick={onDelete}>
              <Trash2 />
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

interface FormState {
  name: string;
  description: string;
  price_stars: string;
  content_text: string;
  content_link: string;
  active: boolean;
}

function PackDialog({ pack, rate, open, onClose }: { pack: Pack | null; rate: number; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const fileInput = React.useRef<HTMLInputElement>(null);
  const [form, setForm] = React.useState<FormState>({ name: "", description: "", price_stars: "", content_text: "", content_link: "", active: true });
  const [existing, setExisting] = React.useState<PackFile[]>([]);
  const [removed, setRemoved] = React.useState<number[]>([]);
  const [added, setAdded] = React.useState<File[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [dragging, setDragging] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setForm(
      pack
        ? { name: pack.name, description: pack.description, price_stars: String(pack.price_stars), content_text: pack.content_text, content_link: pack.content_link, active: pack.active }
        : { name: "", description: "", price_stars: "", content_text: "", content_link: "", active: true },
    );
    setExisting(pack?.files ?? []);
    setRemoved([]);
    setAdded([]);
    setError(null);
  }, [open, pack]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const keptFiles = existing.filter((f) => !removed.includes(f.id));
  const hasContent = !!form.content_text.trim() || !!form.content_link.trim() || keptFiles.length + added.length > 0;
  const price = Number(form.price_stars);

  const save = useMutation({
    mutationFn: async () => {
      const body = { name: form.name, description: form.description, price_stars: price, content_text: form.content_text, content_link: form.content_link };
      // 1. Enregistre le pack hors vente, 2. met à jour ses fichiers, 3. le met en vente si demandé.
      const saved = pack ? await api.put<Pack>(`/api/packs/${pack.id}`, { ...body, active: false }) : await api.post<Pack>("/api/packs", { ...body, active: false });
      for (const id of removed) await api.delete(`/api/packs/${saved.id}/files/${id}`);
      if (added.length) {
        const data = new FormData();
        added.forEach((file) => data.append("files", file));
        await api.upload(`/api/packs/${saved.id}/files`, data);
      }
      if (form.active) await api.put(`/api/packs/${saved.id}`, { ...body, active: true });
      return saved;
    },
    onSuccess: () => {
      toast.success(pack ? "Pack enregistré" : form.active ? "Pack créé et mis en vente" : "Pack créé (hors vente)");
      qc.invalidateQueries({ queryKey: ["packs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      onClose();
    },
    onError: (e) => {
      setError(errorMessage(e));
      qc.invalidateQueries({ queryKey: ["packs"] });
    },
  });

  const addFiles = (files: FileList | null) => {
    if (files?.length) setAdded((list) => [...list, ...Array.from(files)]);
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return setError("Donnez un nom à votre pack.");
    if (!Number.isInteger(price) || price < 1) return setError("Indiquez un prix en Stars (nombre entier, 1 minimum).");
    if (form.active && !hasContent) return setError("Ajoutez un contenu à livrer (fichier, texte ou lien) avant de mettre ce pack en vente.");
    setError(null);
    save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && !save.isPending && onClose()}
      size="lg"
      title={pack ? "Modifier le pack" : "Nouveau pack"}
      description="Le client paie en Telegram Stars, puis reçoit automatiquement le contenu dans votre conversation privée."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Annuler
          </Button>
          <Button type="submit" form="pack-form" loading={save.isPending}>
            {pack ? "Enregistrer" : "Créer le pack"}
          </Button>
        </>
      }
    >
      <form id="pack-form" onSubmit={submit} className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-[1fr_180px]">
          <Field label="Nom du pack" htmlFor="pack-name" hint="Visible par le client sur la facture. 32 caractères maximum.">
            <Input id="pack-name" maxLength={32} required autoFocus={!pack} placeholder="Ex. Pack Photos Été" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Prix en Stars" htmlFor="pack-price" hint={price > 0 ? `≈ ${euros(price * rate)} pour vous` : "1 Star minimum"}>
            <div className="relative">
              <Input id="pack-price" type="number" inputMode="numeric" min={1} max={100000} step={1} required className="tabular pr-9" placeholder="250" value={form.price_stars} onChange={(e) => set("price_stars", e.target.value)} />
              <Star className="pointer-events-none absolute top-3 right-3 size-4 fill-warning text-warning" />
            </div>
          </Field>
        </div>
        <Field label="Description" htmlFor="pack-description" optional hint="Aide l'IA à présenter le pack, et s'affiche sur la facture. 255 caractères maximum.">
          <Textarea id="pack-description" rows={2} maxLength={255} className="min-h-0" placeholder="Ex. 20 photos exclusives en haute définition." value={form.description} onChange={(e) => set("description", e.target.value)} />
        </Field>

        <div className="space-y-4 rounded-2xl border border-line bg-surface-2/40 p-4">
          <div>
            <p className="text-sm font-semibold">Contenu livré après paiement</p>
            <p className="mt-0.5 text-[13px] text-ink-3">Fichiers, texte et lien peuvent se combiner. L'IA n'y a jamais accès : seul un paiement confirmé déclenche l'envoi.</p>
          </div>
          <div>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                addFiles(e.dataTransfer.files);
              }}
              className={cn("flex flex-col items-center rounded-2xl border border-dashed px-4 py-6 text-center transition-colors", dragging ? "border-accent bg-accent-soft" : "border-line-strong")}
            >
              <Upload className="mb-2 size-5 text-ink-3" />
              <p className="text-[13px] text-ink-2">
                Glissez vos fichiers ici ou{" "}
                <button type="button" className="font-semibold text-accent hover:underline" onClick={() => fileInput.current?.click()}>
                  parcourez
                </button>
              </p>
              <p className="mt-1 text-xs text-ink-3">Photos, vidéos, PDF, archives… 30 fichiers maximum.</p>
              <input ref={fileInput} type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
            </div>
            {(keptFiles.length > 0 || added.length > 0) && (
              <ul className="mt-3 space-y-1.5">
                {keptFiles.map((f) => (
                  <FileRow key={f.id} name={f.filename} size={f.size} image={isImage(f)} onRemove={() => setRemoved((r) => [...r, f.id])} />
                ))}
                {added.map((f, i) => (
                  <FileRow key={`${f.name}-${i}`} name={f.name} size={f.size} image={f.type.startsWith("image/")} isNew onRemove={() => setAdded((list) => list.filter((_, j) => j !== i))} />
                ))}
              </ul>
            )}
          </div>
          <Field label="Texte" htmlFor="pack-text" optional>
            <Textarea id="pack-text" rows={3} maxLength={3500} placeholder="Ex. un code d'accès, des instructions, un mot de remerciement…" value={form.content_text} onChange={(e) => set("content_text", e.target.value)} />
          </Field>
          <Field label="Lien" htmlFor="pack-link" optional>
            <Input id="pack-link" type="url" maxLength={1024} placeholder="https://…" value={form.content_link} onChange={(e) => set("content_link", e.target.value)} />
          </Field>
        </div>

        <SwitchRow title="En vente" hint="Quand c'est activé, l'IA peut proposer ce pack et envoyer son lien de paiement." checked={form.active} onCheckedChange={(v) => set("active", v)} />
        {error && (
          <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-[13px] text-ink">
            {error}
          </div>
        )}
      </form>
    </Dialog>
  );
}

function FileRow({ name, size, image, isNew, onRemove }: { name: string; size: number; image: boolean; isNew?: boolean; onRemove: () => void }) {
  return (
    <li className="flex items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-ink-2 [&_svg]:size-4">{image ? <ImageIcon /> : <FileText />}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium">{name}</p>
        <p className="text-xs text-ink-3">
          {fileSize(size)}
          {isNew && " · sera envoyé à l'enregistrement"}
        </p>
      </div>
      <Button type="button" variant="ghost" size="icon-sm" aria-label={`Retirer ${name}`} onClick={onRemove}>
        <X />
      </Button>
    </li>
  );
}

export function PacksPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = React.useState<Pack | null>(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [toDelete, setToDelete] = React.useState<Pack | null>(null);
  const packs = useQuery({ queryKey: ["packs"], queryFn: () => api.get<Pack[]>("/api/packs") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/api/settings") });
  const rate = settings.data?.stars_eur_rate ?? 0;

  React.useEffect(() => {
    if (params.get("nouveau")) {
      setEditing(null);
      setDialogOpen(true);
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  const remove = useMutation({
    mutationFn: (pack: Pack) => api.delete(`/api/packs/${pack.id}`),
    onSuccess: (_d, pack) => {
      toast.success(`Pack « ${pack.name} » supprimé`);
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["packs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-xl text-sm text-ink-2">Vos contenus numériques à vendre. L'IA propose les packs en vente et envoie le lien de paiement ; la livraison est automatique.</p>
        <Button onClick={openNew}>
          <Plus />
          Nouveau pack
        </Button>
      </div>

      {settings.data && !settings.data.bot.configured && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-warning/30 bg-warning-soft px-5 py-3.5 text-sm">
          <p>
            <span className="font-semibold">Bot de paiement non configuré.</span> <span className="text-ink-2">Sans lui, aucun lien de paiement ne peut être créé.</span>
          </p>
          <Button asChild variant="secondary" size="sm">
            <a href="/parametres#bot">Configurer le bot</a>
          </Button>
        </div>
      )}

      {packs.isPending ? (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[340px] rounded-2xl" />
          ))}
        </div>
      ) : packs.isError ? (
        <ErrorState message={errorMessage(packs.error)} onRetry={() => packs.refetch()} />
      ) : packs.data.length === 0 ? (
        <Card>
          <EmptyState
            className="py-16"
            icon={<Package />}
            title="Aucun pack pour l'instant"
            description="Créez votre premier pack : un nom, un prix en Stars et le contenu à livrer. Il sera proposé automatiquement par l'IA."
            action={
              <Button onClick={openNew}>
                <Plus />
                Créer mon premier pack
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {packs.data.map((pack) => (
            <PackCard
              key={pack.id}
              pack={pack}
              rate={rate}
              onEdit={() => {
                setEditing(pack);
                setDialogOpen(true);
              }}
              onDelete={() => setToDelete(pack)}
            />
          ))}
        </div>
      )}

      <PackDialog pack={editing} rate={rate} open={dialogOpen} onClose={() => setDialogOpen(false)} />
      <ConfirmDialog
        open={!!toDelete}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Supprimer ce pack ?"
        description={
          toDelete && (
            <>
              « {toDelete.name} » ne sera plus proposé et ses fichiers seront effacés du serveur. Les ventes déjà réalisées restent dans vos statistiques
              {toDelete.sales_count > 0 && <> ({stars(toDelete.sales_stars)} à ce jour)</>}. Pour le retirer temporairement, passez-le plutôt « hors vente ».
            </>
          )
        }
        confirmLabel="Supprimer le pack"
        loading={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete)}
      />
    </div>
  );
}
