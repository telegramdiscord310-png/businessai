import * as LabelPrimitive from "@radix-ui/react-label";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as React from "react";
import { cn } from "@/lib/utils";

const fieldBase =
  "w-full rounded-xl border border-line bg-surface-2 px-3.5 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 hover:border-line-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-50";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(fieldBase, "h-10", className)} {...props} />;
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(fieldBase, "scroll-thin min-h-24 resize-y py-2.5 leading-relaxed", className)} {...props} />;
}

export function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return <LabelPrimitive.Root className={cn("text-[13px] font-medium text-ink", className)} {...props} />;
}

/** Champ complet : libellé, contrôle, phrase d'aide. */
export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
  optional,
}: {
  label: string;
  hint?: React.ReactNode;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
  optional?: boolean;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={htmlFor} className="flex items-center gap-2">
        {label}
        {optional && <span className="text-xs font-normal text-ink-3">facultatif</span>}
      </Label>
      {children}
      {hint && <p className="text-[13px] leading-snug text-ink-3">{hint}</p>}
    </div>
  );
}

export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "relative inline-flex h-6 w-10.5 shrink-0 items-center rounded-full bg-surface-3 transition-colors duration-200 data-[state=checked]:bg-accent disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-4.5 translate-x-[3px] rounded-full bg-white shadow-sm transition-transform duration-200 data-[state=checked]:translate-x-[21px]" />
    </SwitchPrimitive.Root>
  );
}

/** Ligne de réglage : titre + aide à gauche, interrupteur à droite. */
export function SwitchRow({
  title,
  hint,
  checked,
  onCheckedChange,
  disabled,
}: {
  title: string;
  hint?: React.ReactNode;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const id = React.useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0 space-y-0.5">
        <label htmlFor={id} className="block text-sm font-medium text-ink">
          {title}
        </label>
        {hint && <p className="text-[13px] leading-snug text-ink-3">{hint}</p>}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} className="mt-0.5" />
    </div>
  );
}
