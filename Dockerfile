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

# Crawl4AI browser layer (generic career-page crawler). Chromium system libs
# for patchright + the downloaded browser binary. Safe when unused:
# CRAWL4AI_ENABLED defaults to false and the adapter lazy-imports, so a
# missing browser degrades to the Firecrawl fallback without breaking
# worker startup. Set CRAWL4AI_ENABLED=true only after verifying this
# layer built (Chromium present).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 && \
    crawl4ai-setup && \
    rm -rf /var/lib/apt/lists/*

COPY . .

# Single-process entrypoint: Uvicorn as PID 1 (ARQ worker runs in a separate service).
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 10000

CMD ["./start.sh"]
