"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pencil, Search, Tag } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { merchantAliasesApi } from "@/lib/api";
import { notify, onMutationError } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { LogoCandidate, Transaction } from "@/types/v2";

type Props = {
  /** The transaction whose merchant we'll rename. We need
   * ``merchant_entity_id`` + ``merchant_name`` to derive the
   * family-global key, plus ``display_title`` as a fallback for
   * ACH / check rows that have neither. */
  tx: Transaction;
  /** Optional explicit className for the trigger affordance. */
  className?: string;
};

/**
 * Merchant-override popover — covers two related user overrides:
 *
 *   1. **Display name.** Rename "2B STOR4 NY" → "2 Bros Pizza" so the
 *      Plaid-detected label gets a friendlier rendering everywhere it
 *      shows up (Reports, Recurring, Top merchants, ...).
 *   2. **Website + logo pick.** Type a domain (e.g. `2broslittleitaly.com`)
 *      → the backend resolves logo candidates from Brandfetch +
 *      faviconextractor + Google s2/favicons → user picks a thumbnail →
 *      the chosen URL lands in ``merchant_logos`` with
 *      ``status='user_curated'`` and beats every auto-resolved logo.
 *
 * Either override is independently nullable. The popover lets the user
 * set just one or both. "Remove" clears both columns.
 */
