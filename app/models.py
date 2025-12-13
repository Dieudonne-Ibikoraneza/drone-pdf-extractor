"""
Pydantic models for API request and response.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    """Request model for PDF extraction endpoint."""
    
    pdfPath: str = Field(
        ...,
        description="Absolute path to the PDF file to extract data from",
        example="/path/to/uploads/drone-analysis/file.pdf"
    )


class ExtractResponse(BaseModel):
    """Response model for PDF extraction endpoint."""
    
    success: bool = Field(
        ...,
        description="Whether the extraction was successful"
    )
    
    extractedData: Optional[Dict[str, Any]] = Field(
        None,
        description="Extracted data from the PDF if successful"
    )
    
    error: Optional[str] = Field(
        None,
        description="Error message if extraction failed"
    )

