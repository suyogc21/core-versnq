import type { NextConfig } from "next";

/**
 * Security headers on every page. Stops other sites from embedding our pages (fake look-alike
 * login pages), MIME sniffing and leaking full URLs (with tokens) to other sites. Hosted forms
 * (/f/<id>) are the one exception to embedding: companies put them on their own websites.
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
    return [
      // every page but the hosted forms refuses to be embedded
      { source: "/((?!f/).*)", headers: SECURITY_HEADERS },
      // hosted forms (/f/<id>) are made to be embedded on the company's own website
      { source: "/f/:path*", headers: [...SECURITY_HEADERS.slice(2), { key: "Content-Security-Policy", value: "frame-ancestors *" }] },
      // the service worker (installable app, C2) is always fetched fresh
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }] },
    ];
  },
};

export default nextConfig;
