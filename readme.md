# Face Recognition API

Service Flask untuk verifikasi wajah menggunakan library `face_recognition` (berbasis dlib). Menerima gambar base64 dan membandingkannya dengan wajah-wajah yang sudah terdaftar di folder `writable/faces/`.

> **Sumber awal:** [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) — dimodifikasi oleh **mdestafadilah**.

---

## Struktur Project

```
face_recognition/
├── face_api.py          # Service Flask (entry point)
├── requirements.txt     # Dependensi Python
├── .gitignore
└── writable/
    └── faces/           # Folder wajah terdaftar (kosong, isi via /catch-face)
        └── .gitkeep
```

---

## Arsitektur

```
POST /verify-face (JSON: base64 image)
        │
        ▼
┌──────────────────┐
│   face_api.py    │
│  (Flask + dlib)  │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  decode base64   │────▶│  writable/faces/        │
│  → OpenCV BGR    │     │  (wajah terdaftar)      │
│  → RGB           │     │  filename = nama orang   │
└──────┬───────────┘     └─────────────────────────┘
       │
       ▼
┌──────────────────┐
│ face_encodings() │
│ compare_faces()  │
└──────┬───────────┘
       │
       ▼
  { status, name } atau { status, message }
```

Cache wajah (`known_face_encodings` & `known_face_names`) dimuat sekali saat startup dari `writable/faces/`, lalu dimutasi oleh endpoint `/catch-face` dengan pelindung `threading.Lock` agar race-free.

---

## Endpoint

### `GET /`

Informasi service & jumlah wajah terdaftar.

**Response (200):**

```json
{
  "status": "success",
  "message": "Face Recognition API Service is Running!",
  "registered_faces": 4
}
```

### `GET /health`

Health check ringan. Return `{"status": "ok"}` (200) jika service hidup.

### `POST /verify-face`

Verifikasi wajah dari gambar base64.

**Request Body (JSON):**

```json
{
  "face_encoding": "data:image/jpeg;base64,/9j/4AAQ..."
}
```

> Field `face_encoding` harus dalam format data URI (`data:image/...;base64,...`).

**Response — Berhasil (200):**

```json
{
  "status": "success",
  "name": "budi"
}
```

**Kemungkinan pesan error:**

| Kode | Pesan | Penyebab |
|------|-------|----------|
| 400 | Gambar tidak dapat diproses! | Base64 tidak valid atau corrupt |
| 400 | Wajah tidak terdeteksi! | Tidak ada wajah dalam gambar |
| 400 | Wajah tidak dikenali! | Wajah ada tapi tidak cocok dengan yang terdaftar |
| 500 | (pesan exception) | Error internal server |

---

### `POST /catch-face`

Daftarkan foto master baru ke folder `writable/faces/`. Foto harus berisi **tepat satu wajah**, dan server menolak wajah yang sudah terdaftar atas nama lain.

**Request Body (JSON):**

```json
{
  "face_encoding": "data:image/jpeg;base64,/9j/4AAQ...",
  "name": "budi",
  "overwrite": false
}
```

| Field | Wajib | Keterangan |
|-------|-------|------------|
| `face_encoding` | ya | Data URI atau base64 polos |
| `name` | tidak | Nama orang; jadi nama file dan nama yang dikembalikan `/verify-face`. Karakter selain `A-Z a-z 0-9 _ . -` dibuang, spasi jadi `_`. Jika kosong, dipakai `captured_<timestamp>_<hash>` |
| `overwrite` | tidak | `true` untuk menimpa nama yang sudah terdaftar (atau ekstensi lain dari nama yang sama) |

**Response — Berhasil (201):**

```json
{
  "status": "success",
  "message": "Foto berhasil disimpan!",
  "name": "budi",
  "filename": "budi.jpg",
  "registered_faces": 4
}
```

**Kemungkinan pesan error:**

| Kode | Pesan | Penyebab |
|------|-------|----------|
| 400 | Field 'face_encoding' wajib diisi! | Body kosong / field hilang |
| 400 | Gambar tidak dapat diproses! | Base64 tidak valid atau corrupt |
| 400 | Wajah tidak terdeteksi! | Tidak ada wajah dalam gambar |
| 400 | Terdeteksi N wajah, ... | Lebih dari satu wajah dalam foto |
| 400 | Nama tidak valid! | `name` habis setelah sanitasi (mis. hanya simbol / non-ASCII) |
| 409 | Nama '...' sudah terdaftar | Nama sudah ada, `overwrite` tidak diset |
| 409 | Wajah ini sudah terdaftar sebagai '...' | Wajah cocok dengan orang lain yang sudah terdaftar |
| 500 | Gagal menyimpan foto! | Folder tidak bisa ditulis |

