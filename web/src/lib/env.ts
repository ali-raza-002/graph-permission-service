import "server-only";
import { z } from "zod";

const schema = z.object({
  WARDEN_API_URL: z.url().default("http://127.0.0.1:8106"),
  WARDEN_API_KEY: z.string().min(8, "WARDEN_API_KEY must be set for the console proxy"),
  WORKSPACES_API_URL: z.url().default("http://127.0.0.1:27106"),
});

export type ServerEnv = z.infer<typeof schema>;

let cached: ServerEnv | undefined;

export function serverEnv(): ServerEnv {
  cached ??= schema.parse(process.env);
  return cached;
}
