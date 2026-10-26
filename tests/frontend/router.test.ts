import assert from "node:assert/strict";
import test from "node:test";

import { html } from "../../src/frontend/html.ts";
import { matchRoute, normalizePath } from "../../src/frontend/router.ts";
import type { RouteDef } from "../../src/frontend/types.ts";

const page = () => html`x`;
const routes: RouteDef[] = [
  { pattern: "/", page },
  { pattern: "/about", page },
  { pattern: "/users/new", page },
  { pattern: "/users/:id", page },
  { pattern: "/blog/:slug/edit", page },
];

test("route statis", () => {
  assert.equal(matchRoute(routes, "/")?.route.pattern, "/");
  assert.equal(matchRoute(routes, "/about")?.route.pattern, "/about");
});

test("route dinamis mengisi params", () => {
  const match = matchRoute(routes, "/users/42");
  assert.equal(match?.route.pattern, "/users/:id");
  assert.deepEqual(match?.params, { id: "42" });
  assert.deepEqual(matchRoute(routes, "/blog/halo/edit")?.params, { slug: "halo" });
});

test("urutan menentukan prioritas (statis sebelum dinamis)", () => {
  assert.equal(matchRoute(routes, "/users/new")?.route.pattern, "/users/new");
});

test("trailing slash diabaikan", () => {
  assert.equal(matchRoute(routes, "/about/")?.route.pattern, "/about");
  assert.equal(normalizePath("/"), "/");
  assert.equal(normalizePath("/a//"), "/a");
});

test("tidak cocok mengembalikan null", () => {
  for (const path of ["/tidak-ada", "/users", "/users/1/2", "/about/x", "about", "/a//b"]) {
    assert.equal(matchRoute(routes, path), null, path);
  }
});

test("param di-decode dan %-encoding rusak ditolak", () => {
  assert.deepEqual(matchRoute(routes, "/users/a%20b")?.params, { id: "a b" });
  assert.equal(matchRoute(routes, "/users/%E0%A4%A"), null);
});

test("param bernama __proto__ tidak mencemari prototype", () => {
  const evil: RouteDef[] = [{ pattern: "/x/:__proto__", page }];
  const match = matchRoute(evil, "/x/polluted");
  assert.equal(Object.getPrototypeOf(match?.params), Object.prototype);
  assert.equal(({} as Record<string, unknown>)["polluted"], undefined);
  assert.equal(Object.keys(match?.params ?? {}).includes("__proto__"), true);
});
