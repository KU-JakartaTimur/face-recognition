# source: https://raw.githubusercontent.com/alimochtar78/absensi-wajah-laravel/refs/heads/main/face_recognition_api.py
# modified by: mdestafadilah

from flask import Flask, request, jsonify
import face_recognition
import numpy as np
import base64
import cv2
import hashlib
import os
import re
import threading
import time

app = Flask(__name__)

# Folder yang berisi wajah siswa
KNOWN_FACES_DIR = os.getenv("KNOWN_FACES_DIR", "writable/faces")
ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
known_face_encodings = []
known_face_names = []

# Jarak maksimum agar dua encoding dianggap orang yang sama (default dlib = 0.6)
FACE_TOLERANCE = float(os.getenv("FACE_TOLERANCE", "0.6"))

# Cache wajah dimutasi oleh /catch-face sementara /verify-face membacanya
_faces_lock = threading.Lock()


def _decode_image(payload):
    """Decode data URI atau base64 polos menjadi gambar OpenCV (BGR)."""
    b64 = payload.split(",", 1)[1] if payload.startswith("data:") else payload
    img_array = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)


def _safe_name(name):
    """Bersihkan nama agar aman dipakai sebagai nama file (cegah path traversal)."""
    return re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip(" .").replace(" ", "_")

# Load semua wajah yang sudah didaftarkan.
# File non-gambar (mis. .gitkeep) dan file rusak dilewati agar service tetap jalan.
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
for filename in sorted(os.listdir(KNOWN_FACES_DIR)):
    if not filename.lower().endswith(ALLOWED_EXT):
        continue
    try:
        image = face_recognition.load_image_file(f"{KNOWN_FACES_DIR}/{filename}")
        encoding = face_recognition.face_encodings(image)
    except Exception as e:
        print(f"[face-api] Gagal memuat {filename}: {e}")
        continue
    if encoding:
        known_face_encodings.append(encoding[0])
        known_face_names.append(os.path.splitext(filename)[0])  # Nama file = Nama siswa

print(f"[face-api] {len(known_face_names)} wajah terdaftar dimuat dari {KNOWN_FACES_DIR}")

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "success",
        "message": "Face Recognition API Service is Running!",
        "registered_faces": len(known_face_names)
    }), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/verify-face", methods=["POST"])
def verify_face():
    try:
        # Ambil data dari request
        data = request.json
        img_data = base64.b64decode(data["face_encoding"].split(",")[1])
        img_array = np.frombuffer(img_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({"status": "error", "message": "Gambar tidak dapat diproses!"}), 400

        # Konversi BGR (OpenCV) → RGB (face_recognition)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Cari wajah dalam gambar
        face_locations = face_recognition.face_locations(img)
        face_encodings = face_recognition.face_encodings(img, face_locations)

        if not face_encodings:
            return jsonify({"status": "error", "message": "Wajah tidak terdeteksi!"}), 400

        # Bandingkan wajah yang dikirim dengan yang sudah terdaftar
        for face_encoding in face_encodings:
            matches = face_recognition.compare_faces(known_face_encodings, face_encoding)
            if True in matches:
                matched_name = known_face_names[matches.index(True)]
                return jsonify({"status": "success", "name": matched_name})

        return jsonify({"status": "error", "message": "Wajah tidak dikenali!"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/catch-face", methods=["POST"])
def catch_face():
    """Daftarkan foto master baru ke KNOWN_FACES_DIR.

    Body JSON:
      face_encoding : data URI / base64 gambar (wajib)
      name          : nama orang, dipakai sebagai nama file (opsional)
      overwrite     : true untuk menimpa nama yang sudah ada (opsional)
    """
    try:
        data = request.get_json(silent=True) or {}
        payload = data.get("face_encoding")
        if not payload:
            return jsonify({"status": "error", "message": "Field 'face_encoding' wajib diisi!"}), 400

        img = _decode_image(payload)
        if img is None:
            return jsonify({"status": "error", "message": "Gambar tidak dapat diproses!"}), 400

        # Konversi BGR (OpenCV) -> RGB (face_recognition)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Foto master harus berisi tepat satu wajah
        face_locations = face_recognition.face_locations(img_rgb)
        if not face_locations:
            return jsonify({"status": "error", "message": "Wajah tidak terdeteksi!"}), 400
        if len(face_locations) > 1:
            return jsonify({
                "status": "error",
                "message": f"Terdeteksi {len(face_locations)} wajah, foto master harus berisi satu wajah!"
            }), 400

        encoding = face_recognition.face_encodings(img_rgb, face_locations)[0]

        # Tentukan nama terdaftar (= nama file tanpa ekstensi)
        raw_name = (data.get("name") or "").strip()
        if raw_name:
            person = _safe_name(raw_name)
            if not person:
                return jsonify({"status": "error", "message": "Nama tidak valid!"}), 400
        else:
            person = f"captured_{int(time.time())}_{hashlib.md5(encoding.tobytes()).hexdigest()[:8]}"

        filename = f"{person}.jpg"
        filepath = os.path.join(KNOWN_FACES_DIR, filename)
        overwrite = bool(data.get("overwrite"))

        with _faces_lock:
            if person in known_face_names and not overwrite:
                return jsonify({
                    "status": "error",
                    "message": f"Nama '{person}' sudah terdaftar. Kirim overwrite=true untuk menimpa."
                }), 409

            # Tolak wajah yang sudah terdaftar dengan nama lain
            if known_face_encodings:
                distances = face_recognition.face_distance(known_face_encodings, encoding)
                nearest = int(np.argmin(distances))
                if distances[nearest] <= FACE_TOLERANCE and known_face_names[nearest] != person:
                    return jsonify({
                        "status": "error",
                        "message": f"Wajah ini sudah terdaftar sebagai '{known_face_names[nearest]}'!"
                    }), 409

            if not cv2.imwrite(filepath, img):
                return jsonify({"status": "error", "message": "Gagal menyimpan foto!"}), 500

            # Hapus file lama dengan nama sama tapi ekstensi berbeda agar tidak
            # muncul dua entri untuk orang yang sama saat service di-restart
            for old_ext in ALLOWED_EXT:
                stale = os.path.join(KNOWN_FACES_DIR, person + old_ext)
                if old_ext != ".jpg" and os.path.exists(stale):
                    os.remove(stale)

            # Perbarui cache in-memory tanpa reload seluruh folder
            if person in known_face_names:
                known_face_encodings[known_face_names.index(person)] = encoding
            else:
                known_face_encodings.append(encoding)
                known_face_names.append(person)

            total = len(known_face_names)

        return jsonify({
            "status": "success",
            "message": "Foto berhasil disimpan!",
            "name": person,
            "filename": filename,
            "registered_faces": total
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
