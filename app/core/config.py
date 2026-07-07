"""
Central configuration for the IDP platform.

Loads Azure Document Intelligence credentials from a .env file so you
never have to manually `export` them in every new terminal session.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present


class Settings:
    # Azure Document Intelligence
    AZURE_DOCINTEL_ENDPOINT: str = os.getenv("AZURE_DOCINTEL_ENDPOINT", "")
    AZURE_DOCINTEL_KEY: str = os.getenv("AZURE_DOCINTEL_KEY", "")

    # Confidence threshold below which we fall back to heuristic extraction
    # instead of trusting the prebuilt model's labeled field.
    LOW_CONFIDENCE_THRESHOLD: float = 0.60

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


settings = Settings()

if not settings.AZURE_DOCINTEL_ENDPOINT or not settings.AZURE_DOCINTEL_KEY:
    print(
        "WARNING: Azure credentials not found. Create a .env file "
        "(see .env.example) with AZURE_DOCINTEL_ENDPOINT and AZURE_DOCINTEL_KEY."
    )