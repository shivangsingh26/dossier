import type { SVGProps } from "react";

type MarkProps = {
  size?: number;
  strokeColor?: string;
  className?: string;
} & Omit<SVGProps<SVGSVGElement>, "width" | "height">;

/**
 * Split-D monogram — primary brand mark. Spec §3.4.
 * Outer circle (cream stroke) wraps two halves: peach left, mint right.
 */
export function Mark({
  size = 48,
  strokeColor = "#f5ebe0",
  className,
  ...rest
}: MarkProps) {
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      aria-label="Dossier"
      role="img"
      {...rest}
    >
      <circle cx="50" cy="50" r="46" fill="none" stroke={strokeColor} strokeWidth="3" />
      <path d="M 30 22 L 30 78 L 56 78 A 28 28 0 0 0 56 22 Z" fill="#f97316" />
      <path d="M 56 22 A 28 28 0 0 1 56 78 L 56 50 Z" fill="#4ade80" />
    </svg>
  );
}
