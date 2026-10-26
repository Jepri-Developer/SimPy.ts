# SimPy.ts

**Simpatel Python TypeScript**: framework web dengan **backend Python** dan **frontend TypeScript**
dalam satu project, mirip Next.js tetapi lintas bahasa. Dibuat oleh **Simpatel Studios**.
Lisensi [MIT](LICENSE). Status: **0.1.0 (MVP)**.

```python
# app/routes.py: tipe respons dari anotasi return
@app.post("/api/greet")
def greet(data: GreetInput) -> Message:
    return {"message": f"Halo, {data.name}!"}
```

```ts
// pages/index.ts: klien TypeScript bertipe dibuat otomatis dari route di atas
const reply = await api.greet({ name: "Ani" });   // reply: Message
```

## Fitur

- **CLI**: `simpy create`, `simpy dev`, `simpy build`, `simpy generate`.
- **Backend**: ASGI di atas Starlette, routing dengan decorator, validasi input otomatis.
- **Frontend**: TypeScript murni, routing berbasis file (`pages/`), template `html` yang
  meng-escape otomatis, build dengan esbuild.
- **Jembatan bertipe**: tipe Python menjadi tipe TypeScript, jadi salah panggil API ketahuan
  saat kompilasi, bukan saat dijalankan.
- **Keamanan bawaan**: secure headers + CSP ketat, proteksi CSRF dan XSS, rate limiting,
  password scrypt, sesi aman di server, secret hanya dari environment variable.
- **Ringan**: dependensi Python hanya `starlette`, `uvicorn`, `anyio`; bisa dipasang di Termux.

## Persyaratan

- Python >= 3.11
- Node.js >= 22.18 dan npm
- Opsional: `curl` (untuk uji manual dan `scripts/smoke.sh`)

## Instalasi

```bash
git clone <url-repo-kamu> SimPy.ts      # ganti dengan URL repo GitHub kamu
cd SimPy.ts
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                 # Termux/Android: pip install -e . pytest
simpy --version
```

## Mulai cepat: project baru

```bash
simpy create myapp
cd myapp
npm install                 # esbuild + typescript (sekali saja)
cp .env.example .env        # lalu isi SIMPY_SECRET_KEY
simpy dev                   # buka http://127.0.0.1:8000
```

## Mulai cepat: contoh siap pakai

Contoh lengkap ada di [`examples/hello-world`](examples/hello-world): form sapaan yang memanggil
API, halaman dengan parameter URL, dan alur daftar/masuk/keluar.

```bash
cd examples/hello-world
npm install
cp .env.example .env
simpy dev                   # buka http://127.0.0.1:8000
```

Di browser: klik **Sapa**, buka `/about?name=Ani`, lalu `/account` untuk mendaftar dan masuk.
Atau lewat terminal lain:

```bash
curl http://127.0.0.1:8000/api/hello
```

## Perintah CLI

| Perintah | Fungsi |
|---|---|
| `simpy create <nama> [--dir DIR]` | Buat project baru dari template |
| `simpy dev [--host H] [--port P] [--no-reload]` | Server pengembangan (uvicorn + reload) dan esbuild `--watch` |
| `simpy build [--minify]` | Buat klien API lalu build frontend ke `dist/` |
| `simpy generate` | Buat ulang klien TypeScript (`.simpy/api.ts`) setelah mengubah route |

## Struktur project hasil `simpy create`

```
myapp/
├── app/routes.py         # route Python (backend)
├── pages/                # halaman TypeScript, satu file = satu route
├── simpy.config.json
├── .env.example          # salin ke .env
├── package.json  tsconfig.json
└── (dibuat otomatis)  .simpy/  dist/  instance/
```

## Dokumentasi

- [Backend](docs/backend.md): route, validasi, konfigurasi
- [Frontend](docs/frontend.md): halaman, routing, build
- [Jembatan API](docs/api-bridge.md): klien bertipe, tipe respons, error
- [Keamanan](docs/security.md): headers, CSRF, rate limit, auth, batasan
- [Arsitektur](docs/architecture.md) dan alasan tiap keputusan
- [Termux/Android](docs/termux.md)

## Pengembangan dan test

```bash
pytest                   # backend dan CLI (Python)
npm install && npm test  # frontend (TypeScript, node --test)
npm run typecheck        # tsc untuk src/frontend
bash scripts/smoke.sh    # end-to-end: create, build, jalankan server, uji lewat curl
```

CI GitHub Actions (`.github/workflows/ci.yml`) menjalankan semuanya pada Python 3.11-3.14
dan Node 22. Panduan kontribusi: [CONTRIBUTING.md](CONTRIBUTING.md).

## Batasan saat ini

- Belum ada reset password, verifikasi email, atau 2FA.
- Rate limit (memori) dan sesi (SQLite) ditujukan untuk satu server.
- Halaman baru di `pages/` butuh restart `simpy dev`; klien API dibuat ulang lewat
  `simpy generate` setelah route berubah.
- Belum ada server-side rendering; halaman dirender di browser.
- Proyek awal (0.x) dan belum diaudit keamanannya secara independen.

## Lisensi

MIT, hak cipta Simpatel Studios. Lihat [LICENSE](LICENSE).
