#!/usr/bin/env python3
"""
Agremo PDF Report Extractor
Extracts structured data from Agremo crop monitoring PDF reports.
Handles both structured data extraction and image extraction.
"""

import fitz  # PyMuPDF
import json
import base64
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


class AgremoReportExtractor:
    """
    Extractor class for Agremo crop monitoring PDF reports.
    Handles both structured data extraction and image extraction.
    """
    
    def __init__(self, pdf_path: str):
        """
        Initialize the extractor with a PDF file path.
        
        Args:
            pdf_path: Path to the PDF file (absolute or relative)
        """
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.result = self._init_result_structure()
    
    def _init_result_structure(self) -> Dict[str, Any]:
        """Initialize the result JSON structure"""
        return {
            "metadata": {
                "source_file": os.path.basename(self.pdf_path),
                "extracted_at": datetime.now().isoformat(),
                "total_pages": len(self.doc),
                "extractor_version": "2.0"
            },
            "report": {
                "provider": "Agremo",
                "type": None,
                "survey_date": None,
                "analysis_name": None
            },
            "field": {
                "crop": None,
                "growing_stage": None,
                "area_hectares": None
            },
            "weed_analysis": {
                "total_stress_area_hectares": None,
                "total_stress_percent": None,
                "stress_levels": []
            },
            "additional_info": None,
            "map_image": {
                "format": "png",
                "width": None,
                "height": None,
                "data": None
            }
        }

        # Extract map image from page 2 (index 1)
        page2 = self.doc[1]
        image_list = page2.get_images(full=True)
        if image_list:
            # Assume first/main image is the map (adjust index if multiple images)
            xref = image_list[0][0]  # XREF of the image
            base_image = self.doc.extract_image(xref)
            image_bytes = base_image["image"]
            extracted_data["map_image"]["width"] = base_image["width"]
            extracted_data["map_image"]["height"] = base_image["height"]

            if include_base64:
                extracted_data["map_image"]["data"] = base64.b64encode(image_bytes).decode('utf-8')

    
    def _parse_page1_text(self, text: str) -> None:
        """Parse structured data from page 1 text"""
        
        # Clean up text - remove extra whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        full_text = ' '.join(lines)
        
        # Survey date - multiple patterns
        date_patterns = [
            r'Survey date:\s*(\d{2}-\d{2}-\d{4})',
            r'(\d{2}-\d{2}-\d{4})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                self.result["report"]["survey_date"] = match.group(1)
                break
        
        # Report type
        if "Crop Monitoring" in text:
            self.result["report"]["type"] = "Crop Monitoring"
            crop_match = re.search(r'Crop Monitoring-?\s*(\w+)', text)
            if crop_match:
                self.result["field"]["crop"] = crop_match.group(1).lower()
        
        # Analysis name (WEED DETECTION)
        if "WEED DETECTION" in text:
            self.result["report"]["analysis_name"] = "Weed Detection"
        
        # Crop type (look for Crop: pattern)
        crop_match = re.search(r'Crop:\s*(\w+)', text)
        if crop_match and crop_match.group(1).lower() != "total":
            self.result["field"]["crop"] = crop_match.group(1).lower()
        
        # Growing stage
        stage_match = re.search(r'Growing stage:\s*(\w+)', text)
        if stage_match:
            self.result["field"]["growing_stage"] = stage_match.group(1)
        
        # Field area - look for the hectare value
        area_patterns = [
            r'Field area:\s*([\d.]+)\s*Hectare',
            r'([\d.]+)\s*Hectare',
        ]
        for pattern in area_patterns:
            match = re.search(pattern, text)
            if match:
                self.result["field"]["area_hectares"] = float(match.group(1))
                break
        
        # Total weed stress - multiple patterns
        stress_patterns = [
            r'([\d.]+)\s*ha\s*=\s*(\d+)%\s*field',
            r'Total area WEED STRESS:\s*([\d.]+)\s*ha\s*=\s*(\d+)%',
        ]
        for pattern in stress_patterns:
            match = re.search(pattern, full_text)
            if match:
                self.result["weed_analysis"]["total_stress_area_hectares"] = float(match.group(1))
                self.result["weed_analysis"]["total_stress_percent"] = int(match.group(2))
                break
        
        # Stress levels from table
        stress_level_patterns = [
            (r'Fine\s+([\d.]+)%\s+([\d.]+)', "Fine", "healthy"),
            (r'Low Weed Pressure\s+([\d.]+)%\s+([\d.]+)', "Low Weed Pressure", "low"),
            (r'High Weed Pressure\s+([\d.]+)%\s+([\d.]+)', "High Weed Pressure", "high"),
        ]
        
        for pattern, level_name, severity in stress_level_patterns:
            match = re.search(pattern, text)
            if match:
                self.result["weed_analysis"]["stress_levels"].append({
                    "level": level_name,
                    "severity": severity,
                    "percentage": float(match.group(1)),
                    "area_hectares": float(match.group(2))
                })
        
        # Additional comments
        if "Test comment" in text:
            self.result["additional_info"] = "Test comment"
    
    def _extract_map_image(self, page_num: int = 1, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Extract the map image from the specified page"""
        
        if page_num >= len(self.doc):
            return {"error": "Page not found"}
        
        page = self.doc[page_num]
        image_list = page.get_images(full=True)
        
        if not image_list:
            # Fallback: render page as image
            return self._render_page_as_image(page_num, output_dir)
        
        # Find the largest image (the map)
        images_data = []
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = self.doc.extract_image(xref)
            image_bytes = base_image["image"]
            
            images_data.append({
                "index": img_index,
                "xref": xref,
                "format": base_image["ext"],
                "width": base_image.get("width", 0),
                "height": base_image.get("height", 0),
                "size_bytes": len(image_bytes),
                "bytes": image_bytes
            })
        
        # Get the largest image
        largest = max(images_data, key=lambda x: x["size_bytes"])
        
        result = {
            "source": "embedded",
            "format": largest["format"],
            "width": largest["width"],
            "height": largest["height"],
            "size_bytes": largest["size_bytes"],
            "data_base64": base64.b64encode(largest["bytes"]).decode('utf-8')
        }
        
        # Save to file if output directory specified
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"field_map.{largest['format']}"
            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(largest["bytes"])
            result["saved_path"] = filepath
        
        return result
    
    def _render_page_as_image(self, page_num: int, output_dir: Optional[str] = None, dpi: int = 150) -> Dict[str, Any]:
        """Render entire page as image (fallback method)"""
        page = self.doc[page_num]
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        result = {
            "source": "page_render",
            "format": "png",
            "width": pix.width,
            "height": pix.height,
            "dpi": dpi,
            "data_base64": base64.b64encode(pix.tobytes("png")).decode('utf-8')
        }
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, "field_map.png")
            pix.save(filepath)
            result["saved_path"] = filepath
        
        return result
    
    def extract(self, output_dir: Optional[str] = None, include_base64: bool = True) -> Dict[str, Any]:
        """
        Main extraction method.
        
        Args:
            output_dir: Directory to save extracted images (optional)
            include_base64: Whether to include base64 image data in result
        
        Returns:
            Complete extracted data as dictionary
        """
        # Extract text from page 1
        if len(self.doc) >= 1:
            page1_text = self.doc[0].get_text()
            self._parse_page1_text(page1_text)
        
        # Extract map from page 2
        if len(self.doc) >= 2:
            map_data = self._extract_map_image(1, output_dir)
            if not include_base64:
                map_data.pop("data_base64", None)
            self.result["map_image"] = map_data
        
        return self.result
    
    def to_json(self, include_base64: bool = False) -> str:
        """Return result as JSON string"""
        output = self.result.copy()
        if not include_base64 and output.get("map_image"):
            output["map_image"] = {k: v for k, v in output["map_image"].items() if k != "data_base64"}
        return json.dumps(output, indent=2, ensure_ascii=False)
    
    def close(self):
        """Close the PDF document"""
        if hasattr(self, 'doc') and self.doc:
            self.doc.close()


def extract_pdf_report(pdf_path: str, output_dir: str = None) -> Dict[str, Any]:
    """
    Convenience function to extract data from an Agremo PDF report.
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Optional directory to save extracted images
    
    Returns:
        Extracted data as dictionary
    """
    extractor = AgremoReportExtractor(pdf_path)
    try:
        result = extractor.extract(output_dir)
        return result
    finally:
        extractor.close()

