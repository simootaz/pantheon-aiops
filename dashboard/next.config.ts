import type { NextConfig } from "next";

/**
 * Pantheon dashboard configuration.
 *
 * Phase: 4 - Delivery Flow
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The API base the AG-UI client talks to. Compose and Helm both set this.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
