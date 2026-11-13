import { cn } from "@/lib/utils";

export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  className,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  className?: string;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex rounded-xl border border-line bg-surface-2 p-0.5", className)}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "h-8 rounded-[10px] px-3 text-[13px] font-medium whitespace-nowrap transition-colors duration-150",
            value === option.value ? "bg-surface-3 text-ink shadow-sm" : "text-ink-3 hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
