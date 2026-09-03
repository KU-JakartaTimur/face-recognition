# Face Recognition API

Service FastAPI untuk verifikasi wajah menggunakan library `face_recognition` (berbasis dlib). Menerima gambar base64 dan membandingkannya dengan wajah-wajah yang sudah terdaftar di folder `writable/faces/`.

> **Sumber awal:** [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) — dimodifikasi oleh **mdestafadilah**.

---

## Struktur Project

```
face_recognition/
├── main.py              # Service FastAPI (entry point)
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
│   main.py        │
│ (FastAPI + dlib) │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  decode base64   │────▶│  writable/faces/        │
│  → OpenCV BGR    │     │  (wajah terdaftar)      │
│  → downscale     │     │  filename = nama orang   │
│  → RGB           │     └─────────────────────────┘
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ face_encodings() │
│ face_distance()  │  ← ambil jarak terkecil, lalu
└──────┬───────────┘    bandingkan dengan FACE_TOLERANCE
       │
       ▼
  { status, name, distance } atau { status, message }
```

Cache wajah (`known_face_encodings` & `known_face_names`) dimuat sekali saat startup dari `writable/faces/`, lalu dimutasi oleh endpoint `/catch-face` di bawah `threading.Lock`. `/verify-face` menyalin kedua list di bawah lock yang sama sebelum mencocokkan, sehingga tidak pernah membaca cache yang baru terisi separuh (encoding sudah ditambah, nama belum).

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

> Field `face_encoding` menerima data URI (`data:image/...;base64,...`) maupun base64 polos.

**Response — Berhasil (200):**

```json
{
  "status": "success",
  "name": "budi",
  "distance": 0.3812
}
```

`distance` adalah jarak euclidean ke encoding yang paling mirip (makin kecil makin yakin); nilainya selalu ≤ `FACE_TOLERANCE`. Kalau gambar berisi beberapa wajah, yang dilaporkan adalah pasangan dengan jarak terkecil.

**Kemungkinan pesan error:**

| Kode | Pesan | Penyebab |
|------|-------|----------|
| 400 | Body harus berupa JSON yang valid! | Body bukan JSON |
| 400 | Body harus berupa objek JSON! | Body JSON tapi bukan object (mis. array) |
| 400 | Field 'face_encoding' wajib diisi! | Field hilang atau kosong |
| 400 | Gambar tidak dapat diproses! | Base64 tidak valid atau corrupt |
| 400 | Wajah tidak terdeteksi! | Tidak ada wajah dalam gambar |
| 400 | Wajah tidak dikenali! | Wajah ada tapi jarak terdekat > `FACE_TOLERANCE`, atau belum ada wajah terdaftar |
| 413 | Gambar melebihi batas N byte! | Payload lebih besar dari `MAX_IMAGE_BYTES` |
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
| `name` | tidak | Nama orang; jadi nama file dan nama yang dikembalikan `/verify-face`. Karakter selain `A-Z a-z 0-9 _ . -` dibuang, spasi jadi `_`, dan nama device Windows (`CON`, `NUL`, `COM1`, …) ditolak. Jika kosong, dipakai `captured_<timestamp>_<hash>` |
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
| 400 | Body harus berupa JSON yang valid! | Body bukan JSON |
| 400 | Body harus berupa objek JSON! | Body JSON tapi bukan object (mis. array) |
| 400 | Field 'face_encoding' wajib diisi! | Body kosong / field hilang |
| 400 | Gambar tidak dapat diproses! | Base64 tidak valid atau corrupt |
| 400 | Wajah tidak terdeteksi! | Tidak ada wajah dalam gambar |
| 400 | Terdeteksi N wajah, ... | Lebih dari satu wajah dalam foto |
| 400 | Nama tidak valid! | `name` habis setelah sanitasi (mis. hanya simbol / non-ASCII) atau nama device Windows |
| 409 | Nama '...' sudah terdaftar | Nama sudah ada di cache **atau** filenya ada di disk, dan `overwrite` tidak diset |
| 409 | Wajah ini sudah terdaftar sebagai '...' | Wajah cocok dengan orang lain yang sudah terdaftar |
| 413 | Gambar melebihi batas N byte! | Payload lebih besar dari `MAX_IMAGE_BYTES` |
| 500 | Gagal menyimpan foto! | Folder tidak bisa ditulis |

