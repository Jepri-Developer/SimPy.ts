import assert from "node:assert/strict";
import test from "node:test";

import { createApp, renderUrl } from "../../src/frontend/app.ts";
import { html } from "../../src/frontend/html.ts";
import { definePage } from "../../src/frontend/page.ts";
import type { AppOptions } from "../../src/frontend/app.ts";
import type { PageContext } from "../../src/frontend/types.ts";

const options: AppOptions = {
  routes: [
    { pattern: "/", page: () => html`<h1>Beranda</h1>` },
    {
      pattern: "/users/:id",
      page: (ctx: PageContext) => html`<p>${ctx.params["id"]}|${ctx.query.get("tab")}</p>`,
    },
    { pattern: "/slow", page: async () => html`<p>lambat</p>` },
    { pattern: "/string", page: (() => "<b>bukan SafeHtml</b>") as never },
    {
      pattern: "/boom",
      page: () => {
        throw new Error("rahasia internal");
      },
    },
  ],
};

test("renderUrl memberi params dan query ke halaman", async () => {
  const out = await renderUrl(options, "/users/7", "?tab=profil");
  assert.equal(out.value, "<p>7|profil</p>");
});

test("nilai dari URL di-escape", async () => {
  const out = await renderUrl(options, "/users/%3Cscript%3E", "");
  assert.ok(!out.value.includes("<script>"));
});

test("halaman async didukung", async () => {
  assert.equal((await renderUrl(options, "/slow")).value, "<p>lambat</p>");
});

test("404 bawaan dan notFound kustom", async () => {
  assert.ok((await renderUrl(options, "/nope")).value.includes("404"));
  const custom = { ...options, notFound: () => html`<h1>Hilang</h1>` };
  assert.equal((await renderUrl(custom, "/nope")).value, "<h1>Hilang</h1>");
});

test("error halaman tidak bocor ke output", async (t) => {
  t.mock.method(console, "error", () => {});
  const out = await renderUrl(options, "/boom");
  assert.ok(out.value.includes("Terjadi kesalahan"));
  assert.ok(!out.value.includes("rahasia internal"));
});

test("halaman yang mengembalikan string biasa ditolak", async (t) => {
  t.mock.method(console, "error", () => {});
  const out = await renderUrl(options, "/string");
  assert.ok(!out.value.includes("<b>"));
});

type Listener = (event: unknown) => void;

function installFakeDom() {
  const g = globalThis as Record<string, unknown>;
  const listeners: Record<string, Listener[]> = {};
  const add = (type: string, fn: Listener) => {
    (listeners[type] ??= []).push(fn);
  };
  const root = { innerHTML: "" };
  const loc = { pathname: "/", search: "", origin: "http://app.test", href: "http://app.test/" };
  g["location"] = loc;
  g["history"] = {
    pushState(_state: unknown, _title: string, url: string) {
      const parsed = new URL(url, loc.href);
      loc.pathname = parsed.pathname;
      loc.search = parsed.search;
      loc.href = parsed.href;
    },
  };
  g["window"] = { addEventListener: add, scrollTo() {} };
  g["document"] = { querySelector: () => root, addEventListener: add };

  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const click = (href: string, extra: Record<string, unknown> = {}) => {
    let prevented = false;
    const anchor = { href, getAttribute: () => null, hasAttribute: () => false };
    const event = {
      defaultPrevented: false,
      button: 0,
      metaKey: false,
      ctrlKey: false,
      shiftKey: false,
      altKey: false,
      target: { closest: () => anchor },
      preventDefault() {
        prevented = true;
      },
      ...extra,
    };
    for (const fn of listeners["click"] ?? []) fn(event);
    return () => prevented;
  };
  const restore = () => {
    for (const key of ["location", "history", "window", "document"]) delete g[key];
  };
  return { root, loc, listeners, tick, click, restore };
}

test("start() merender, mencegat klik link internal, dan membiarkan link luar", async () => {
  const dom = installFakeDom();
  try {
    createApp(options).start();
    await dom.tick();
    assert.equal(dom.root.innerHTML, "<h1>Beranda</h1>");

    const internal = dom.click("http://app.test/users/9?tab=x");
    await dom.tick();
    assert.equal(internal(), true);
    assert.equal(dom.root.innerHTML, "<p>9|x</p>");

    assert.equal(dom.click("http://evil.test/")(), false);
    assert.equal(dom.click("http://app.test/api/hello")(), false);
    assert.equal(dom.click("http://app.test/", { ctrlKey: true })(), false);

    dom.loc.pathname = "/";
    dom.loc.href = "http://app.test/";
    for (const fn of dom.listeners["popstate"] ?? []) fn({});
    await dom.tick();
    assert.equal(dom.root.innerHTML, "<h1>Beranda</h1>");
  } finally {
    dom.restore();
  }
});

test("definePage: mount dipanggil setelah render dan cleanup sebelum pindah halaman", async () => {
  const events: string[] = [];
  const interactive = definePage({
    render: () => html`<h1>Interaktif</h1>`,
    mount: (root, context) => {
      events.push(`mount:${context.path}:${(root as unknown as { innerHTML: string }).innerHTML}`);
      return () => events.push("cleanup");
    },
  });
  const app: AppOptions = {
    routes: [
      { pattern: "/", page: interactive },
      { pattern: "/lain", page: () => html`<p>lain</p>` },
    ],
  };
  const dom = installFakeDom();
  try {
    createApp(app).start();
    await dom.tick();
    assert.deepEqual(events, ["mount:/:<h1>Interaktif</h1>"]);

    dom.click("http://app.test/lain");
    await dom.tick();
    assert.deepEqual(events, ["mount:/:<h1>Interaktif</h1>", "cleanup"]);
    assert.equal(dom.root.innerHTML, "<p>lain</p>");
  } finally {
    dom.restore();
  }
});

test("mount yang melempar error tidak merusak aplikasi", async (t) => {
  t.mock.method(console, "error", () => {});
  const broken = definePage({
    render: () => html`<h1>Rusak</h1>`,
    mount: () => {
      throw new Error("gagal mount");
    },
  });
  const dom = installFakeDom();
  try {
    createApp({ routes: [{ pattern: "/", page: broken }] }).start();
    await dom.tick();
    assert.equal(dom.root.innerHTML, "<h1>Rusak</h1>");
  } finally {
    dom.restore();
  }
});

test("start() gagal jelas bila elemen root tidak ada", () => {
  const g = globalThis as Record<string, unknown>;
  g["document"] = { querySelector: () => null, addEventListener() {} };
  g["window"] = { addEventListener() {} };
  try {
    assert.throws(() => createApp(options).start(), /tidak ditemukan/);
  } finally {
    delete g["document"];
    delete g["window"];
  }
});
