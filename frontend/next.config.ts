import type { NextConfig } from "next";

/**
 * Security headers on every page. Stops other sites from embedding our pages (fake look-alike
 * login pages), MIME sniffing and leaking full URLs (with tokens) to other sites.
 * HSTS is added by the HTTPS proxy in production.
 */
const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone", // the production image (Dockerfile) runs the standalone server
  // Uploads pass through proxy.ts, which buffers bodies and silently cuts them at this size.
  // Files are at most 10 MB (Decision log #32); the backend also refuses any cut-off body.
  experimental: { proxyClientMaxBodySize: "11mb" },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
