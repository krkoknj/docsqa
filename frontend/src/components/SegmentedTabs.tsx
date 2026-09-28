type Props<T extends string> = {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label?: string;
  /** Extra classes for the track (e.g. its background color). */
  className?: string;
};

/** Pill-shaped tab switcher. */
export default function SegmentedTabs<T extends string>({ options, value, onChange, label, className = "" }: Props<T>) {
  return (
    <div className={`flex gap-1 rounded-full p-1 ${className}`} role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          aria-selected={value === o.id}
          onClick={() => onChange(o.id)}
          className={`flex-1 rounded-full py-2 text-sm font-bold transition-colors ${
            value === o.id ? "bg-ink text-cream" : "text-fg-dim hover:text-fg"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
