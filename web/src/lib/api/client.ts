import { z } from "zod";
import { apiErrorSchema } from "@/lib/api/schemas";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>[];

  constructor(status: number, code: string, message: string, details: Record<string, unknown>[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query: Query | undefined): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

const fastApiDetailSchema = z.object({
  detail: z.union([
    z.string(),
    z.object({ code: z.string(), message: z.string() }).loose(),
    z.array(z.object({ msg: z.string(), loc: z.array(z.union([z.string(), z.number()])) })),
  ]),
  code: z.string().optional(),
});

async function parseError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null);
  const parsed = apiErrorSchema.safeParse(body);
  if (parsed.success) {
    const { code, message, details } = parsed.data.error;
    return new ApiError(response.status, code, message, details);
  }
  const fastApi = fastApiDetailSchema.safeParse(body);
  if (!fastApi.success) {
    return new ApiError(response.status, "http_error", response.statusText || "Request failed");
  }
  const { detail, code } = fastApi.data;
  if (typeof detail === "string") return new ApiError(response.status, code ?? "http_error", detail);
  if (Array.isArray(detail)) {
    const message = detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    return new ApiError(response.status, "validation_error", message, detail);
  }
  const { code: detailCode, message, ...rest } = detail;
  return new ApiError(response.status, detailCode, message, [rest]);
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function requestJson<S extends z.ZodType>(
  base: string,
  path: string,
  schema: S,
  options: RequestOptions = {},
): Promise<z.infer<S>> {
  const response = await send(base, path, options);
  const payload: unknown = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError(response.status, "invalid_response", `Unexpected response from ${path}`);
  }
  return parsed.data;
}

export async function send(base: string, path: string, options: RequestOptions = {}): Promise<Response> {
  const init: RequestInit = {
    method: options.method ?? "GET",
    headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store",
  };
  if (options.body !== undefined) init.body = JSON.stringify(options.body);
  if (options.signal) init.signal = options.signal;
  const response = await fetch(withQuery(`${base}/${path}`, options.query), init);
  if (!response.ok) throw await parseError(response);
  return response;
}
