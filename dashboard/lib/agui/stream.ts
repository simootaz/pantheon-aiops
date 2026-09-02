/**
 * Reading the AG-UI event stream, with a credential that stays out of the URL.
 *
 * WHY NOT `EventSource`
 * ---------------------
 * `EventSource` cannot set request headers. The only way to authenticate one is
 * a query parameter, and a credential in a query string lands in the reverse
 * proxy's access log, in the browser's history, and in any `Referer` the page
 * emits.
 *
 * `connectors/github` and `connectors/gitlab` refuse exactly that on the way
 * out - the token travels in a header. It would be strange to argue it there
 * and then put the dashboard's token in a URL on the way in.
 *
 * So this reads the stream with `fetch` and a `ReadableStream`. It costs the
 * automatic reconnection `EventSource` provides, which is why `reconnect()`
 * below exists and says what it does about state.
 *
 * A RECONNECT DISCARDS THE OLD STATE
 * ----------------------------------
 * The server opens every stream with a `StateSnapshot`. Applying patches from a
 * new connection onto state accumulated from an old one would silently produce
 * an Investigation that never existed - a client showing findings twice, or a
 * verdict from before a retry.
 *
 * So a reconnect is a fresh `InvestigationStore`, and `investigation-state.ts`
 * already refuses a `StateDelta` that arrives before a snapshot.
 *
 * Phase: 4 - Delivery Flow
 */

/** One decoded SSE frame. */
export interface StreamFrame {
  event?: string;
  data: string;
}

/** Everything a caller needs to open one stream. */
export interface StreamOptions {
  url: string;
  /** Bearer token. Sent as a header, never as a query parameter. */
  token?: string;
  signal?: AbortSignal;
}

/**
 * Split an SSE buffer into complete frames, returning the unconsumed remainder.
 *
 * The remainder matters. A `fetch` chunk boundary falls wherever the network
 * put it, so a frame regularly arrives in two reads - and parsing each chunk
 * independently would drop every event unlucky enough to be split, which on a
 * quiet stream is most of them.
 */
export function parseFrames(buffer: string): { frames: StreamFrame[]; rest: string } {
  const frames: StreamFrame[] = [];
  const parts = buffer.split("\n\n");
  // The last part is either an incomplete frame or an empty string. Either way
  // it is not ready, so it goes back to the caller.
  const rest = parts.pop() ?? "";

  for (const part of parts) {
    const frame: StreamFrame = { data: "" };
    const dataLines: string[] = [];

    for (const line of part.split("\n")) {
      if (line.startsWith(":")) continue; // a keep-alive comment
      if (line.startsWith("event:")) frame.event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }

    // Multi-line data is joined with newlines, per the SSE specification. A
    // frame carrying JSON with an embedded newline arrives this way, and
    // taking only the first line would produce a parse error nobody can trace.
    if (dataLines.length > 0) {
      frame.data = dataLines.join("\n");
      frames.push(frame);
    }
  }

  return { frames, rest };
}

/**
 * Read one AG-UI stream, yielding each frame's decoded payload.
 *
 * A non-2xx response throws rather than yielding nothing. A stream that opened,
 * returned 401 and closed is indistinguishable from a run with no events, and a
 * dashboard would render an empty investigation rather than a login prompt.
 */
export async function* readStream(options: StreamOptions): AsyncGenerator<unknown> {
  const headers: Record<string, string> = { accept: "text/event-stream" };
  if (options.token) headers.authorization = `Bearer ${options.token}`;

  const response = await fetch(options.url, {
    headers,
    signal: options.signal,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new StreamError(response.status, `the stream refused to open: ${response.status}`);
  }
  if (response.body === null) {
    throw new StreamError(0, "the response carried no body to read");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = parseFrames(buffer);
      buffer = rest;

      for (const frame of frames) {
        yield JSON.parse(frame.data);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** A stream that would not open, carrying the status so a caller can branch. */
export class StreamError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "StreamError";
  }
}

/**
 * How long to wait before reconnecting, given how many attempts have failed.
 *
 * Exponential with a ceiling. A dashboard left open on a laptop that lost its
 * network would otherwise retry every second for the rest of the day, which is
 * a client-side denial of service against the API it is trying to read.
 *
 * The ceiling is thirty seconds rather than minutes: this is a live incident
 * view, and a reader who fixed their VPN should not wait five minutes to find
 * out the run finished.
 */
export function backoffMs(attempt: number): number {
  const base = Math.min(1000 * 2 ** Math.max(attempt - 1, 0), 30_000);
  // Jitter, so a hundred dashboards reconnecting after one API restart do not
  // arrive in the same millisecond and restart it again.
  return Math.round(base * (0.5 + Math.random() * 0.5));
}

/**
 * Whether a failed stream is worth retrying.
 *
 * A 401 or 403 is not: the token is wrong or lacks a role, and retrying it
 * every thirty seconds produces a log full of failures and never a connection.
 * A 404 is not either - the run does not exist for this reader, and it will not
 * start existing.
 */
export function isRetryable(error: unknown): boolean {
  if (error instanceof StreamError) {
    return error.status !== 401 && error.status !== 403 && error.status !== 404;
  }
  return true;
}
