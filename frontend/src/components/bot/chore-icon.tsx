"use client";

import {
  Bath,
  Bed,
  Brush,
  Car,
  ChefHat,
  Dog,
  Flower2,
  ListChecks,
  ShoppingCart,
  Shirt,
  Sparkles,
  Trash2,
  UtensilsCrossed,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * Icons for the household-chores rotation.
 *
 * The chore row stores a single TEXT value in `chores.icon`. New rows save the
 * key (e.g. "kitchen"); legacy rows still hold the emoji that the v1 seed
 * inserted (🍳 / 🛁 / 🧹 / …). LEGACY_EMOJI_MAP translates those values into
 * the same icon keys so existing households see a real icon instead of the
 * generic fallback. The picker below only ever writes keys — emoji input is
 * gone for good in V2.3+ to keep the bot tab visually consistent with the
 * rest of the app's lucide-only design system.
 */

export const CHORE_ICONS: { value: string; label: string; icon: LucideIcon }[] = [
  { value: "kitchen", label: "Kitchen", icon: ChefHat },
  { value: "dishes", label: "Dishes", icon: UtensilsCrossed },
  { value: "bathroom", label: "Bathroom", icon: Bath },
  { value: "floors", label: "Floors", icon: Brush },
  { value: "trash", label: "Trash", icon: Trash2 },
  { value: "laundry", label: "Laundry", icon: Shirt },
  { value: "bedroom", label: "Bedroom", icon: Bed },
  { value: "plants", label: "Plants", icon: Flower2 },
  { value: "car", label: "Car", icon: Car },
  { value: "pet", label: "Pet", icon: Dog },
  { value: "groceries", label: "Groceries", icon: ShoppingCart },
  { value: "repairs", label: "Repairs", icon: Wrench },
  { value: "cleaning", label: "Cleaning", icon: Sparkles },
  { value: "general", label: "General", icon: ListChecks },
];

export const DEFAULT_CHORE_ICON_KEY = "general";

const ICON_BY_KEY: Record<string, LucideIcon> = Object.fromEntries(
  CHORE_ICONS.map((o) => [o.value, o.icon]),
);

const LABEL_BY_KEY: Record<string, string> = Object.fromEntries(
  CHORE_ICONS.map((o) => [o.value, o.label]),
);

const LEGACY_EMOJI_MAP: Record<string, string> = {
  "🍳": "kitchen",
  "🍽": "dishes",
  "🍽️": "dishes",
  "🛁": "bathroom",
  "🚿": "bathroom",
  "🧹": "floors",
  "🗑": "trash",
  "🗑️": "trash",
  "👕": "laundry",
  "🧺": "laundry",
  "🛏": "bedroom",
  "🛏️": "bedroom",
  "🌱": "plants",
  "🌿": "plants",
  "🌷": "plants",
  "🚗": "car",
  "🐕": "pet",
  "🐶": "pet",
  "🐾": "pet",
  "🛒": "groceries",
  "🔧": "repairs",
  "🛠": "repairs",
  "🛠️": "repairs",
  "✨": "cleaning",
};

export function resolveChoreIconKey(value?: string | null): string {
  if (!value) return DEFAULT_CHORE_ICON_KEY;
  if (ICON_BY_KEY[value]) return value;
  if (LEGACY_EMOJI_MAP[value]) return LEGACY_EMOJI_MAP[value];
  return DEFAULT_CHORE_ICON_KEY;
}

export function ChoreIcon({
  value,
  className,
}: {
  value?: string | null;
  className?: string;
}) {
  const key = resolveChoreIconKey(value);
  const Icon = ICON_BY_KEY[key];
  return (
    <Icon
      className={cn("h-4 w-4 text-muted-foreground", className)}
      aria-label={LABEL_BY_KEY[key]}
    />
  );
}

export function ChoreIconPicker({
  value,
  onChange,
  id,
}: {
  value?: string | null;
  onChange: (next: string) => void;
  id?: string;
}) {
  const current = resolveChoreIconKey(value);
  return (
    <Select value={current} onValueChange={onChange}>
      <SelectTrigger id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {CHORE_ICONS.map(({ value: v, label, icon: Icon }) => (
          <SelectItem key={v} value={v}>
            <span className="flex items-center gap-2">
              <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
              {label}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
