import { Mark } from "./Mark";
import { Wordmark } from "./Wordmark";

type LockupProps = {
  size?: "sm" | "md" | "lg";
  className?: string;
};

const MARK_SIZE: Record<NonNullable<LockupProps["size"]>, number> = {
  sm: 24,
  md: 32,
  lg: 44,
};

const WORDMARK_SIZE: Record<NonNullable<LockupProps["size"]>, "sm" | "md" | "lg"> = {
  sm: "sm",
  md: "md",
  lg: "lg",
};

/**
 * Full lockup = Mark + Wordmark side-by-side. Spec §3.4.
 */
export function Lockup({ size = "md", className }: LockupProps) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <Mark size={MARK_SIZE[size]} />
      <Wordmark size={WORDMARK_SIZE[size]} />
    </span>
  );
}
