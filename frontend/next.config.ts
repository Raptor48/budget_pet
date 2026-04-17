import type { NextConfig } from "next";

/** Comma-separated full origins, e.g. http://192.168.1.117:3000 — stops Next 15+ LAN dev warning. */
function allowedDevOrigins(): string[] {
  const raw = process.env.NEXT_ALLOWED_DEV_ORIGINS?.trim();
  if (!raw) return [];
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

const nextConfig: NextConfig = {
  allowedDevOrigins: allowedDevOrigins(),
};

export default nextConfig;
