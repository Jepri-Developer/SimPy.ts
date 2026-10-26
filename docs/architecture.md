# Arsitektur SimPy.ts

- Backend: ASGI di atas Starlette. Validasi memakai modul bawaan `simpy.validation`;
  Pydantic dicoret karena `pydantic-core` (Rust) tidak bisa dipasang di Termux/Android.
- Frontend: TypeScript murni, template tag `html` yang meng-escape otomatis (anti-XSS).
- Build: esbuild.
- Komunikasi: REST JSON + klien TypeScript bertipe hasil generate (`simpy generate`). Tipe respons
  dari anotasi return route; Schema/list[Schema] dicek saat runtime. Detail: docs/api-bridge.md.
- CLI: Python (`pip install simpy-ts` menyediakan perintah `simpy`).
- Satu origin untuk API dan frontend (tanpa CORS, CSRF lebih mudah dijaga).
- Keamanan (docs/security.md): middleware ASGI (rate limit global -> secure headers -> cookie CSRF),
  lalu per route: rate limit -> CSRF -> auth/sesi -> validasi input. Sesi di server (SQLite),
  password scrypt, semua dengan pustaka standar.
- Versi: Python >= 3.11, Node >= 20; test pytest + vitest; lint ruff + eslint.
