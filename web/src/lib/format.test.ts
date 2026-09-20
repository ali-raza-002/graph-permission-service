import { describe, expect, it } from "vitest";
import { formatMs, formatPercent, splitRef, timeAgo } from "@/lib/format";

describe("format", () => {
  it("splits object and userset references", () => {
    expect(splitRef("document:roadmap")).toEqual({ type: "document", id: "roadmap", relation: null });
    expect(splitRef("team:eng#member")).toEqual({ type: "team", id: "eng", relation: "member" });
    expect(splitRef("user:*")).toEqual({ type: "user", id: "*", relation: null });
  });

  it("formats latency and ratios for dashboards", () => {
    expect(formatMs(0.42)).toBe("0.42 ms");
    expect(formatMs(12.34)).toBe("12.3 ms");
    expect(formatMs(250.4)).toBe("250 ms");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0.034)).toBe("3.4%");
  });

  it("describes relative times", () => {
    const now = Date.parse("2026-10-04T12:00:00Z");
    expect(timeAgo("2026-10-04T11:59:30Z", now)).toBe("30 seconds ago");
    expect(timeAgo("2026-10-04T09:00:00Z", now)).toBe("3 hours ago");
  });
});
