import type { NextRequest } from "next/server";
import { serverEnv } from "@/lib/env";
import { proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Context) {
  const env = serverEnv();
  return proxy(request, {
    upstream: env.WARDEN_API_URL,
    path: (await context.params).path,
    // Key management stays out of the browser entirely; the console key also lacks keys:admin.
    allow: (path) => (path.startsWith("v1/") && !path.startsWith("v1/api-keys")) || path === "healthz",
    headers: { authorization: `Bearer ${env.WARDEN_API_KEY}` },
  });
}

export { handle as GET, handle as POST, handle as DELETE };
