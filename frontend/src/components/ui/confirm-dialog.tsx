"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { registerConfirmListener, type ConfirmOptions } from "@/lib/notify";

type ConfirmRequest = ConfirmOptions & { resolve: (value: boolean) => void };

/**
 * Global <ConfirmDialog/> host. Mount it once at the app root. It listens for
 * promise-based `confirm(...)` calls from lib/notify and renders a shadcn
 * Dialog, resolving the promise with the user's choice.
 */
export function ConfirmDialogHost() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);

  useEffect(() => {
    registerConfirmListener((req) => setRequest(req));
    return () => registerConfirmListener(null);
  }, []);

  function handleCancel() {
    request?.resolve(false);
    setRequest(null);
  }

  function handleConfirm() {
    request?.resolve(true);
    setRequest(null);
  }

  return (
    <Dialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open) handleCancel();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{request?.title}</DialogTitle>
          {request?.description ? (
            <DialogDescription>{request.description}</DialogDescription>
          ) : null}
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button variant="outline" onClick={handleCancel} autoFocus>
            {request?.cancelLabel ?? "Cancel"}
          </Button>
          <Button
            variant={request?.destructive ? "destructive" : "default"}
            onClick={handleConfirm}
          >
            {request?.confirmLabel ?? (request?.destructive ? "Delete" : "Confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
