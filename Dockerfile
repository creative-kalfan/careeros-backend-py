FROM python:3.11-slim

WORKDIR /app

# System deps for pymupdf, docx compilation, and headless LibreOffice
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libreoffice-writer-nogui default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Default: run the FastAPI server.
# Override CMD for worker: python -m arq app.workers.settings.WorkerSettings
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
