"use client";

/**
 * OAuth redirect callback page.
 *
 * After the user authenticates at their bank via OAuth, Plaid redirects them here.
 * We reinitialize Plaid Link with the same link_token (stored in localStorage) and
 * pass `receivedRedirectUri: window.location.href` so Link can resume the flow.
 *
 * See: https://plaid.com/docs/link/oauth/#desktop-web-mobile-web-or-react
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { usePlaidLink } from "react-plaid-link";
import { Loader2 } from "lucide-react";
import { plaidApi } from "@/lib/api";

const LINK_TOKEN_KEY = "plaid_link_token";

function OAuthResumeLink({ linkToken, receivedRedirectUri }: { linkToken: string; receivedRedirectUri: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const { open, ready } = usePlaidLink({
    token: linkToken,
    receivedRedirectUri,
    onSuccess: async (publicToken, metadata) => {
      try {
        await plaidApi.exchangeToken(publicToken, metadata.institution?.name ?? undefined);
        localStorage.removeItem(LINK_TOKEN_KEY);
        router.replace("/settings?plaid=connected");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to connect bank account.");
      }
    },
    onExit: (err) => {
      localStorage.removeItem(LINK_TOKEN_KEY);
      if (err) {
        router.replace(`/settings?plaid_error=${encodeURIComponent(err.display_message || err.error_code || "exit")}`);
      } else {
        router.replace("/settings");
      }
    },
  });

  useEffect(() => {
    if (ready) open();
  }, [ready, open]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6 text-center">
        <div className="max-w-sm space-y-3">
          <p className="text-lg font-semibold text-destructive">Connection failed</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <a href="/settings" className="text-sm underline underline-offset-4">
            Back to settings
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="size-5 animate-spin" />
      Resuming bank connection…
    </div>
  );
}

export default function OAuthPage() {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [receivedRedirectUri, setReceivedRedirectUri] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem(LINK_TOKEN_KEY);
    if (!token) {
      setMissing(true);
      return;
    }
    setLinkToken(token);
    setReceivedRedirectUri(window.location.href);
  }, []);

  if (missing) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6 text-center">
        <div className="max-w-sm space-y-3">
          <p className="text-lg font-semibold">Session expired</p>
          <p className="text-sm text-muted-foreground">
            The OAuth session could not be resumed. Please try connecting your bank again.
          </p>
          <a href="/settings" className="text-sm underline underline-offset-4">
            Back to settings
          </a>
        </div>
      </div>
    );
  }

  if (!linkToken || !receivedRedirectUri) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-sm text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
        Loading…
      </div>
    );
  }

  return <OAuthResumeLink linkToken={linkToken} receivedRedirectUri={receivedRedirectUri} />;
}
