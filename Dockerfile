# Usiamo una versione completa di Python, non la "slim", per avere già i compilatori pronti
FROM python:3.11-bullseye

# Ottimizzazioni per i log e per evitare file inutili
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Installa Tesseract e le dipendenze per le librerie grafiche/vettoriali
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Aggiorna pip e installa le dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# Esponi la porta (documentativo)
EXPOSE 8080

# Avvia l'API
CMD ["python", "api.py"]
