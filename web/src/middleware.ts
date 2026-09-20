import { NextResponse, type NextRequest } from "next/server";
import { basicAuthMatches } from "@/lib/request-guard";

const CREDENTIALS = /^[^:]+:.{8,}$/;

// Optional gate for the whole console. The proxy routes hold a Warden key, so anything
// that can reach this server can act with that key; set CONSOLE_BASIC_AUTH (user:password)
// whenever the console is reachable from anywhere but localhost.
export function middleware(request: NextRequest): NextResponse {
  const expected = process.env.CONSOLE_BASIC_AUTH ?? "";
  if (expected === "") return NextResponse.next();
  if (!CREDENTIALS.test(expected)) {
    return new NextResponse("CONSOLE_BASIC_AUTH must look like user:password (8+ character password)", {
      status: 500,
    });
  }
  if (basicAuthMatches(request.headers.get("authorization"), expected)) return NextResponse.next();
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Warden console", charset="UTF-8"' },
  });
}

export const config = {
  runtime: "nodejs",
  matcher: ["/((?!_next/static|_next/image|favicon.ico|monaco/).*)"],
};
