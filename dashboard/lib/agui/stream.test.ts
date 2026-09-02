/**
 * Reading the stream: frame boundaries, and which failures are worth retrying.
 *
 * The frame test is the one that matters. A `fetch` chunk boundary falls
 * wherever the network put it, so a frame regularly arrives in two reads - and
 * a parser that handled each chunk independently would drop every event
 * unlucky enough to be split.
 *
 * Phase: 4 - Delivery Flow
 */
import { describe, expect, it } from "vitest";
import { backoffMs, isRetryable, parseFrames, StreamError } from "./stream";

describe("parseFrames", () => {
  it("returns an incomplete frame as the remainder rather than dropping it", () => {
    const { frames, rest } = parseFrames('data: {"type":"RUN_STA');

    expect(frames).toHaveLength(0);
    expect(rest).toBe('data: {"type":"RUN_STA');
  });

  it("parses a frame split across two reads once both have arrived", () => {
    const first = parseFrames('data: {"type":"RUN_STA');
    const second = parseFrames(`${first.rest}RTED"}\n\n`);

    const [reassembled] = second.frames;
    expect(reassembled).toBeDefined();
    expect(JSON.parse(reassembled?.data ?? "")).toEqual({ type: "RUN_STARTED" });
  });

  it("parses several frames from one read", () => {
    const { frames } = parseFrames('data: {"a":1}\n\ndata: {"b":2}\n\n');

    expect(frames.map((f) => JSON.parse(f.data))).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("joins multi-line data with newlines, per the SSE specification", () => {
    const { frames } = parseFrames("data: line one\ndata: line two\n\n");

    expect(frames[0]?.data).toBe("line one\nline two");
  });

  it("ignores keep-alive comments", () => {
    const { frames } = parseFrames(': keep-alive\n\ndata: {"a":1}\n\n');

    expect(frames).toHaveLength(1);
  });

  it("carries the event name when one is present", () => {
    const { frames } = parseFrames("event: custom\ndata: {}\n\n");

    expect(frames[0]?.event).toBe("custom");
  });
});

describe("isRetryable", () => {
  it("does not retry a rejected credential", () => {
    // Retrying a 401 every thirty seconds produces a log full of failures and
    // never a connection.
    expect(isRetryable(new StreamError(401, "unauthorised"))).toBe(false);
    expect(isRetryable(new StreamError(403, "forbidden"))).toBe(false);
  });

  it("does not retry a run this reader cannot see", () => {
    // 404 covers "does not exist" and "not yours". Neither starts being true.
    expect(isRetryable(new StreamError(404, "no investigation"))).toBe(false);
  });

  it("retries a server error and a dropped connection", () => {
    // The control. A check that refused everything would make the dashboard
    // give up on one restart.
    expect(isRetryable(new StreamError(503, "unavailable"))).toBe(true);
    expect(isRetryable(new TypeError("network error"))).toBe(true);
  });
});

describe("backoffMs", () => {
  it("grows with the attempt count", () => {
    // A dashboard on a laptop that lost its network would otherwise retry every
    // second for the rest of the day - a client-side denial of service against
    // the API it is trying to read.
    const early = backoffMs(1);
    const later = backoffMs(6);

    expect(later).toBeGreaterThan(early);
  });

  it("never waits longer than thirty seconds", () => {
    // This is a live incident view. A reader who fixed their VPN should not
    // wait five minutes to find out the run finished.
    for (let attempt = 1; attempt < 40; attempt += 1) {
      expect(backoffMs(attempt)).toBeLessThanOrEqual(30_000);
    }
  });

  it("is jittered, so a hundred dashboards do not reconnect in one millisecond", () => {
    const samples = new Set(Array.from({ length: 20 }, () => backoffMs(8)));

    expect(samples.size).toBeGreaterThan(1);
  });
});
