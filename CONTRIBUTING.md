# Berkontribusi ke SimPy.ts

Terima kasih sudah tertarik! Proyek ini dibuat sebagai bahan belajar sekaligus produk open-source,
jadi kode yang jelas, test, dan dokumentasi sama pentingnya dengan fitur.

## Menyiapkan lingkungan

Butuh Python >= 3.11 dan Node >= 22.18.

```bash
git clone <url-repo-kamu> SimPy.ts && cd SimPy.ts
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
npm install
```

Di Termux/Android: `pip install -e . pytest` (paket `ruff` sering gagal dipasang di sana).
Lihat [docs/termux.md](docs/termux.md).

## Sebelum membuka Pull Request

```bash
ruff check .          # lint Python
pytest                # test backend dan CLI
npm run typecheck     # tsc untuk src/frontend
npm test              # test frontend (node --test)
bash scripts/smoke.sh # opsional: uji end-to-end dengan server sungguhan
```

Aturan singkat:

- Setiap fitur atau perbaikan disertai test. Test yang mengubah perilaku keamanan wajib ada.
- Jangan menambah dependensi tanpa alasan jelas (Termux dan pemasangan sederhana jadi pertimbangan).
- `examples/hello-world` harus identik dengan hasil `simpy create hello-world --dir examples`
  (ada test yang memeriksa ini). Ubah template di `cli/simpy_cli/templates/default/`, lalu buat ulang contohnya.
- Kode TypeScript runtime memakai sintaks yang bisa dijalankan Node langsung (tanpa `enum`,
  `namespace`, atau parameter property) dan impor dengan ekstensi `.ts`.
- Jelaskan APA yang berubah dan KENAPA di deskripsi PR.
- Temuan keamanan dilaporkan secara privat, lihat [SECURITY.md](SECURITY.md).
