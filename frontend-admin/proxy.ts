import { NextResponse, type NextRequest } from "next/server";

/**
 * Forwards API calls to FastAPI on the same origin, so refresh cookies stay
 * first-party (httpOnly, SameSite=strict). The backend picks the workspace from
 * X-Forwarded-Host (when TRUST_PROXY_HEADERS=true); this proxy always overwrites
 * that header with the real Host, so a browser cannot choose another workspace.
 * In production nginx does the same job.
 */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  const target = new URL(request.nextUrl.pathname + request.nextUrl.search, BACKEND_URL);
  return NextResponse.rewrite(target, { request: { headers } });
}

export const config = {
  matcher: ["/platform/:path*"],
};
