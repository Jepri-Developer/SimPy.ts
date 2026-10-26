# Backend SimPy.ts (Fase 2)

## Aplikasi dan route

```python
from simpy import Schema, SimPy, field, load_settings

app = SimPy(settings=load_settings())

class GreetInput(Schema):
    name: str = field(min_length=1, max_length=50)

@app.get("/api/hello")
def hello():
    return {"message": "Hello"}

@app.post("/api/greet")
async def greet(data: GreetInput):
    return {"message": f"Halo, {data.name}!"}, 201     # (body, status)

@app.get("/api/users/{user_id:int}")
def user(user_id: int, request): ...
```

Parameter handler diisi otomatis: `request` (objek Request), nama yang ada di path
(`{user_id:int}`), dan parameter beranotasi `Schema` (body JSON tervalidasi; maksimal satu).
Parameter lain tanpa default dianggap salah dan ditolak saat definisi.

Nilai kembalian: dict/list/Schema menjadi JSON; `None` menjadi 204; `(data, status)` untuk
status kustom; objek `Response` dikirim apa adanya. `raise HTTPError(403, "pesan")` membalas
error JSON.

## Validasi input

Tipe didukung: `str`, `int`, `float`, `bool`, `list[T]`, `T | None`, dan `Schema` bersarang.
Aturan bawaan (aman by default):

- Tipe ketat: `"20"` bukan `int`, `True` bukan `int`.
- Field yang tidak dideklarasikan ditolak.
- Teks maksimal 10.000 karakter dan list maksimal 1.000 item bila tidak diatur lain.
- `float` menolak NaN dan Infinity.
- Body harus `Content-Type: application/json` (juga membantu pertahanan CSRF), maksimal
  1 MiB (`SimPy(max_body_bytes=...)`), dan tidak boleh memuat `NaN`/`Infinity`.

Batasan field: `field(min_length, max_length, ge, le, pattern, default)`.

Format error:

```json
{"error": "validation_error", "message": "Input tidak valid",
 "details": [{"loc": ["name"], "msg": "minimal 1 karakter"}]}
```

Error tak terduga (500) hanya mengembalikan pesan generik; detailnya tidak bocor ke klien.

## Konfigurasi

`load_settings()` membaca environment variable (dan `.env`; environment menang):

| Variabel | Default | Catatan |
|---|---|---|
| `SIMPY_SECRET_KEY` | wajib | aplikasi gagal start bila kosong |
| `SIMPY_ENV` | `development` | `development`, `production`, `test` |
| `SIMPY_HOST` | `127.0.0.1` | |
| `SIMPY_PORT` | `8000` | |

Di `production`, secret minimal 32 karakter dan tidak boleh nilai contoh. Buat secret:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Menjalankan

```bash
cd myapp
cp .env.example .env     # isi SIMPY_SECRET_KEY
simpy dev                # uvicorn + auto-reload
simpy dev --port 9000 --no-reload
```
