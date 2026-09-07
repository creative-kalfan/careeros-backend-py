FROM python:3.11-slim

WORKDIR /app

# System deps for pymupdf, docx compilation, and headless LibreOffice
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libreoffice-writer-nogui default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Single-process entrypoint: Uvicorn as PID 1 (ARQ worker runs in a separate service).
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 10000

CMD ["./start.sh"]
