import { cn } from "@/lib/utils";

/**
 * Minimal skeleton placeholder. Use in place of spinners for the initial
 * load of cards, lists, or tables so the page shape is preserved.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted/60", className)}
      {...props}
    />
  );
}
