type CreditPillProps = {
  credits: number;
  creditsTotal?: number;
};

/**
 * Real-data credit pill (M2). Total defaults to a sensible per-tier ceiling
 * picked by the layout; pill itself just renders what it's given.
 */
export function CreditPill({ credits, creditsTotal }: CreditPillProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)] px-3 py-1.5 text-sm"
      title="Credits remaining this period"
      style={{ fontFamily: "var(--font-geist-mono)" }}
    >
      <span aria-hidden className="text-primary">⚡</span>
      <span className="text-[color:var(--color-text)] tabular-nums">
        {credits.toLocaleString()}
      </span>
      {creditsTotal !== undefined && (
        <span className="text-[color:var(--color-text-subtle)]">
          / {creditsTotal.toLocaleString()}
        </span>
      )}
    </span>
  );
}
