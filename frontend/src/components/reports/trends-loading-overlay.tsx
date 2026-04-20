"use client";

/**
 * Large, eye-catching loading state shown while the Trends tab is
 * fetching per-month category data in parallel. Motion-heavy on purpose
 * (this is the "big animation" the product spec calls for), but fully
 * respectful of `prefers-reduced-motion`.
 */
export function TrendsLoadingOverlay({
  loaded,
  total,
}: {
  loaded: number;
  total: number;
}) {
  const pct = total > 0 ? Math.round((loaded / total) * 100) : 0;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-border/60 bg-gradient-to-br from-card via-card to-muted/40 px-6 py-10">
      {/* Animated sweeping gradient background */}
      <div className="pointer-events-none absolute inset-0 opacity-60 motion-reduce:hidden">
        <div className="absolute inset-0 animate-[trends-sweep_3.5s_ease-in-out_infinite] bg-[radial-gradient(circle_at_20%_30%,theme(colors.primary/0.18),transparent_55%),radial-gradient(circle_at_80%_70%,theme(colors.sky.500/0.16),transparent_55%)]" />
      </div>

      <div className="relative mx-auto flex max-w-xl flex-col items-center text-center">
        {/* Big animated SVG chart */}
        <svg
          viewBox="0 0 200 80"
          className="h-32 w-full max-w-md text-primary"
          role="img"
          aria-label="Loading trend data"
        >
          <defs>
            <linearGradient id="trends-line-grad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.2" />
              <stop offset="50%" stopColor="currentColor" stopOpacity="1" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.2" />
            </linearGradient>
            <linearGradient id="trends-fill-grad" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Background placeholder grid */}
          {[20, 40, 60].map((y) => (
            <line
              key={y}
              x1="4"
              x2="196"
              y1={y}
              y2={y}
              stroke="currentColor"
              strokeOpacity="0.06"
              strokeWidth="0.3"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {/* Area under the curve */}
          <path
            d="M 4 60 Q 30 30 60 45 T 120 30 T 196 20 L 196 80 L 4 80 Z"
            fill="url(#trends-fill-grad)"
            className="motion-reduce:opacity-30"
          >
            <animate
              attributeName="opacity"
              values="0.35;0.7;0.35"
              dur="2.4s"
              repeatCount="indefinite"
            />
          </path>

          {/* Animated line with traveling dash */}
          <path
            d="M 4 60 Q 30 30 60 45 T 120 30 T 196 20"
            fill="none"
            stroke="url(#trends-line-grad)"
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            strokeDasharray="6 6"
            className="motion-reduce:[stroke-dasharray:none]"
          >
            <animate
              attributeName="stroke-dashoffset"
              from="0"
              to="-24"
              dur="1.2s"
              repeatCount="indefinite"
            />
          </path>

          {/* Pulsating dot tracing the curve */}
          <circle r="1.8" fill="currentColor" className="motion-reduce:hidden">
            <animateMotion
              dur="3s"
              repeatCount="indefinite"
              path="M 4 60 Q 30 30 60 45 T 120 30 T 196 20"
            />
            <animate
              attributeName="opacity"
              values="0.5;1;0.5"
              dur="1.2s"
              repeatCount="indefinite"
            />
          </circle>
        </svg>

        <h3 className="mt-4 text-base font-semibold">Crunching your history</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Aggregating category spend across {total} months…
        </p>

        {/* Progress bar */}
        <div className="mt-5 w-full max-w-sm space-y-2">
          <div className="flex items-center justify-between text-[11px] font-medium text-muted-foreground">
            <span>
              {loaded} / {total} months loaded
            </span>
            <span className="tabular-nums">{pct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-gradient-to-r from-primary via-sky-500 to-primary bg-[length:200%_100%] transition-[width] duration-500 ease-out motion-reduce:animate-none motion-safe:animate-[trends-shimmer_2s_linear_infinite]"
              style={{ width: `${Math.max(pct, 4)}%` }}
            />
          </div>
        </div>

        {/* Ghost rows */}
        <div className="mt-6 grid w-full max-w-md grid-cols-5 gap-1.5 opacity-50">
          {Array.from({ length: 25 }).map((_, i) => (
            <div
              key={i}
              className="h-4 rounded-sm bg-muted motion-safe:animate-pulse"
              style={{ animationDelay: `${(i % 5) * 80}ms` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
