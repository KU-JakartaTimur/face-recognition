FROM python:3.11-slim

# Runtime libs yang dibutuhkan opencv-headless (libglib) dan dlib (libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    tzdata \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Jakarta \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KNOWN_FACES_DIR=/app/writable/faces

WORKDIR /app

COPY requirements.txt /app/requirements.txt

# face_recognition dipasang --no-deps agar pip tidak mencoba build `dlib`
# dari source; dlib sudah tersedia lewat wheel `dlib-bin` di requirements.txt.
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install --no-deps face_recognition==1.3.0

COPY main.py /app/main.py

# Folder wajah sebaiknya di-mount sebagai volume agar tidak ikut hilang saat
# container dibuat ulang.
RUN mkdir -p /app/writable/faces
VOLUME ["/app/writable/faces"]

EXPOSE 5000

# -w 1 wajib: cache wajah hidup di memori proses, jadi dengan lebih dari satu
# worker hasil /catch-face hanya terlihat oleh worker yang menanganinya.
# FastAPI = ASGI, jadi gunicorn perlu worker class uvicorn.
CMD ["gunicorn", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:5000", "--timeout", "120", "main:app"]
