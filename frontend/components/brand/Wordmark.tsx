type WordmarkProps = {
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
};

const SIZE_CLASS: Record<NonNullable<WordmarkProps["size"]>, string> = {
  sm: "text-xl",
  md: "text-2xl",
  lg: "text-4xl",
  xl: "text-6xl",
};

/**
 * "Dossier" wordmark — Geist semibold + peach period. Spec §3.4 (post-redesign 2026-05-18).
 */
export function Wordmark({ size = "md", className }: WordmarkProps) {
  return (
    <span
      className={`font-extrabold tracking-[-0.03em] ${SIZE_CLASS[size]} ${className ?? ""}`}
    >
      Dossier<span style={{ color: "#f97316" }}>.</span>
    </span>
  );
}