export function RenameMerchantPopover({ tx, className }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [websiteDraft, setWebsiteDraft] = useState("");
  const [pickedLogo, setPickedLogo] = useState<LogoCandidate | null>(null);
  // Tracks the last *fetched* domain so the gallery doesn't refetch on
  // every keystroke — only on an explicit "Find logos" click.
  const [searchedDomain, setSearchedDomain] = useState<string>("");

  const eid = (tx.merchant_entity_id ?? "").trim();
  const name = (tx.merchant_name ?? "").trim();
  const fallback = (tx.display_title ?? "").trim();
  // The alias system needs *something* to key on — eid, name, or
  // display_title. Hide the affordance when nothing is available
  // (extremely rare; happens for fully manual rows with empty merchant).
  const canAlias = Boolean(eid || name || fallback);

  const currentAlias = (tx.merchant_alias ?? "").trim();
  const isAliased = currentAlias.length > 0;

  // Reset drafts whenever we open or the underlying tx changes —
  // otherwise the popover would remember stale typing across rows.
  useEffect(() => {
    if (open) {
      setNameDraft(currentAlias || fallback || name);
      setWebsiteDraft("");
      setPickedLogo(null);
      setSearchedDomain("");
    }
  }, [open, currentAlias, fallback, name]);

  const candidatesQuery = useQuery({
    queryKey: ["merchant-aliases", "logo-candidates", searchedDomain],
    queryFn: () => merchantAliasesApi.logoCandidates(searchedDomain),
    enabled: searchedDomain.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });
  const candidates: LogoCandidate[] = useMemo(
    () => candidatesQuery.data?.candidates ?? [],
    [candidatesQuery.data],
  );

  const invalidate = () => {
    // Surfaces that bake the alias / logo into their responses:
    qc.invalidateQueries({ queryKey: ["transactions"] });
    qc.invalidateQueries({ queryKey: ["transaction"] });
    qc.invalidateQueries({ queryKey: ["recurring"] });
    qc.invalidateQueries({ queryKey: ["reports"] });
    qc.invalidateQueries({ queryKey: ["insights"] });
  };

  const upsertMutation = useMutation({
    mutationFn: () =>
      merchantAliasesApi.upsert({
        merchant_entity_id: eid || null,
        merchant_name: name || null,
        merchant_label: name ? null : fallback || null,
        // null means "leave unchanged" — only send fields the user actually
        // changed in this session.
        display_name: nameChanged ? nameDraft.trim() : undefined,
        website: websiteChanged ? websiteDraft.trim() : undefined,
        chosen_logo_url: pickedLogo?.url ?? undefined,
        chosen_logo_domain: pickedLogo
          ? candidatesQuery.data?.domain
          : undefined,
      }),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      const msg = pickedLogo
        ? `Saved “${nameDraft.trim()}” with custom logo`
        : `Renamed to “${nameDraft.trim()}”`;
      notify.success(msg);
    },
    onError: onMutationError("Could not save merchant override."),
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      merchantAliasesApi.delete({
        merchant_entity_id: eid || null,
        merchant_name: name || null,
        merchant_label: name ? null : fallback || null,
      }),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      notify.success("Merchant override removed");
    },
    onError: onMutationError("Could not remove override."),
  });

  if (!canAlias) return null;

  const trimmedName = nameDraft.trim();
  const trimmedWebsite = websiteDraft.trim();
  const nameChanged = trimmedName.length > 0 && trimmedName !== currentAlias;
  const websiteChanged = trimmedWebsite.length > 0;
  // Save is enabled when there's any change to push. A new logo pick
  // counts even without a name/website change (the user might be
  // re-picking from a saved website on a later visit, hypothetical for
  // now since we don't pre-populate the website field — but the
  // condition stays correct for that future flow).
  const saveDisabled =
    upsertMutation.isPending ||
    deleteMutation.isPending ||
    trimmedName.length === 0 ||
    (!nameChanged && !websiteChanged && !pickedLogo);

  const handleFindLogos = () => {
    const cleaned = trimmedWebsite;
    if (!cleaned) return;
    setSearchedDomain(cleaned);
    setPickedLogo(null);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded-sm px-1 py-0.5 text-[11px] uppercase tracking-wide transition-colors",
            isAliased && "text-foreground/80",
            className,
          )}
          aria-label={isAliased ? "Edit merchant override" : "Rename merchant"}
        >
          {isAliased ? <Tag className="size-3" /> : <Pencil className="size-3" />}
          <span>{isAliased ? `Aliased as “${currentAlias}”` : "Rename merchant"}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <div className="space-y-1">
          <Label htmlFor="merchant-alias-input" className="text-sm">
            Show this merchant as
          </Label>
          <Input
            id="merchant-alias-input"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            maxLength={200}
            placeholder="e.g. 2 Bros Pizza"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && !saveDisabled) {
                e.preventDefault();
                upsertMutation.mutate();
              }
            }}
          />
        </div>

        <div className="space-y-1">
          <Label htmlFor="merchant-website-input" className="text-sm">
            Website <span className="text-muted-foreground">(optional)</span>
          </Label>
          <div className="flex gap-1.5">
            <Input
              id="merchant-website-input"
              value={websiteDraft}
              onChange={(e) => setWebsiteDraft(e.target.value)}
              maxLength={500}
              placeholder="2broslittleitaly.com"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleFindLogos();
                }
              }}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={trimmedWebsite.length === 0 || candidatesQuery.isFetching}
              onClick={handleFindLogos}
              aria-label="Find logo candidates"
            >
              {candidatesQuery.isFetching ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Search className="size-3.5" aria-hidden />
              )}
            </Button>
          </div>
        </div>

        {/* Candidate gallery — appears once the user clicks Find. */}
        {searchedDomain ? (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              Pick a logo {candidatesQuery.isFetching ? "…" : `(${candidates.length})`}
            </Label>
            {candidates.length === 0 && !candidatesQuery.isFetching ? (
              <p className="text-xs text-muted-foreground">
                No logos found for that domain. Try a different URL.
              </p>
            ) : (
              <div className="grid grid-cols-5 gap-1.5">
                {candidates.map((c) => {
                  const active = pickedLogo?.url === c.url;
                  return (
                    <button
                      key={c.url}
                      type="button"
                      onClick={() => setPickedLogo(c)}
                      title={c.label}
                      className={cn(
                        "relative aspect-square overflow-hidden rounded-md border bg-white p-1 transition-colors",
                        active
                          ? "border-primary ring-2 ring-primary/40"
                          : "border-border/60 hover:border-border",
                      )}
                      aria-label={`Select ${c.label}`}
                      aria-pressed={active}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={c.url}
                        alt=""
                        className="size-full object-contain"
                        loading="lazy"
                      />
                      {active && (
                        <span className="absolute right-0.5 top-0.5 rounded-full bg-primary p-0.5 text-primary-foreground">
                          <Check className="size-2.5" aria-hidden />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            {pickedLogo && (
              <p className="truncate text-[10px] text-muted-foreground">
                Picked: {pickedLogo.label}
              </p>
            )}
          </div>
        ) : null}

        <p className="text-muted-foreground text-[11px] leading-snug">
          Rename + logo override apply everywhere this merchant appears
          (Top merchants, Recurring, Insights). Categorization, math,
          and Plaid sync are untouched.
        </p>

        <div className="flex justify-between gap-2 pt-1">
          {isAliased ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={deleteMutation.isPending || upsertMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              className="text-destructive hover:text-destructive"
            >
              Remove
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setOpen(false)}
              disabled={upsertMutation.isPending || deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={saveDisabled}
              onClick={() => upsertMutation.mutate()}
            >
              {upsertMutation.isPending ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                "Save"
              )}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
