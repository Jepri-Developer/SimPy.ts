# Changelog

## 0.1.0 (MVP pertama)

- **CLI**: `simpy create`, `simpy dev`, `simpy build`, `simpy generate`.
- **Backend** (ASGI di atas Starlette): routing dengan decorator, validasi input bawaan
  (`Schema`), konfigurasi dari environment/`.env`, penyajian frontend.
- **Frontend** (TypeScript murni): template `html` yang meng-escape otomatis, routing berbasis
  file (`pages/`), navigasi sisi klien, build dengan esbuild.
- **Jembatan backend-frontend**: klien TypeScript bertipe dibuat otomatis dari route Python
  (`simpy generate`), tipe respons dari anotasi return dan dicek saat runtime.
- **Keamanan bawaan**: secure headers dengan CSP ketat, CSRF bertanda tangan, rate limiting,
  password scrypt, sesi di server (SQLite), validasi input ketat.
- Contoh aplikasi di `examples/hello-world`, dokumentasi di `docs/`, CI GitHub Actions.
