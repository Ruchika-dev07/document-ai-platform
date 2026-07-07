"""FastAPI entrypoint for the IDP platform."""
from fastapi import FastAPI

app = FastAPI(title="Enterprise IDP Platform")


@app.get("/health")
def health_check():
    return {"status": "ok"}
