# Face Recognition API

Service Flask untuk verifikasi wajah menggunakan library `face_recognition` (berbasis dlib). Menerima gambar berbasis base64 dan membandingkannya dengan wajah-wajah yang sudah terdaftar di server.

> **Sumber awal:** [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) — dimodifikasi oleh **mdestafadilah**.

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
│  decode base64   │────▶│  known_faces/           │
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

---

## Endpoint

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
  "name": "nama_file_tanpa_ekstensi"
}
```

**Response — Gagal (400):**

```json
{
  "status": "error",
  "message": "Wajah tidak terdeteksi!"
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

---

## Setup & Menjalankan

### Prerequisites

- Python 3.10+
- `cmake` (jika install dlib dari source — tidak perlu jika pakai `dlib-bin`)

### Instalasi Manual

```bash
cd D:\PYTHON-DEV\face_recognition

# Install dependency utama
pip install -r requirements.txt

# Install face_recognition tanpa deps (sudah pakai dlib-bin)
pip install --no-deps face_recognition==1.3.0
```

### Jalankan

```bash
# Default: host 0.0.0.0, port 5000
python face_api.py
```

Server akan memuat semua wajah dari folder `writable/faces/` saat startup, lalu mendengarkan di `http://0.0.0.0:5000`.

### Konfigurasi

Variabel environment yang didukung:

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `KNOWN_FACES_DIR` | `writable/faces` | Path folder berisi gambar wajah terdaftar |

---

## Dependencies

| Paket | Versi | Keterangan |
|-------|-------|------------|
| flask | 3.0.3 | Web framework |
| gunicorn | 22.0.0 | WSGI server untuk production |
| numpy | 1.26.4 | Operasi array gambar |
| Pillow | 10.4.0 | Load gambar |
| opencv-python-headless | 4.10.0.84 | Decode & konversi gambar (BGR↔RGB) |
| dlib-bin | >=19.24.2 | Wheel siap pakai untuk dlib |
| face-recognition-models | 0.3.0 | Model wajah bawaan dlib |
| face_recognition | 1.3.0 | Library utama (install manual, `--no-deps`) |

---

## Deployment (Docker)

Dockerfile terpisah (`Dockerfile.face-api`) tersedia untuk deployment container. Dockerfile tersebut menginstal `dlib-bin` (wheel) terlebih dahulu, lalu `face_recognition` dengan `--no-deps` agar proses build tidak memakan waktu lama.

---

## Lisensi

Proyek ini dimodifikasi dari [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) oleh mdestafadilah. Merujuk pada lisensi dari repositori asli.
