# source: https://raw.githubusercontent.com/alimochtar78/absensi-wajah-laravel/refs/heads/main/face_recognition_api.py
# modified by: mdestafadilah

from flask import Flask, request, jsonify
import face_recognition
import numpy as np
import base64
import cv2
import os

app = Flask(__name__)

# Folder yang berisi wajah siswa
KNOWN_FACES_DIR = os.getenv("KNOWN_FACES_DIR", "writable/faces")
ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
known_face_encodings = []
known_face_names = []

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
        known_face_names.append(filename.split(".")[0])  # Nama file = Nama siswa

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

        # Simpan foto ke folder writable/faces
        # Gunakan timestamp dan hash untuk nama unik
        import hashlib
        import time
        
        timestamp = int(time.time())
        face_hash = hashlib.md5(face_encodings[0].tobytes()).hexdigest()[:8]
        filename = f"captured_{timestamp}_{face_hash}.jpg"
        filepath = os.path.join(KNOWN_FACES_DIR, filename)
        
        # Konversi kembali ke BGR untuk disimpan
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        
        # Simpan file
        success = cv2.imwrite(filepath, img_bgr)
        
        if not success:
            return jsonify({"status": "error", "message": "Gagal menyimpan foto!"}), 500

        # Tambahkan ke daftar encoding yang dikenal
        known_face_encodings.append(face_encodings[0])
        known_face_names.append(filename)

        # Reload semua wajah untuk memperbarui daftar encoding
        known_face_encodings.clear()
        known_face_names.clear()
        for f in sorted(os.listdir(KNOWN_FACES_DIR)):
            if not f.lower().endswith(ALLOWED_EXT):
                continue
            try:
                image = face_recognition.load_image_file(os.path.join(KNOWN_FACES_DIR, f))
                encoding = face_recognition.face_encodings(image)
                if encoding:
                    known_face_encodings.append(encoding[0])
                    known_face_names.append(f.split(".")[0])
            except Exception:
                continue

        return jsonify({
            "status": "success", 
            "message": "Foto berhasil disimpan!",
            "filename": filename,
            "registered_faces": len(known_face_names)
        }), 201

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
