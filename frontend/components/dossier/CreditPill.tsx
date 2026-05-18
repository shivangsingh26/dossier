type CreditPillProps = {
  used?: number;
  total?: number;
};

/**
 * Static placeholder for M1. M2 wires this to GET /me { credits, credits_total }.
 */
export function CreditPill({ used = 0, total = 100 }: CreditPillProps) {
  const remaining = total - used;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)] px-3 py-1.5 text-sm"
      title="Credits remaining this period"
      style={{ fontFamily: "var(--font-geist-mono)" }}
    >
      <span aria-hidden className="text-primary">⚡</span>
      <span className="text-[color:var(--color-text)] tabular-nums">
        {remaining}
      </span>
      <span className="text-[color:var(--color-text-subtle)]">/ {total}</span>
    </span>
  );
}
