import { describe, expect, it } from "vitest";
import { basicAuthMatches, rejectUnsafeRequest } from "@/lib/request-guard";

function request(method: string, headers: Record<string, string>) {
  return { method, headers: new Headers({ host: "127.0.0.1:3106", ...headers }) };
}

describe("rejectUnsafeRequest", () => {
  it("allows same-origin JSON writes from the console", () => {
    const req = request("POST", {
      "sec-fetch-site": "same-origin",
      origin: "http://127.0.0.1:3106",
      "content-type": "application/json",
    });
    expect(rejectUnsafeRequest(req)).toBeNull();
  });

  it("trusts the forwarded host set by a reverse proxy", () => {
    const req = request("POST", {
      origin: "https://console.example.com",
      "x-forwarded-host": "console.example.com",
      "content-type": "application/json",
    });
    expect(rejectUnsafeRequest(req)).toBeNull();
  });

  it("refuses anything another site triggers, including reads", () => {
    expect(rejectUnsafeRequest(request("GET", { "sec-fetch-site": "cross-site" }))?.status).toBe(403);
    expect(rejectUnsafeRequest(request("POST", { "sec-fetch-site": "same-site" }))?.status).toBe(403);
  });

  it("falls back to the Origin header when Sec-Fetch-Site is missing", () => {
    const req = request("POST", { origin: "http://evil.example", "content-type": "application/json" });
    expect(rejectUnsafeRequest(req)?.code).toBe("cross_site_request");
  });

  it("requires JSON bodies so text/plain form posts cannot get through", () => {
    const plain = request("POST", { origin: "http://127.0.0.1:3106", "content-type": "text/plain" });
    expect(rejectUnsafeRequest(plain)?.status).toBe(415);
    const charset = request("POST", { "content-type": "application/json; charset=utf-8" });
    expect(rejectUnsafeRequest(charset)).toBeNull();
    expect(rejectUnsafeRequest(request("DELETE", {}))).toBeNull();
  });
});

describe("basicAuthMatches", () => {
  const header = `Basic ${btoa("admin:s3cret")}`;

  it("accepts the configured credentials only", () => {
    expect(basicAuthMatches(header, "admin:s3cret")).toBe(true);
    expect(basicAuthMatches(header, "admin:other")).toBe(false);
    expect(basicAuthMatches(null, "admin:s3cret")).toBe(false);
    expect(basicAuthMatches("Basic %%%", "admin:s3cret")).toBe(false);
  });
});
