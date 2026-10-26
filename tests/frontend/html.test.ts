import assert from "node:assert/strict";
import test from "node:test";

import { SafeHtml, escapeHtml, html, raw, safeUrl } from "../../src/frontend/html.ts";

test("html() mengembalikan SafeHtml", () => {
  assert.ok(html`<p>x</p>` instanceof SafeHtml);
});

test("nilai yang disisipkan di-escape", () => {
  const evil = "<script>alert(1)</script>";
  assert.equal(html`<p>${evil}</p>`.value, "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>");
});

test("kutip di atribut di-escape sehingga atribut tidak bisa disisipi", () => {
  const evil = '" onmouseover="alert(1)';
  assert.equal(
    html`<a title="${evil}">x</a>`.value,
    '<a title="&quot; onmouseover=&quot;alert(1)">x</a>',
  );
});

test("html bersarang tidak di-escape dua kali", () => {
  const inner = html`<b>${"a&b"}</b>`;
  assert.equal(html`<p>${inner}</p>`.value, "<p><b>a&amp;b</b></p>");
});

test("array dirender berurutan", () => {
  const items = ["a", "<b>"].map((item) => html`<li>${item}</li>`);
  assert.equal(html`<ul>${items}</ul>`.value, "<ul><li>a</li><li>&lt;b&gt;</li></ul>");
});

test("null, undefined, true, false kosong; angka tampil", () => {
  assert.equal(html`[${null}${undefined}${false}${true}]`.value, "[]");
  assert.equal(html`[${0}|${42}]`.value, "[0|42]");
});

test("string biasa tidak pernah dianggap aman", () => {
  const notSafe = "<img src=x onerror=alert(1)>";
  assert.ok(!html`${notSafe}`.value.includes("<img"));
});

test("raw() melewati escape", () => {
  assert.equal(html`<div>${raw("<i>ok</i>")}</div>`.value, "<div><i>ok</i></div>");
});

test("escapeHtml menangani semua karakter berbahaya", () => {
  assert.equal(escapeHtml(`&<>"'\``), "&amp;&lt;&gt;&quot;&#39;&#96;");
});

test("safeUrl menerima url aman dan menolak skema berbahaya", () => {
  assert.equal(safeUrl("/about"), "/about");
  assert.equal(safeUrl("https://example.com/a?b=1"), "https://example.com/a?b=1");
  assert.equal(safeUrl("mailto:a@b.co"), "mailto:a@b.co");
  assert.equal(safeUrl(""), "");
  for (const bad of [
    "javascript:alert(1)",
    "  JaVaScRiPt:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:x",
  ]) {
    assert.equal(safeUrl(bad), "#", bad);
  }
});
