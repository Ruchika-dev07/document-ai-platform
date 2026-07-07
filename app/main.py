"""FastAPI entrypoint for the IDP platform."""
from fastapi import FastAPI

from app.api.routes import upload

app = FastAPI(title="Enterprise IDP Platform")

app.include_router(upload.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}

""" To start the server run the following command in the terminal: uvicorn app.main:app --reload """
