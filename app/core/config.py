"""
Central configuration for the IDP platform.
Reads Azure Document Intelligence credentials from environment variables.
Never hardcode keys directly in source files.
"""

import os


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
