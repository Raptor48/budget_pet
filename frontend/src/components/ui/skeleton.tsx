import { cn } from "@/lib/utils";

/**
 * Shimmer skeleton placeholder. Instead of a flat pulsing fill, a soft
 * highlight sweeps across the element — matches modern loading patterns
 * and makes the UI feel more responsive. Falls back to a muted fill
 * when `prefers-reduced-motion` is enabled (handled globally in
 * `globals.css`).
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "relative overflow-hidden rounded-md bg-muted/60",
        "bg-gradient-to-r from-muted/70 via-muted/30 to-muted/70",
        "bg-[length:200%_100%]",
        "motion-safe:animate-[shimmer_1.6s_ease-in-out_infinite]",
        "motion-reduce:animate-pulse",
        className,
      )}
      {...props}
    />
  );
}
