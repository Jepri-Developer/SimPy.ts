# Frontend SimPy.ts (Fase 3)

Halaman ditulis dengan TypeScript murni. Satu file di `pages/` = satu route (file-based routing).

| File | Route |
|---|---|
| `pages/index.ts` | `/` |
| `pages/about.ts` | `/about` |
| `pages/users/index.ts` | `/users` |
| `pages/users/[id].ts` | `/users/:id` |
| `pages/404.ts` | halaman tidak ditemukan |

File berawalan `_`, `*.d.ts`, dan `*.test.ts` diabaikan (boleh dipakai untuk helper).
Route statis didahulukan sebelum yang dinamis. Nama yang bentrok ditolak saat build.

## Menulis halaman

```ts
import { html, safeUrl, type PageContext } from "simpy-ts/frontend";

export default async function render(ctx: PageContext) {
  const name = ctx.query.get("name") ?? "tamu";      // ?name=...
  const id = ctx.params["id"];                        // dari pages/users/[id].ts
  return html`<h1>Halo, ${name}</h1><a href="${safeUrl("/")}">Beranda</a>`;
}
```

## Keamanan (XSS by design)

- `html` meng-escape setiap nilai yang disisipkan. Hanya `SafeHtml` yang menembus escape:
  hasil `html`, atau `raw()` (hanya untuk HTML yang kamu tulis sendiri).
- Halaman yang mengembalikan string biasa ditolak (tidak pernah masuk ke `innerHTML`).
- Selalu beri tanda kutip pada atribut: `title="${x}"`. Jangan menyisipkan nilai ke `<script>`
  atau `<style>`. Bungkus URL dari pengguna dengan `safeUrl()` (menolak `javascript:`, `data:`).
- Error halaman hanya ditulis ke console; pengguna melihat pesan generik.
- `index.html` dibuat tanpa script inline, siap untuk CSP ketat di Fase 5.

## Build

```bash
npm install                 # sekali: esbuild + typescript
simpy build                 # hasil: dist/index.html + dist/app.js
simpy build --minify
simpy dev                   # backend + esbuild --watch otomatis
npm run typecheck           # tsc (opsional)
```

`simpy build` menyalin runtime ke `.simpy/frontend/`, membuat `.simpy/entry.ts` (daftar route),
lalu memanggil esbuild. Folder `.simpy/` dan `dist/` dibuat otomatis (sudah di `.gitignore`).
Halaman baru butuh restart `simpy dev`.

Backend menyajikan `dist/` lewat `app.serve_frontend()`: `/static/*` untuk aset dan `index.html`
untuk path lain (kecuali `/api/*` dan path berekstensi, yang membalas JSON 404). Perlindungan
path traversal dan symlink keluar folder sudah ada.

## Pengembangan SimPy.ts sendiri

```bash
npm install
npm test            # node --test (butuh Node >= 22.18, TypeScript dijalankan langsung)
npm run typecheck
```

Halaman interaktif (`definePage` + `mount`) dan pemanggilan API: lihat [api-bridge.md](api-bridge.md).