> Cache wajah in-memory diperbarui langsung tanpa reload seluruh folder. Pada gunicorn multi-worker, wajah baru hanya terlihat oleh worker yang menerima request — worker lain baru ikut setelah restart.

---

## Struktur Folder Wajah

```
writable/faces/
├── budi.jpg        → terdaftar sebagai "budi"
├── ani.png         → terdaftar sebagai "ani"
├── citra.jpeg      → terdaftar sebagai "citra"
└── .gitkeep        → diabaikan (bukan ekstensi gambar)
```

**Aturan penamaan:**
- Nama file = nama yang dikembalikan dalam response (tanpa ekstensi).
- Ekstensi yang didukung: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`.
- File non-gambar dan file yang rusak otomatis dilewati saat startup.
- Saat `/catch-face` dengan `overwrite=true`, file lama dengan nama sama & ekstensi lain akan dihapus agar tidak muncul duplikat.

---

## Setup & Menjalankan

### Prerequisites

- Python 3.10+
- `cmake` (hanya jika install `dlib` dari source — tidak perlu jika pakai `dlib-bin` wheel)

### Foto Master

- Simpan foto di folder `writable/faces/` (bertambah otomatis saat service jalan), **atau**
- Gunakan endpoint `POST /catch-face` untuk mendaftarkan foto dari aplikasi lain.

### Instalasi (Windows / lokal)

```bash
cd D:\PYTHON-DEV\face_recognition

# Install dependency utama
pip install -r requirements.txt

# Install face_recognition tanpa deps (sudah pakai dlib-bin dari requirements.txt)
pip install --no-deps face_recognition==1.3.0
```

Catatan: `face_recognition` sengaja tidak ada di `requirements.txt` karena metadata PyPI-nya menarik `dlib` (build dari source, ~15 menit + butuh `cmake`). `requirements.txt` sudah memakai `dlib-bin` (wheel jadi `dlib`), jadi cukup install `face_recognition` dengan `--no-deps`.

### Instalasi (Linux / server, bila dlib perlu di-build dari source)

```bash
cd /www/wwwroot/face_recognition
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Tambah swap sementara agar build dlib tidak kehabisan RAM
sudo fallocate -l 2G /swapfile_temp
sudo chmod 600 /swapfile_temp
sudo mkswap /swapfile_temp
sudo swapon /swapfile_temp

export MAKEFLAGS="-j1"
export DLIB_NO_GUI_SUPPORT=1
export CFLAGS="-mno-avx"
# ~5–10 menit
venv/bin/pip install dlib --no-cache-dir

# Bersihkan swap
sudo swapoff /swapfile_temp
sudo rm /swapfile_temp

# Verifikasi
venv/bin/python -c "import dlib; import face_recognition; print('BERHASIL!')"

# Jalankan service
venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 face_api:app
```

### Jalankan (dev)

```bash
python face_api.py
```

Default: bind ke `127.0.0.1:5000` (lihat `if __name__ == "__main__"` di `face_api.py`).

### Konfigurasi (Environment Variables)

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `KNOWN_FACES_DIR` | `writable/faces` | Path folder berisi gambar wajah terdaftar |
| `FACE_TOLERANCE` | `0.6` | Jarak maksimum agar dua encoding dianggap orang yang sama (default dlib). Dipakai di `/verify-face` via `compare_faces` dan di `/catch-face` untuk deteksi duplikat lintas-nama |

---

## Dependencies

Diambil dari `requirements.txt`:

| Paket | Versi | Keterangan |
|-------|-------|------------|
| flask | 3.0.3 | Web framework |
| gunicorn | 22.0.0 | WSGI server untuk production |
| numpy | 1.26.4 | Operasi array gambar |
| Pillow | 10.4.0 | Load gambar |
| click | 8.1.7 | Dependency Flask CLI |
| opencv-python-headless | 4.10.0.84 | Decode & konversi gambar (BGR↔RGB), tanpa GUI |
| dlib-bin | >=19.24.2 | Wheel siap pakai untuk dlib (modul Python tetap `dlib`) |
| face-recognition-models | 0.3.0 | Model wajah bawaan dlib |
| face_recognition | 1.3.0 | Library utama — **diinstal manual** dengan `pip install --no-deps` (tidak ada di `requirements.txt`) |

---

## Catatan Keamanan

- Sanitasi nama: hanya `[A-Za-z0-9 _.-]` lolos, dan strip di-trim; mencegah path traversal saat dipakai sebagai nama file.
- Folder `writable/faces/` dibuat otomatis (`os.makedirs(..., exist_ok=True)`) — pastikan proses punya izin tulis.
- `threading.Lock` melindungi mutation cache saat `/catch-face` berjalan paralel dengan `/verify-face`.

---

## Lisensi

Proyek ini dimodifikasi dari [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) oleh **mdestafadilah**. Merujuk pada lisensi dari repositori asli.
