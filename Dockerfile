FROM python:3.11-slim

WORKDIR /app

# System deps for pymupdf/docx compilation. LibreOffice was purged in favor of
# the standalone Typst PDF engine (instant, no JRE, ~30MB vs ~1GB).
# A base font is required: Typst renders system fonts and the slim image
# ships none, so DejaVu is installed explicitly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev ca-certificates curl xz-utils fonts-dejavu-core && \
    curl -4 -fsSL --retry 5 --retry-all-errors --retry-delay 5 https://github.com/typst/typst/releases/download/v0.11.1/typst-x86_64-unknown-linux-musl.tar.xz \
      | tar -xJ -C /usr/local/bin --strip-components=1 typst-x86_64-unknown-linux-musl/typst && \
    typst --version && \
    apt-get purge -y curl xz-utils && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Single-process entrypoint: Uvicorn as PID 1 (ARQ worker runs in a separate service).
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 10000

CMD ["./start.sh"]
