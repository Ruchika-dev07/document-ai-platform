"""FastAPI entrypoint for the IDP platform."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import upload, documents

app = FastAPI(title="Enterprise IDP Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(documents.router)

os.makedirs("uploads/page_thumbnails", exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory="uploads/page_thumbnails"), name="thumbnails")


@app.get("/")
def serve_frontend():
    return FileResponse("frontend/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}