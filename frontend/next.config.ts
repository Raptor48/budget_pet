import type { NextConfig } from "next";

/** Comma-separated full origins, e.g. http://192.168.1.117:3000 — stops Next 15+ LAN dev warning. */
function allowedDevOrigins(): string[] {
  const raw = process.env.NEXT_ALLOWED_DEV_ORIGINS?.trim();
  if (!raw) return [];
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

const nextConfig: NextConfig = {
  allowedDevOrigins: allowedDevOrigins(),
  // Plaid serves merchant + category icons from two public CDNs. Allowlist them
  // here so next/image can fetch + optimize them. Per Plaid /transactions/sync
  // docs, every icon is a 100x100 PNG; we still pass width/height at the use
  // site to drive the optimizer.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "plaid-merchant-logos.plaid.com", pathname: "/**" },
      { protocol: "https", hostname: "plaid-category-icons.plaid.com", pathname: "/**" },
    ],
  },
};

export default nextConfig;
