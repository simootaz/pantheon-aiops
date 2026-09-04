/**
 * The two rules the REST reads exist to keep.
 *
 * 1. The token travels in a header. Same rule as `stream.ts` and the
 *    connectors: a credential in a query string lands in the reverse proxy's
 *    access log and in the browser's history.
 * 2. A refusal throws. A 401 turned into `[]` renders "no investigations" to
 *    somebody whose token expired, and they go looking for a run that is
 *    sitting right there.
 *
 * Both are asserted against the request that actually left, not against the
 * shape of the code that built it.
 *
 * Phase: 4 - Delivery Flow
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, isAuthFailure, pendingApprovals, recentInvestigations } from "./api";

/** Capture the one request a call makes, and answer it. */
function stubFetch(status: number, body: unknown): () => Request {
  const seen: Request[] = [];
  vi.stubGlobal("fetch", (input: string, init?: RequestInit) => {
    seen.push(new Request(input, init));
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  return () => {
    const request = seen[0];
    if (!request) throw new Error("no request was made");
    return request;
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the token", () => {
  it("is sent as an authorization header", async () => {
    const request = stubFetch(200, []);
    await recentInvestigations("s3cret");

    expect(request().headers.get("authorization")).toBe("Bearer s3cret");
  });

  it("never appears in the URL", async () => {
    // The assertion that would catch a well-meaning `?token=` added later to
    // make an EventSource work. It reads the whole URL, not just the query.
    const request = stubFetch(200, []);
    await recentInvestigations("s3cret");

    expect(request().url).not.toContain("s3cret");
  });

  it("is omitted entirely when there is none, rather than sent empty", async () => {
    // `Bearer ` with nothing after it is a malformed credential, and the API
    // would answer 401 for a reason that has nothing to do with the token.
    const request = stubFetch(200, []);
    await recentInvestigations(null);

    expect(request().headers.get("authorization")).toBeNull();
  });
});

describe("the tenant", () => {
  it("is not passed, because the server takes it from the principal", async () => {
    // A `?tenant=` would be a claim rather than a fact - see the endpoint in
    // api/routers/investigations.py, which reads it off the verified Principal.
    const request = stubFetch(200, []);
    await recentInvestigations("s3cret");

    expect(request().url).not.toContain("tenant");
  });
});

describe("a refusal", () => {
  it("throws with the status rather than returning an empty list", async () => {
    stubFetch(401, { detail: "token expired" });

    await expect(recentInvestigations("stale")).rejects.toBeInstanceOf(ApiError);
  });

  it("carries the status, so a view can tell 401 from 503", async () => {
    stubFetch(503, {});

    const caught = await recentInvestigations("s3cret").catch((error: unknown) => error);
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
  });

  it("resolves normally on success, so the check is not just refusing", async () => {
    // The control. A `read` that threw unconditionally would pass every
    // assertion above and no view would ever show a row.
    stubFetch(200, [{ id: "abc" }]);

    await expect(pendingApprovals("s3cret")).resolves.toHaveLength(1);
  });
});

describe("isAuthFailure", () => {
  it("separates sign in again from try later", () => {
    expect(isAuthFailure(new ApiError(401, ""))).toBe(true);
    expect(isAuthFailure(new ApiError(403, ""))).toBe(true);
    expect(isAuthFailure(new ApiError(503, ""))).toBe(false);
    expect(isAuthFailure(new TypeError("network"))).toBe(false);
  });
});
