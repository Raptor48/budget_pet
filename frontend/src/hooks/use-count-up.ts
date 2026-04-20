"use client";

import { useEffect, useRef, useState } from "react";

export interface UseCountUpOptions {
  /** Animation duration in ms. Defaults to 600. */
  durationMs?: number;
  /** Decimal precision kept during animation (final value still matches exactly). */
  decimals?: number;
  /**
   * Skip the tween on the first render. Defaults to `false` so the value
   * visibly "flies in" when a screen mounts.
   */
  skipInitial?: boolean;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Animates a numeric value from its previous state (or 0 on first mount)
 * to the target using `requestAnimationFrame` and an `ease-out-cubic`
 * curve. Respects `prefers-reduced-motion` by jumping immediately to the
 * target.
 */
export function useCountUp(
  target: number,
  { durationMs = 600, decimals = 0, skipInitial = false }: UseCountUpOptions = {},
): number {
  const [value, setValue] = useState<number>(() =>
    skipInitial || prefersReducedMotion() ? target : 0,
  );
  const rafRef = useRef<number | null>(null);
  const fromRef = useRef<number>(value);

  useEffect(() => {
    if (!Number.isFinite(target)) {
      setValue(target);
      return;
    }
    if (prefersReducedMotion() || durationMs <= 0) {
      setValue(target);
      return;
    }

    fromRef.current = value;
    const from = value;
    const start = performance.now();
    const round = decimals > 0 ? Math.pow(10, decimals) : 1;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      const raw = from + (target - from) * eased;
      setValue(Math.round(raw * round) / round);
      if (t < 1) {
        rafRef.current = window.requestAnimationFrame(tick);
      } else {
        setValue(target);
      }
    };

    rafRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) window.cancelAnimationFrame(rafRef.current);
    };
    // intentionally omit `value` from deps: we only retarget when the
    // external target actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs, decimals]);

  return value;
}
