"""
Wrapper around Azure Document Intelligence (prebuilt-invoice model).
Handles submitting a document and returning the raw analyzeResult JSON.

Requires: pip install azure-ai-documentintelligence --break-system-packages
"""

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

from app.core.config import settings


def analyze_invoice(file_path: str) -> dict:
    """
    Sends a document to Azure's prebuilt-invoice model and returns the
    raw analyzeResult as a dict (matching Document Intelligence Studio output).
    """
    client = DocumentIntelligenceClient(
        endpoint=settings.AZURE_DOCINTEL_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_DOCINTEL_KEY),
    )

    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            model_id="prebuilt-invoice",
            body=f,
            content_type="application/octet-stream",
        )

    result = poller.result()

    # The SDK returns fields flat (documents, content, pages, etc. at the
    # top level). Document Intelligence Studio's exported JSON nests all
    # of this under an "analyzeResult" key instead. We wrap it here so
    # invoice_extractor.py and everything downstream can treat both
    # sources identically.
    return {"analyzeResult": result.as_dict()}