# source: https://raw.githubusercontent.com/alimochtar78/absensi-wajah-laravel/refs/heads/main/face_recognition_api.py
# modified by: mdestafadilah
# refactored by: AI

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import face_recognition
import numpy as np
import base64
import cv2
import hashlib
import os
import re
import threading
import time

from dotenv import load_dotenv

app = FastAPI()

# Folder yang berisi wajah siswa. Default-nya diikat ke lokasi file ini, bukan
# ke cwd: dijalankan dari folder mana pun, service tetap membaca folder wajah
# yang sama (kalau relatif, "uvicorn main:app" dari folder lain diam-diam
# membaca folder kosong dan semua wajah jadi tidak dikenali).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Muat .env dari folder main.py, bukan dari cwd: sama alasannya dengan
# BASE_DIR di atas -- "uvicorn main:app" yang dijalankan dari folder lain tetap
# memakai konfigurasi yang sama. override=False (default) disengaja: env asli
# dari "docker run -e" / systemd tetap menang atas isi file.
load_dotenv(os.path.join(BASE_DIR, ".env"))

KNOWN_FACES_DIR = os.getenv("KNOWN_FACES_DIR") or os.path.join(BASE_DIR, "writable", "faces")
ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
known_face_encodings = []
known_face_names = []

# Jarak maksimum agar dua encoding dianggap orang yang sama (default dlib = 0.6)
FACE_TOLERANCE = float(os.getenv("FACE_TOLERANCE", "0.6"))

# Toleransi terpisah untuk dedup saat pendaftaran, sengaja lebih ketat.
# 0.6 divalidasi pada foto frontal beresolusi bagus; foto absensi (wajah kecil
# di frame, blur, backlight, masker) rutin menghasilkan jarak < 0.6 untuk dua
# orang yang berbeda, sehingga pendaftaran sah ditolak 409.
DUP_TOLERANCE = float(os.getenv("DUP_TOLERANCE", "0.45"))

# Foto master di-encode dengan jitter supaya hasilnya lebih stabil; ini cuma
# terjadi sekali saat pendaftaran, jadi biaya ~10x tidak terasa. Probe
# /verify-face tetap num_jitters=1 agar absensi tidak melambat -- jitter hanya
# merata-ratakan chip yang sama, jadi aman dicampur.
#
# ENCODE_MODEL beda cerita: model landmark ini yang meluruskan wajah sebelum
# di-encode, jadi nilainya HARUS sama di sisi master dan sisi probe. Kalau
# beda, chip-nya tidak sebangun dan semua jarak ikut melar.
ENCODE_MODEL = os.getenv("FACE_ENCODE_MODEL", "large")
ENCODE_JITTERS = int(os.getenv("FACE_ENCODE_JITTERS", "10"))

# Batas ukuran gambar. Tanpa ini satu request 20 MP bisa menahan worker
# beberapa detik di face_locations() yang jalan di CPU.
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))
MAX_DETECT_SIZE = int(os.getenv("MAX_DETECT_SIZE", "1600"))

# Nama device Windows: "CON.jpg" tetap diarahkan ke device, bukan ke file
_RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Cache wajah dimutasi oleh /catch-face sementara /verify-face membacanya
_faces_lock = threading.Lock()


