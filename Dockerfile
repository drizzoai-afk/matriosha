# Usa un'immagine Python ufficiale snella
FROM python:3.11-slim

# Evita che Python generi file .pyc e assicura che i log siano visibili subito
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Installa le dipendenze di sistema (Tesseract e librerie per immagini/vettori)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Imposta la cartella di lavoro
WORKDIR /app

# Copia e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il resto del codice
COPY . .

# Comando per avviare il server sulla porta indicata da Cloud Run
CMD ["python", "api.py"]
