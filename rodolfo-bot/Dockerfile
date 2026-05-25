FROM python:3.11-slim

# Dependencias del sistema: ffmpeg para reproducir audio, build tools para PyNaCl
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsodium-dev \
        build-essential \
        python3-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar deps primero (capa cacheada por Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY bot.py command_parser.py ./

# Puerto del API HTTP
EXPOSE 5000

# Arrancar
CMD ["python", "-u", "bot.py"]
