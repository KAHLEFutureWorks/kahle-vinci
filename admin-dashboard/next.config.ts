import type { NextConfig } from "next";

const basePath = process.env.DASHBOARD_BASE_PATH || "";

const nextConfig: NextConfig = {
  basePath,
  assetPrefix: basePath || undefined,
};

export default nextConfig;