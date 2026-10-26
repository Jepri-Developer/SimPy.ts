import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, request } from "../../src/frontend/api.ts";

interface Call {
  url: string;
  init: RequestInit;
}

function stubFetch(handler: (call: Call) => Response | Promise<Response>) {
  const original = globalThis.fetch;
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
  return { calls, restore: () => void (globalThis.fetch = original) };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("GET sukses mengembalikan JSON dan mengirim header yang benar", async () => {
  const stub = stubFetch(() => json({ message: "hi" }));
  try {
    const result = await request<{ message: string }>("GET", "/api/hello");
    assert.deepEqual(result, { message: "hi" });
    const call = stub.calls[0];
    assert.equal(call?.url, "/api/hello");
    assert.equal(call?.init.method, "GET");
    assert.equal(call?.init.credentials, "same-origin");
    assert.equal((call?.init.headers as Record<string, string>)["Accept"], "application/json");
    assert.equal(call?.init.body, undefined);
  } finally {
    stub.restore();
  }
});

test("POST mengirim body JSON dengan Content-Type", async () => {
  const stub = stubFetch(() => json({ ok: true }));
  try {
    await request("POST", "/api/greet", { body: { name: "Ani" } });
    const call = stub.calls[0];
    assert.equal(call?.init.body, '{"name":"Ani"}');
    assert.equal(
      (call?.init.headers as Record<string, string>)["Content-Type"],
      "application/json",
    );
  } finally {
    stub.restore();
  }
});

test("status 204 mengembalikan undefined", async () => {
  const stub = stubFetch(() => new Response(null, { status: 204 }));
  try {
    assert.equal(await request<void>("DELETE", "/api/x"), undefined);
  } finally {
    stub.restore();
  }
});

test("error validasi 422 menjadi ApiError lengkap dengan details", async () => {
  const body = {
    error: "validation_error",
    message: "Input tidak valid",
    details: [{ loc: ["name"], msg: "minimal 1 karakter" }, "sampah"],
  };
  const stub = stubFetch(() => json(body, 422));
  try {
    await assert.rejects(request("POST", "/api/greet", { body: {} }), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 422);
      assert.equal(error.code, "validation_error");
      assert.equal(error.message, "Input tidak valid");
      assert.deepEqual(error.details, [{ loc: ["name"], msg: "minimal 1 karakter" }]);
      return true;
    });
  } finally {
    stub.restore();
  }
});

test("error non-JSON menjadi ApiError generik", async () => {
  const stub = stubFetch(
    () => new Response("<html>oops</html>", { status: 502, statusText: "Bad Gateway" }),
  );
  try {
    await assert.rejects(request("GET", "/api/x"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 502);
      assert.equal(error.code, "http_error");
      assert.ok(!error.message.includes("<html>"));
      return true;
    });
  } finally {
    stub.restore();
  }
});

test("gagal koneksi menjadi ApiError status 0", async () => {
  const stub = stubFetch(() => {
    throw new TypeError("fetch failed");
  });
  try {
    await assert.rejects(request("GET", "/api/x"), (error: unknown) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 0);
      assert.equal(error.code, "network_error");
      return true;
    });
  } finally {
    stub.restore();
  }
});

test("respons sukses yang bukan JSON ditolak", async () => {
  const stub = stubFetch(() => new Response("teks", { status: 200 }));
  try {
    await assert.rejects(
      request("GET", "/api/x"),
      (error: unknown) => error instanceof ApiError && error.code === "invalid_response",
    );
  } finally {
    stub.restore();
  }
});

test("hanya path satu origin yang diizinkan", async () => {
  const stub = stubFetch(() => json({}));
  try {
    for (const bad of ["https://evil.test/x", "//evil.test/x", "api/x", "javascript:alert(1)"]) {
      await assert.rejects(request("GET", bad), /origin yang sama/, bad);
    }
    assert.equal(stub.calls.length, 0);
  } finally {
    stub.restore();
  }
});

test("AbortError diteruskan apa adanya", async () => {
  const stub = stubFetch(() => {
    throw new DOMException("dibatalkan", "AbortError");
  });
  try {
    await assert.rejects(request("GET", "/api/x"), (error: unknown) => {
      assert.ok(!(error instanceof ApiError));
      return true;
    });
  } finally {
    stub.restore();
  }
});
