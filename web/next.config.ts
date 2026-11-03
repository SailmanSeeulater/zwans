import type { NextConfig } from "next";

// A static export: `zwans serve` serves web/out itself, so no Node server runs alongside it.
// Pages take their parameters from the query string (?id=...), since an export can't render
// a page per session or run.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
