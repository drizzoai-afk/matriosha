from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Matriosha API is running"}

if __name__ == "__main__":
    import uvicorn
    # Cloud Run passa la porta come variabile d'ambiente
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
