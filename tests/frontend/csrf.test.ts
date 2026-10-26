import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, request } from "../../src/frontend/api.ts";
import { currentCsrfToken, readCsrfToken } from "../../src/frontend/csrf.ts";

test("readCsrfToken membaca cookie dev maupun production", () => {
  assert.equal(readCsrfToken("a=1; simpy_csrf=abc.def; b=2"), "abc.def");
  assert.equal(readCsrfToken("__Host-simpy_csrf=prod.tok"), "prod.tok");
  assert.equal(readCsrfToken("simpy_csrf=dev.tok; __Host-simpy_csrf=prod.tok"), "prod.tok");
});

test("readCsrfToken mengembalikan null bila tidak ada", () => {
  assert.equal(readCsrfToken(""), null);
  assert.equal(readCsrfToken("a=1; b=2"), null);
  assert.equal(readCsrfToken("simpy_csrf="), null);
  assert.equal(readCsrfToken("xsimpy_csrf=abc"), null);
});

test("currentCsrfToken null di luar browser", () => {
  assert.equal(currentCsrfToken(), null);
});

function withBrowser(cookie: string, handler: (init: RequestInit) => Response) {
  const g = globalThis as Record<string, unknown>;
  const originalFetch = globalThis.fetch;
  const seen: RequestInit[] = [];
  g["document"] = { cookie };
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    seen.push(init ?? {});
    return handler(init ?? {});
  }) as typeof fetch;
  return {
    seen,
    restore: () => {
      delete g["document"];
      globalThis.fetch = originalFetch;
    },
  };
}

const ok = () =>
  new Response("{}", { status: 200, headers: { "content-type": "application/json" } });

test("request() mengirim X-CSRF-Token pada POST, bukan pada GET", async () => {
  const env = withBrowser("simpy_csrf=tok.sig", ok);
  try {
    await request("POST", "/api/x", { body: {} });
    await request("GET", "/api/x");
    const post = env.seen[0]?.headers as Record<string, string>;
    const get = env.seen[1]?.headers as Record<string, string>;
    assert.equal(post["X-CSRF-Token"], "tok.sig");
    assert.equal(get["X-CSRF-Token"], undefined);
  } finally {
    env.restore();
  }
});

test("request() tanpa cookie CSRF tidak mengirim header", async () => {
  const env = withBrowser("lain=1", ok);
  try {
    await request("DELETE", "/api/x");
    assert.equal((env.seen[0]?.headers as Record<string, string>)["X-CSRF-Token"], undefined);
  } finally {
    env.restore();
  }
});

test("403 csrf_failed menjadi ApiError", async () => {
  const body = { error: "csrf_failed", message: "Token CSRF tidak valid atau hilang." };
  const env = withBrowser("", () =>
    new Response(JSON.stringify(body), {
      status: 403,
      headers: { "content-type": "application/json" },
    }),
  );
  try {
    await assert.rejects(
      request("POST", "/api/x", { body: {} }),
      (error: unknown) => error instanceof ApiError && error.code === "csrf_failed",
    );
  } finally {
    env.restore();
  }
});
