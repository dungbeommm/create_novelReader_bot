# Python 3.10 la bat buoc: piper-phonemize chi co ban wheel cho Python <= 3.10
FROM python:3.10-slim

# espeak-ng ho tro phoneme hoa (piper-phonemize da bundle san, day la insurance them)
RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 2 --timeout 180 --bind 0.0.0.0:$PORT"]
