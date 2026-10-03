FROM python:3.12-slim

# ffmpeg (with libass for burned-in captions) + a font that matches "Arial"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-liberation fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY clipper.py bot.py ./

# Whisper models download here on first run; mounted as a volume so restarts don't re-download
ENV HF_HOME=/models
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
