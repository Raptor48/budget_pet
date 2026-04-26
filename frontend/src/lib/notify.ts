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
  // Defensive coerce: if some future code path stores a non-string into
  // ApiError.detail (e.g. a Pydantic 422 array slipping past the
  // normaliser in api.ts), we serialise here so the toast never renders
  // an object — that would crash the React tree with error #31
  // ("Objects are not valid as a React child").
  const asString = (v: unknown, fb: string): string => {
    if (typeof v === "string" && v.length > 0) return v;
    if (v == null) return fb;
    try {
      return JSON.stringify(v);
    } catch {
      return fb;
    }
  };
  if (err instanceof ApiError) {
    return asString(err.detail ?? err.message, fallback);
  }
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