class ApiError(Exception):
    """Kesalahan yang pesannya aman dikirim ke klien apa adanya."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _error(message, status_code=400):
    return JSONResponse({"status": "error", "message": message}, status_code=status_code)


async def _read_json(request):
    """Ambil body JSON. Body rusak = 400, bukan 500."""
    try:
        data = await request.json()
    except Exception:
        raise ApiError("Body harus berupa JSON yang valid!")
    if not isinstance(data, dict):
        raise ApiError("Body harus berupa objek JSON!")
    return data


def _decode_image(payload):
    """Decode data URI atau base64 polos menjadi gambar OpenCV (BGR)."""
    if not isinstance(payload, str) or not payload.strip():
        raise ApiError("Field 'face_encoding' wajib diisi!")

    b64 = payload.split(",", 1)[1] if payload.startswith("data:") else payload

    # Cek panjang base64 dulu supaya payload raksasa ditolak sebelum di-decode
    if len(b64) > MAX_IMAGE_BYTES // 3 * 4 + 4:
        raise ApiError(f"Gambar melebihi batas {MAX_IMAGE_BYTES} byte!", 413)

    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise ApiError("Gambar tidak dapat diproses!")

    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ApiError("Gambar tidak dapat diproses!")
    return img


def _downscale(img):
    """Kecilkan sisi terpanjang ke MAX_DETECT_SIZE agar deteksi tidak kelamaan."""
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= MAX_DETECT_SIZE:
        return img
    scale = MAX_DETECT_SIZE / longest
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def _safe_name(name):
    """Bersihkan nama agar aman dipakai sebagai nama file (cegah path traversal)."""
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip(" .").replace(" ", "_")
    if cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        return ""
    return cleaned


def _stored_files(person):
    """File di disk yang memakai nama ini, apa pun ekstensinya."""
    paths = [os.path.join(KNOWN_FACES_DIR, person + ext) for ext in ALLOWED_EXT]
    return [path for path in paths if os.path.exists(path)]


def _snapshot_faces():
    """Salin cache di bawah lock supaya pembaca tak melihat list setengah jadi."""
    with _faces_lock:
        return list(known_face_encodings), list(known_face_names)


def _scan_faces_dir():
    """Baca seluruh folder wajah dari disk dan hasilkan (encodings, names).

    File non-gambar (mis. .gitkeep) dan file rusak dilewati agar service tetap
    jalan. Sengaja tidak menyentuh cache global supaya pemanggil bisa melakukan
    pekerjaan berat ini di luar lock.
    """
    encodings = []
    names = []
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    for filename in sorted(os.listdir(KNOWN_FACES_DIR)):
        if not filename.lower().endswith(ALLOWED_EXT):
            continue
        try:
            image = face_recognition.load_image_file(os.path.join(KNOWN_FACES_DIR, filename))
            encoding = face_recognition.face_encodings(
                image, num_jitters=ENCODE_JITTERS, model=ENCODE_MODEL
            )
        except Exception as e:
            print(f"[face-api] Gagal memuat {filename}: {e}")
            continue
        if encoding:
            encodings.append(encoding[0])
            names.append(os.path.splitext(filename)[0])  # Nama file = Nama siswa
    return encodings, names


# Load semua wajah yang sudah didaftarkan.
known_face_encodings, known_face_names = _scan_faces_dir()

print(f"[face-api] {len(known_face_names)} wajah terdaftar dimuat dari {KNOWN_FACES_DIR}")

@app.get("/")
def index():
    return {
        "status": "success",
        "message": "Face Recognition API Service is Running!",
        "registered_faces": len(known_face_names),
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/verify-face")
async def verify_face(request: Request):
    """Cocokkan wajah pada gambar dengan wajah yang sudah terdaftar.

    Body JSON:
      face_encoding : data URI / base64 gambar (wajib)
    """
    try:
        data = await _read_json(request)
        img = _decode_image(data.get("face_encoding"))

        # Konversi BGR (OpenCV) -> RGB (face_recognition)
        img_rgb = cv2.cvtColor(_downscale(img), cv2.COLOR_BGR2RGB)

        # Cari wajah dalam gambar
        face_locations = face_recognition.face_locations(img_rgb)
        face_encodings = face_recognition.face_encodings(
            img_rgb, face_locations, model=ENCODE_MODEL
        )

        if not face_encodings:
            return _error("Wajah tidak terdeteksi!")

        known_encodings, known_names = _snapshot_faces()
        if not known_encodings:
            return _error("Wajah tidak dikenali!")

        # Pilih kandidat berjarak terkecil, bukan yang pertama cocok, supaya
        # urutan file tidak menentukan siapa yang menang saat dua orang mirip
        best_name = None
        best_distance = None
        for face_encoding in face_encodings:
            distances = face_recognition.face_distance(known_encodings, face_encoding)
            nearest = int(np.argmin(distances))
            if best_distance is None or distances[nearest] < best_distance:
                best_name = known_names[nearest]
                best_distance = float(distances[nearest])

        if best_distance <= FACE_TOLERANCE:
            return {
                "status": "success",
                "name": best_name,
                "distance": round(best_distance, 4),
            }

        return _error("Wajah tidak dikenali!")

    except ApiError as e:
        return _error(e.message, e.status_code)
    except Exception as e:
        return _error(str(e), 500)

@app.post("/catch-face")
async def catch_face(request: Request):
    """Daftarkan foto master baru ke KNOWN_FACES_DIR.

    Body JSON:
      face_encoding : data URI / base64 gambar (wajib)
      name          : nama orang, dipakai sebagai nama file (opsional)
      overwrite     : true untuk menimpa nama yang sudah ada (opsional)
    """
    try:
        data = await _read_json(request)
        img = _decode_image(data.get("face_encoding"))

        # Simpan versi yang sudah dikecilkan agar encoding hasil reload saat
        # restart identik dengan yang dipakai sekarang
        img = _downscale(img)

        # Konversi BGR (OpenCV) -> RGB (face_recognition)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Foto master harus berisi tepat satu wajah
        face_locations = face_recognition.face_locations(img_rgb)
        if not face_locations:
            return _error("Wajah tidak terdeteksi!")
        if len(face_locations) > 1:
            return _error(
                f"Terdeteksi {len(face_locations)} wajah, foto master harus berisi satu wajah!"
            )

        encoding = face_recognition.face_encodings(
            img_rgb, face_locations, num_jitters=ENCODE_JITTERS, model=ENCODE_MODEL
        )[0]

        # Tentukan nama terdaftar (= nama file tanpa ekstensi)
        raw_name = (data.get("name") or "").strip()
        if raw_name:
            person = _safe_name(raw_name)
            if not person:
                return _error("Nama tidak valid!")
        else:
            person = f"captured_{int(time.time())}_{hashlib.md5(encoding.tobytes()).hexdigest()[:8]}"

        filename = f"{person}.jpg"
        filepath = os.path.join(KNOWN_FACES_DIR, filename)
        overwrite = bool(data.get("overwrite"))

        with _faces_lock:
            # Cek disk juga, bukan cuma cache: file yang gagal di-encode saat
            # startup tidak ada di known_face_names tapi tetap tidak boleh
            # ditimpa diam-diam
            if not overwrite and (person in known_face_names or _stored_files(person)):
                return _error(
                    f"Nama '{person}' sudah terdaftar. Kirim overwrite=true untuk menimpa.",
                    409,
                )

            # Tolak wajah yang sudah terdaftar dengan nama lain. Jarak dan nama
            # lawannya ikut dikirim: tanpa itu 409 di produksi tidak bisa
            # dibedakan antara duplikat asli dan false positive, karena log akses
            # cuma memuat status code.
            if known_face_encodings:
                distances = face_recognition.face_distance(known_face_encodings, encoding)
                nearest = int(np.argmin(distances))
                distance = float(distances[nearest])
                if distance <= DUP_TOLERANCE and known_face_names[nearest] != person:
                    return JSONResponse({
                        "status": "error",
                        "message": f"Wajah ini sudah terdaftar sebagai '{known_face_names[nearest]}'!",
                        "matched_name": known_face_names[nearest],
                        "distance": round(distance, 4),
                        "tolerance": DUP_TOLERANCE,
                    }, status_code=409)

            # Folder bisa saja terhapus setelah service jalan; imwrite tidak
            # membuat folder induk dan hanya mengembalikan False tanpa alasan.
            os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
            if not cv2.imwrite(filepath, img):
                return _error("Gagal menyimpan foto!", 500)

            # Hapus file lama dengan nama sama tapi ekstensi berbeda agar tidak
            # muncul dua entri untuk orang yang sama saat service di-restart
            for stale in _stored_files(person):
                if stale != filepath:
                    os.remove(stale)

            # Perbarui cache in-memory tanpa reload seluruh folder
            if person in known_face_names:
                known_face_encodings[known_face_names.index(person)] = encoding
            else:
                known_face_encodings.append(encoding)
                known_face_names.append(person)

            total = len(known_face_names)

        return JSONResponse({
            "status": "success",
            "message": "Foto berhasil disimpan!",
            "name": person,
            "filename": filename,
            "registered_faces": total
        }, status_code=201)

    except ApiError as e:
        return _error(e.message, e.status_code)
    except Exception as e:
        return _error(str(e), 500)

@app.post("/forget-face")
async def forget_face(request: Request):
    """Cabut satu wajah terdaftar: hapus filenya dan keluarkan dari cache.

    Body JSON:
      name : nama terdaftar yang akan dihapus (wajib)
    """
    try:
        data = await _read_json(request)

        raw_name = (data.get("name") or "").strip()
        if not raw_name:
            raise ApiError("Field 'name' wajib diisi!")

        # Nama disanitasi dengan aturan yang sama seperti saat didaftarkan,
        # supaya "../x" tidak bisa dipakai menghapus file di luar folder wajah
        person = _safe_name(raw_name)
        if not person:
            raise ApiError("Nama tidak valid!")

        with _faces_lock:
            files = _stored_files(person)
            if person not in known_face_names and not files:
                raise ApiError(f"Nama '{person}' tidak terdaftar.", 404)

            for path in files:
                os.remove(path)

            # Cache dan disk bisa memuat nama yang sama lebih dari sekali bila
            # foldernya pernah diisi manual, jadi bersihkan semua kemunculan
            while person in known_face_names:
                index = known_face_names.index(person)
                del known_face_names[index]
                del known_face_encodings[index]

            total = len(known_face_names)

        print(f"[face-api] '{person}' dihapus, sisa {total} wajah terdaftar")

        return {
            "status": "success",
            "message": "Wajah dihapus dari daftar.",
            "name": person,
            "registered_faces": total,
        }

    except ApiError as e:
        return _error(e.message, e.status_code)
    except Exception as e:
        return _error(str(e), 500)

@app.post("/reload-faces")
def reload_faces():
    """Muat ulang cache wajah dari disk.

    Cache hanya dibangun saat startup, jadi file yang disalin manual ke
    KNOWN_FACES_DIR setelah service jalan tidak akan terbaca sampai endpoint ini
    dipanggil (atau service di-restart). Wajah yang didaftarkan lewat
    /catch-face tidak perlu ini karena cache-nya sudah diperbarui langsung.
    """
    # Scan berat (dekode gambar + encoding) sengaja di luar lock supaya
    # /verify-face tidak ikut terhenti selama pemuatan ulang berlangsung.
    encodings, names = _scan_faces_dir()

    with _faces_lock:
        # Ganti isi list, bukan rebind: /catch-face memutasi objek list yang
        # sama, jadi rebind akan membuat kedua endpoint memegang list berbeda.
        known_face_encodings[:] = encodings
        known_face_names[:] = names
        total = len(known_face_names)

    print(f"[face-api] reload: {total} wajah terdaftar dimuat dari {KNOWN_FACES_DIR}")

    return {
        "status": "success",
        "message": "Cache wajah dimuat ulang.",
        "registered_faces": total,
    }

if __name__ == "__main__":
    import uvicorn
    # Cache wajah hidup di memori proses ini, jadi jalankan single-process.
    # Dengan --workers N tiap worker punya cache sendiri dan hasil /catch-face
    # tidak terlihat oleh worker lain sampai service di-restart.
    uvicorn.run(app, host="127.0.0.1", port=5000)
