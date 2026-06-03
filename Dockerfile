FROM python:3.11-slim

WORKDIR /app

# System deps (sentence-transformers / chromadb need build basics)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Writable caches for the embedding model / HF hub (HF Spaces friendly)
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    PYTHONUTF8=1
RUN mkdir -p /app/.cache && chmod -R 777 /app/.cache

EXPOSE 7860

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
