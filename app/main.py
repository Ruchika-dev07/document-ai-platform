"""FastAPI entrypoint for the IDP platform."""
from fastapi import FastAPI

from app.api.routes import upload, documents

app = FastAPI(title="Enterprise IDP Platform")

app.include_router(upload.router)
app.include_router(documents.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}