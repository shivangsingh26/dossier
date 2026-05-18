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
 * Fraunces italic "Dossier" with a peach "." period — spec §3.4.
 */
export function Wordmark({ size = "md", className }: WordmarkProps) {
  return (
    <span
      className={`italic font-medium tracking-tight ${SIZE_CLASS[size]} ${className ?? ""}`}
      style={{ fontFamily: "var(--font-fraunces)" }}
    >
      Dossier<span style={{ color: "#f97316" }}>.</span>
    </span>
  );
}
