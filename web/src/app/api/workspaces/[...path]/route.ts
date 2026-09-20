import type { NextRequest } from "next/server";
import { serverEnv } from "@/lib/env";
import { proxy } from "@/lib/proxy";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

const HANDLE = /^[a-z0-9_-]{1,64}$/;

async function handle(request: NextRequest, context: Context) {
  const user = request.headers.get("x-workspaces-user") ?? "";
  return proxy(request, {
    upstream: serverEnv().WORKSPACES_API_URL,
    path: (await context.params).path,
    allow: (path) => path.startsWith("api/"),
    headers: HANDLE.test(user) ? { "x-workspaces-user": user } : {},
  });
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
