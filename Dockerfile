FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && if [ "$WITH_CALIBRE" = "1" ]; then apt-get install -y --no-install-recommends calibre; fi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /config

EXPOSE 5000

ENV BOOK_ORGANISER_DOCKER=1 \
    PYTHONUNBUFFERED=1

CMD ["python", "app.py"]