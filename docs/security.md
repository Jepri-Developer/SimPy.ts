# Keamanan SimPy.ts (Fase 5)

Semua fitur ini aktif **otomatis**. Hanya pustaka standar Python yang dipakai (tanpa paket
native), jadi bisa dipasang di Termux/Android.

## Secure headers

Dipasang di setiap respons (termasuk 404 dan 429): `Content-Security-Policy`,
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
`Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`. `Strict-Transport-Security`
hanya di `SIMPY_ENV=production`. Respons `/api/*` diberi `Cache-Control: no-store`.
Header yang sudah ditulis handler tidak ditimpa.

CSP bawaan ketat: `script-src 'self'`, `style-src 'self'`, `object-src 'none'`,
`frame-ancestors 'none'`. Artinya **tidak ada script atau style inline**, dan atribut
`style="..."` diblokir browser; taruh CSS di file sendiri yang disajikan dari `/static/`.
Longgarkan hanya bila perlu: `SimPy(csp="...")`.

## CSRF

- Server memasang cookie `simpy_csrf` (bisa dibaca JS) berisi token yang ditandatangani HMAC
  dengan `SIMPY_SECRET_KEY` dan terikat ke sesi login.
- Setiap POST/PUT/PATCH/DELETE wajib mengirim header `X-CSRF-Token` yang sama dengan cookie.
  `request()`/`api.*` di klien TypeScript melakukannya otomatis.
- Pemeriksaan tambahan: `Origin` harus sama dengan `Host` (atau ada di
  `SimPy(allowed_origins=[...])`) dan `Sec-Fetch-Site` tidak boleh `cross-site`/`same-site`.
- Token diganti saat login dan logout. Respons 403 membawa cookie baru, jadi klien bisa mencoba lagi.
- Webhook dari luar: `@app.post("/webhook", csrf=False)` (lindungi dengan tanda tangan sendiri).
- Body harus `application/json`, yang juga mencegah kiriman form lintas situs.

## Rate limiting

- Global: 300 request/menit per IP (`SimPy(rate_limit="300/minute")`, `None` untuk mematikan).
- Per route: `@app.post("/api/login", rate_limit="10/minute")`. Melebihi batas membalas 429 JSON
  dengan `Retry-After`.
- Jendela geser di memori, **per proses**: dengan beberapa worker, batas efektifnya dikali
  jumlah worker. Memori dibatasi (10.000 kunci).
- Di belakang reverse proxy, atur `SimPy(trusted_proxy_hops=1)` agar IP klien diambil dari
  `X-Forwarded-For`. Tanpa itu header tersebut diabaikan (tidak bisa dipalsukan untuk
  menghindari batas).

## Auth dan sesi

```python
@app.post("/api/login", rate_limit="10/minute")
def sign_in(request, data: Credentials) -> UserOut:
    user = app.users.authenticate(data.username, data.password)
    if user is None:
        raise HTTPError(401, "Username atau password salah.")
    login(request, user.id)                    # buat sesi, pasang cookie, ganti token CSRF
    return {"id": user.id, "username": user.username}

@app.get("/api/me", auth=True)                 # tanpa sesi: 401
def me(session: Session) -> UserOut: ...

@app.post("/api/logout")
def sign_out(request) -> None:
    logout(request)
```

- Password di-hash dengan `scrypt` + salt acak (`hash_password`, `verify_password`). Login
  untuk username tak dikenal tetap menjalankan hash agar waktu responsnya sama.
- Cookie sesi: `HttpOnly`, `SameSite=Lax`, `Path=/`; di production juga `Secure` dan awalan
  `__Host-`. Cookie hanya berisi id acak 256-bit; SQLite hanya menyimpan hash SHA-256-nya,
  jadi bocornya database tidak membocorkan sesi aktif.
- Logout mencabut sesi di server (cookie yang dicuri tidak berguna lagi). `login()` mencabut sesi
  lama (anti session fixation). Masa hidup 7 hari, batas diam 1 hari
  (`session_lifetime`, `session_idle_timeout`).
- Database: `SIMPY_SESSION_DB` (default `instance/sessions.db`, izin file 0600). Dibuat lazy,
  jadi aplikasi tanpa auth tidak membuat file apa pun. Folder `instance/` sudah ada di `.gitignore`.
- Pakai handler `def` biasa untuk fungsi yang memanggil hash password; framework menjalankannya
  di thread terpisah sehingga server tidak terblokir.

## Konfigurasi production

```
SIMPY_ENV=production
SIMPY_SECRET_KEY=<acak, minimal 32 karakter>
```

Jalankan di belakang HTTPS. Cookie `Secure` tidak akan terkirim lewat HTTP biasa.

## Batasan yang perlu kamu ketahui

- Belum ada reset password, verifikasi email, atau 2FA.
- Rate limit dan penyimpanan sesi SQLite ditujukan untuk satu server. Untuk beberapa mesin,
  ganti dengan penyimpanan bersama (Redis/PostgreSQL) di fase lanjutan.
- Registrasi memberi tahu bila username sudah dipakai (409), sehingga username bisa ditebak.
- Ini kerangka dasar yang masuk akal, bukan hasil audit keamanan independen. Untuk aplikasi
  yang menyimpan data sensitif, lakukan review sendiri sebelum dipublikasikan.
