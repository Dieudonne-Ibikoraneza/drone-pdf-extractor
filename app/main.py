"""
FastAPI application for drone PDF extraction service.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.models import ExtractRequest, ExtractResponse
from app.extractor import AgremoReportExtractor

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Drone PDF Extraction Service",
    description="Microservice for extracting structured data from Agremo drone PDF reports",
    version="1.0.0"
)

# Configure CORS
cors_origins = settings.get_cors_origins_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if "*" not in cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "drone-pdf-extractor",
        "version": "1.0.0"
    }


@app.post("/extract-drone-data", response_model=ExtractResponse)
async def extract_drone_data(request: ExtractRequest) -> ExtractResponse:
    """
    Extract structured data from a drone PDF report.
    
    Args:
        request: ExtractRequest containing the PDF file path
        
    Returns:
        ExtractResponse with extracted data or error message
    """
    pdf_path = request.pdfPath
    
    logger.info(f"Received extraction request for PDF: {pdf_path}")
    
    # Validate file exists
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return ExtractResponse(
            success=False,
            error=f"PDF file not found: {pdf_path}"
        )
    
    # Validate file is readable
    if not os.access(pdf_path, os.R_OK):
        logger.error(f"PDF file is not readable: {pdf_path}")
        return ExtractResponse(
            success=False,
            error=f"PDF file is not readable: {pdf_path}"
        )
    
    # Validate file size
    file_size = os.path.getsize(pdf_path)
    if file_size > settings.max_file_size:
        logger.error(f"PDF file exceeds maximum size: {file_size} bytes")
        return ExtractResponse(
            success=False,
            error=f"PDF file exceeds maximum size of {settings.max_file_size} bytes"
        )
    
    # Validate file extension
    if not pdf_path.lower().endswith('.pdf'):
        logger.error(f"File is not a PDF: {pdf_path}")
        return ExtractResponse(
            success=False,
            error="File is not a PDF"
        )
    
    # Extract data from PDF
    extractor = None
    try:
        logger.info(f"Starting PDF extraction for: {pdf_path}")
        extractor = AgremoReportExtractor(pdf_path)
        
        # Extract data (without base64 image data for API response)
        extracted_data = extractor.extract(include_base64=False)
        
        logger.info(f"Successfully extracted data from PDF: {pdf_path}")
        
        return ExtractResponse(
            success=True,
            extractedData=extracted_data
        )
        
    except Exception as e:
        logger.error(f"Error extracting PDF data: {str(e)}", exc_info=True)
        return ExtractResponse(
            success=False,
            error=f"Failed to extract PDF data: {str(e)}"
        )
    finally:
        if extractor:
            extractor.close()


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if settings.log_level == "DEBUG" else "An unexpected error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower()
    )

