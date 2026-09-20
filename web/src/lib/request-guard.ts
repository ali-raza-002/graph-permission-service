export interface Rejection {
  status: number;
  code: string;
  message: string;
}

interface GuardedRequest {
  method: string;
  headers: Headers;
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const ALLOWED_FETCH_SITES = new Set(["same-origin", "none"]);

// Compare against the Host the browser actually used: Next.js builds request.url from its
// own configured hostname, which need not match. A page cannot forge either header on a
// cross-origin request (Host is forbidden, X-Forwarded-Host would force a preflight).
function sameHost(origin: string, headers: Headers): boolean {
  let originHost: string;
  try {
    originHost = new URL(origin).host;
  } catch {
    return false;
  }
  const hosts = [headers.get("x-forwarded-host"), headers.get("host")];
  return hosts.some((host) => host !== null && host.split(",")[0]?.trim() === originHost);
}

/**
 * Cross-site request forgery guard for the proxy routes, which attach server-side
 * credentials. Browsers label every request with Sec-Fetch-Site; anything a page on
 * another site triggers is refused. Older browsers fall back to an Origin check, and
 * bodies must be JSON so a cross-site "simple" form or text/plain POST cannot slip
 * through without a CORS preflight.
 */
export function rejectUnsafeRequest(request: GuardedRequest): Rejection | null {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null && !ALLOWED_FETCH_SITES.has(site)) {
    return { status: 403, code: "cross_site_request", message: "Cross-site requests are not allowed" };
  }
  if (SAFE_METHODS.has(request.method)) return null;

  const origin = request.headers.get("origin");
  if (origin !== null && !sameHost(origin, request.headers)) {
    return { status: 403, code: "cross_site_request", message: "Cross-origin requests are not allowed" };
  }
  const contentType = request.headers.get("content-type") ?? "";
  const hasBody = request.method === "POST" || request.method === "PATCH" || request.method === "PUT";
  if (hasBody && !/^application\/json(\s*;|$)/i.test(contentType)) {
    return { status: 415, code: "unsupported_media_type", message: "Request bodies must be application/json" };
  }
  return null;
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  let diff = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  }
  return diff === 0;
}

/** Whether an Authorization header carries the expected `user:password` basic credentials. */
export function basicAuthMatches(header: string | null, expected: string): boolean {
  if (!header?.startsWith("Basic ")) return false;
  let decoded: Uint8Array;
  try {
    // atob yields one character per byte; browsers send the credentials as UTF-8 bytes, so
    // compare bytes rather than re-encoding that byte string.
    decoded = Uint8Array.from(atob(header.slice("Basic ".length).trim()), (c) => c.charCodeAt(0));
  } catch {
    return false;
  }
  return constantTimeEqual(decoded, new TextEncoder().encode(expected));
}
