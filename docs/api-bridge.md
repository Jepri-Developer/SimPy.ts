# Jembatan backend ↔ frontend (Fase 4)

Route Python menjadi satu-satunya sumber kebenaran. `simpy generate` membaca route dan Schema,
lalu menulis klien TypeScript bertipe di `.simpy/api.ts`.

## Dari Python ke TypeScript

```python
class GreetInput(Schema):
    name: str = field(min_length=1, max_length=50)

class Message(Schema):
    message: str

@app.post("/api/greet")
def greet(data: GreetInput) -> Message:
    return {"message": f"Halo, {data.name}!"}
```

```ts
import { api } from "simpy-ts/api";
const reply = await api.greet({ name: "Ani" });   // reply: Message
await api.greet({ nama: "Ani" });                  // error tsc: 'nama' tidak dikenal
```

- Nama fungsi klien = nama fungsi handler dalam camelCase (`get_user` jadi `getUser`).
- Parameter path menjadi argumen berurutan (`getUser(userId: number)`); body Schema menjadi
  argumen terakhir. GET tidak boleh punya body.
- Handler yang didaftarkan ke beberapa method mendapat akhiran method (`thingGet`, `thingPost`).

## Tipe respons = anotasi return

| Anotasi | Tipe klien | Dicek saat runtime |
|---|---|---|
| `-> Message` | `Message` | ya |
| `-> list[Message]` | `Message[]` | ya |
| `-> None` | `void` (204) | - |
| `-> dict` / `dict[str, T]` | `Record<string, ...>` | tidak |
| `-> str`, `int`, `float`, `bool` | tipe dasar | tidak |
| tanpa anotasi / `-> Response` | `unknown` | tidak |

Handler boleh mengembalikan `dict` untuk `-> Message`; dict itu divalidasi menjadi `Message`
(field kurang atau berlebih = bug server, jawabannya 500 generik, detailnya hanya di log).
Ini menjaga janji tipe ke frontend. `(data, status)` tetap didukung. Tipe return utama tidak
boleh Optional (pakai `-> None` untuk 204).

## Bentuk tipe input vs output

Satu Schema yang dipakai sebagai body dan sebagai respons menghasilkan dua interface:
`Name` (respons, semua field wajib) dan `NameInput` (body, field ber-default menjadi opsional).
Bila hanya dipakai satu peran, namanya tetap `Name`. Dua kelas berbeda dengan nama sama
ditolak saat generate.

## Error di klien

```ts
import { ApiError } from "simpy-ts/frontend";
try { await api.greet({ name: "" }); }
catch (e) {
  if (e instanceof ApiError && e.status === 422) console.log(e.details); // [{loc, msg}]
}
```

`ApiError` punya `status` (0 = server tak terjangkau), `code`, `message`, dan `details`.
Klien hanya mengakses path satu origin, tidak bisa dipakai untuk menembak situs lain.

## Kapan klien dibuat

- `simpy dev` dan `simpy build` membuatnya otomatis di awal.
- Setelah mengubah route atau Schema: `simpy generate` (esbuild `--watch` ikut membangun ulang)
  atau restart `simpy dev`.
- Generator mengimpor `app/routes.py`, jadi butuh `SIMPY_SECRET_KEY` valid (dari `.env`).

## Halaman interaktif

```ts
export default definePage({
  render: () => html`<form>...</form><p id="result"></p>`,
  mount(root) {                         // dipanggil setelah HTML masuk DOM
    root.querySelector("form")?.addEventListener("submit", async (e) => { ... });
    return () => { /* pembersihan opsional sebelum pindah halaman */ };
  },
});
```

Tulis hasil API ke DOM dengan `textContent`, bukan `innerHTML`.

## Belum ada (fase berikutnya)

CSRF token otomatis dan rate limiting (Fase 5); query string sebagai parameter bertipe;
regenerasi klien otomatis saat route berubah di tengah `simpy dev`.
