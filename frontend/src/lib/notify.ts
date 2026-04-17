/**
 * Thin wrapper around `sonner` for consistent toast notifications, plus a
 * promise-based `confirm(...)` helper that defers to a global ConfirmDialog
 * mounted at app root. Use this instead of window.alert / window.confirm and
 * as onError handler for React Query mutations.
 */
import { toast } from "sonner";
import { ApiError } from "@/lib/api";

type ToastOpts = { description?: string };

export const notify = {
  success(message: string, opts?: ToastOpts) {
    toast.success(message, opts);
  },
  error(message: string, opts?: ToastOpts) {
    toast.error(message, opts);
  },
  info(message: string, opts?: ToastOpts) {
    toast.info(message, opts);
  },
};

export function formatApiError(err: unknown, fallback = "Something went wrong"): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  if (typeof err === "string") return err;
  return fallback;
}

export function onMutationError(fallback = "Something went wrong") {
  return (err: unknown) => notify.error(formatApiError(err, fallback));
}

// ---------------------------------------------------------------------------
// Global confirm dialog — a single instance is mounted by ConfirmDialogHost.
// ---------------------------------------------------------------------------

export type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

type ConfirmRequest = ConfirmOptions & { resolve: (value: boolean) => void };

type ConfirmListener = (req: ConfirmRequest | null) => void;

let currentListener: ConfirmListener | null = null;

export function registerConfirmListener(listener: ConfirmListener | null) {
  currentListener = listener;
}

export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    if (!currentListener) {
      if (typeof window !== "undefined") {
        const msg = options.description
          ? `${options.title}\n\n${options.description}`
          : options.title;
        resolve(window.confirm(msg));
      } else {
        resolve(false);
      }
      return;
    }
    currentListener({ ...options, resolve });
  });
}
