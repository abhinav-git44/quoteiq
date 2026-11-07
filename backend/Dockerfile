FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr fonts-dejavu-core libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app/backend
COPY demo_data /app/demo_data
COPY scripts /app/scripts
ENV PYTHONPATH=/app/backend STORAGE_PATH=/app/storage
EXPOSE 8000
CMD ["sh", "/app/scripts/start.sh"]
