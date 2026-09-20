import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { rejectUnsafeRequest } from "@/lib/request-guard";

const FORWARDED_RESPONSE_HEADERS = ["content-type", "x-request-id"];

interface ProxyOptions {
  upstream: string;
  path: string[];
  allow: (path: string) => boolean;
  headers: Record<string, string>;
}

/**
 * Forwards a browser request to an internal service. Credentials are attached here,
 * on the server, so API keys never reach the browser.
 */
export async function proxy(request: NextRequest, options: ProxyOptions): Promise<NextResponse> {
  const rejection = rejectUnsafeRequest(request);
  if (rejection) {
    return NextResponse.json(
      { error: { code: rejection.code, message: rejection.message, details: [] } },
      { status: rejection.status },
    );
  }
  const path = options.path.map(encodeURIComponent).join("/");
  if (!options.allow(path)) {
    return NextResponse.json(
      { error: { code: "not_found", message: "Unknown API path", details: [] } },
      { status: 404 },
    );
  }
  const target = new URL(`${options.upstream.replace(/\/$/, "")}/${path}`);
  target.search = request.nextUrl.search;

  const headers: Record<string, string> = { ...options.headers };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const init: RequestInit = { method: request.method, headers, cache: "no-store" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "upstream_unavailable",
          message: `Could not reach ${new URL(options.upstream).host}. Is the service running?`,
          details: [],
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  return new NextResponse(body, { status: upstream.status, headers: responseHeaders });
}