> Cache wajah in-memory diperbarui langsung tanpa reload seluruh folder. Karena cache itu hidup di memori proses, service ini harus jalan **single-process**: dengan multi-worker, wajah baru hanya terlihat oleh worker yang menerima request — worker lain baru ikut setelah restart.

> Foto disimpan setelah dikecilkan ke `MAX_DETECT_SIZE` (sisi terpanjang), sama persis dengan gambar yang dipakai menghitung encoding. Jadi encoding hasil reload saat restart identik dengan yang dipakai saat pendaftaran.

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
- `setuptools` (ada di `requirements.txt`). Pada Python 3.12+ `venv` tidak lagi
  memasangnya otomatis, dan tanpa itu `face_recognition_models` gagal impor dengan
  `ModuleNotFoundError: No module named 'pkg_resources'`

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
pip install gunicorn uvicorn

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

# Jalankan service (FastAPI = ASGI, jadi gunicorn butuh worker class uvicorn).
# -w 1 wajib: cache wajah ada di memori proses, lihat catatan /catch-face di atas.
venv/bin/gunicorn -w 1 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:5000 main:app

# Alternatif tanpa gunicorn
venv/bin/pip install --no-deps face_recognition==1.3.0
venv/bin/uvicorn main:app --host 127.0.0.1 --port 5000
```

### Jalankan (dev)

```bash
python main.py
```

Default: bind ke `127.0.0.1:5000` (lihat `if __name__ == "__main__"` di `main.py`).

### Konfigurasi (Environment Variables)

| Variabel | Default | Deskripsi |
|----------|---------|-----------|
| `KNOWN_FACES_DIR` | `writable/faces` | Path folder berisi gambar wajah terdaftar |
| `FACE_TOLERANCE` | `0.6` | Jarak maksimum agar dua encoding dianggap orang yang sama (default dlib). Dipakai di `/verify-face` untuk memutuskan match dan di `/catch-face` untuk deteksi duplikat lintas-nama — keduanya lewat `face_distance` |
| `MAX_IMAGE_BYTES` | `8388608` (8 MB) | Batas ukuran gambar setelah decode base64; lebih dari ini ditolak 413 sebelum di-decode |
| `MAX_DETECT_SIZE` | `1600` | Sisi terpanjang gambar sebelum deteksi wajah. Gambar lebih besar dikecilkan dulu supaya `face_locations()` (CPU) tidak menahan worker |

---

## Dependencies

Diambil dari `requirements.txt`:

| Paket | Versi | Keterangan |
|-------|-------|------------|
| fastapi | 0.115.6 | Web framework (ASGI) |
| uvicorn | 0.32.1 | ASGI server; dipakai langsung atau sebagai worker class gunicorn |
| gunicorn | 22.0.0 | Process manager untuk production (butuh `-k uvicorn.workers.UvicornWorker`) |
| numpy | 1.26.4 | Operasi array gambar |
| Pillow | 10.4.0 | Load gambar |
| opencv-python-headless | 4.10.0.84 | Decode & konversi gambar (BGR↔RGB), tanpa GUI |
| dlib-bin | >=19.24.2 | Wheel siap pakai untuk dlib (modul Python tetap `dlib`) |
| face-recognition-models | 0.3.0 | Model wajah bawaan dlib |
| face_recognition | 1.3.0 | Library utama — **diinstal manual** dengan `pip install --no-deps` (tidak ada di `requirements.txt`) |

---

## Catatan Keamanan

- Sanitasi nama: hanya `[A-Za-z0-9 _.-]` lolos, titik di ujung di-trim, dan nama device Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`) ditolak — mencegah path traversal dan penulisan ke device saat dipakai sebagai nama file.
- Folder `writable/faces/` dibuat otomatis (`os.makedirs(..., exist_ok=True)`) — pastikan proses punya izin tulis.
- `threading.Lock` melindungi cache: `/catch-face` memutasi di dalam lock, `/verify-face` menyalin isinya di dalam lock sebelum mencocokkan.
- Payload dibatasi `MAX_IMAGE_BYTES` (ditolak sebelum decode) dan dikecilkan ke `MAX_DETECT_SIZE` sebelum deteksi, supaya satu gambar besar tidak menahan worker.
- Body non-JSON, field hilang, dan gambar corrupt dijawab 4xx; hanya kegagalan tak terduga yang jadi 500.

---

## Lisensi

Proyek ini dimodifikasi dari [absensi-wajah-laravel](https://github.com/alimochtar78/absensi-wajah-laravel) oleh **mdestafadilah**. Merujuk pada lisensi dari repositori asli.
