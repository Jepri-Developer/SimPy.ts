# Menjalankan SimPy.ts di Termux (Android)

Seluruh fase pengembangan diuji di Termux (Python 3.14, Node 26). Catatan yang terbukti:

```bash
pkg update && pkg install python git nodejs
python -m venv .venv && source .venv/bin/activate
pip install -e . pytest
```

- **Kerjakan di folder home** (`~`), bukan di `~/storage/downloads`. Penyimpanan bersama
  Android tidak mendukung symlink sehingga `python -m venv` gagal.
- `/tmp` tidak bisa ditulis di Termux; gunakan `~`.
- Pasang `pytest` terpisah. Paket `ruff` sering tidak punya wheel untuk Android.
- Tidak ada dependensi Python berbasis Rust: sebab itulah validasi input memakai modul bawaan
  (bukan Pydantic) dan password di-hash dengan `hashlib.scrypt`.
- Node >= 22.18 dibutuhkan untuk `npm test` (menjalankan TypeScript langsung).
- Gunakan TypeScript 5.x (sudah diatur di template). TypeScript versi terbaru yang berbasis
  binary native belum menyediakan paket untuk Android.
- Peringatan `npm warn install-scripts ... esbuild` aman diabaikan; esbuild tetap berfungsi.
- Server dev hanya mendengarkan `127.0.0.1`; buka `http://127.0.0.1:8000` di browser HP.
