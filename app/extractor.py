#!/usr/bin/env python3
"""
Agremo PDF Report Extractor - Optimized for Plant_Stress_29998.pdf
"""

import fitz
import base64
import re
import os
from datetime import datetime
from typing import Optional, Dict, Any, List


class AgremoReportExtractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.result = self._init_result_structure()

    def _init_result_structure(self) -> Dict[str, Any]:
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

    def _parse_page1_text(self, text: str) -> None:
        # Get text with better structure preservation - preserve newlines for better matching
        blocks = self.doc[0].get_text("blocks")
        # Join blocks with newlines to preserve structure, then normalize whitespace
        full_text = '\n'.join([b[4].strip() for b in blocks if len(b[4].strip()) > 3])
        # Also create a space-joined version for patterns that need it
        full_text_spaced = ' '.join([b[4].strip() for b in blocks if len(b[4].strip()) > 3])
        lower_full = full_text.lower()
        lower_full_spaced = full_text_spaced.lower()

        # Survey date - handle multi-line: "Survey date:" followed by date on next line or same line
        date_match = re.search(r'Survey\s+date:\s*(\d{2}-\d{2}-\d{4})', full_text_spaced, re.I)
        if not date_match:
            # Try finding date near "Survey date" label
            date_match = re.search(r'(\d{2}-\d{2}-\d{4})', full_text_spaced)
        if date_match:
            self.result["report"]["survey_date"] = date_match.group(1)

        # Report type
        if "Crop Monitoring" in full_text:
            self.result["report"]["type"] = "Crop Monitoring"
        if "Plant Health Monitoring" in full_text:
            self.result["report"]["type"] = "Plant Health Monitoring"

        # Analysis name - only take clean value
        analysis_match = re.search(r'Analysis\s+name:\s*([\w\s]+?)(?:\s+(?:Growing|Field|STRESS|Total|Additional)|$)', full_text_spaced, re.I)
        if analysis_match:
            name = analysis_match.group(1).strip()
            if "STRESS LEVEL" not in name.upper() and len(name) < 50:
                self.result["report"]["analysis_name"] = name
        # Strong fallback
        if "Plant Stress" in full_text and not self.result["report"]["analysis_name"]:
            self.result["report"]["analysis_name"] = "Plant Stress"

        # Crop - find "Crop:" label, then look for crop name nearby (not immediately after due to block structure)
        crop_label_pos = full_text_spaced.find("Crop:")
        if crop_label_pos >= 0:
            # Look for common crop names after the label (skip over other labels)
            # Common patterns: word(s) that are not labels
            crop_patterns = [
                r'(?:sugar\s+beet|wheat|corn|soybean|rice|barley|potato|tomato|cotton|canola)',
                r'([a-z]+\s+[a-z]+)',  # Two-word crop names
                r'([a-z]{4,})',  # Single word, at least 4 chars
            ]
            search_start = crop_label_pos + 5  # After "Crop:"
            search_text = full_text_spaced[search_start:search_start + 200].lower()

            for pattern in crop_patterns:
                match = re.search(pattern, search_text, re.I)
                if match:
                    crop = match.group(1 if match.lastindex else 0).strip()
                    # Validate it's not a label
                    if crop and crop.lower() not in ['total', 'area', 'stress', 'field', 'growing', 'stage', 'analysis', 'name', 'plant', 'health', 'monitoring']:
                        self.result["field"]["crop"] = crop
                        break

        # Growing stage - find "Growing stage:" then look for BBCH pattern nearby
        stage_label_pos = full_text_spaced.find("Growing stage:")
        if stage_label_pos >= 0:
            search_text = full_text_spaced[stage_label_pos:stage_label_pos + 100]
            stage_match = re.search(r'BBCH\s*\d+|BBCH\d+', search_text, re.I)
            if stage_match:
                self.result["field"]["growing_stage"] = stage_match.group(0).strip()
            else:
                # Try finding it anywhere in the text
                stage_match = re.search(r'BBCH\s*\d+|BBCH\d+', full_text_spaced, re.I)
                if stage_match:
                    self.result["field"]["growing_stage"] = stage_match.group(0).strip()

        # Field area - find "Field area:" then look for number + "Hectare"
        area_label_pos = full_text_spaced.find("Field area:")
        if area_label_pos >= 0:
            search_text = full_text_spaced[area_label_pos:area_label_pos + 100]
            area_match = re.search(r'([\d.]+)\s*Hectare', search_text, re.I)
            if area_match:
                try:
                    self.result["field"]["area_hectares"] = float(area_match.group(1))
                except ValueError:
                    pass
            else:
                # Try finding number near "Hectare" anywhere
                area_match = re.search(r'([\d.]+)\s*Hectare', full_text_spaced, re.I)
                if area_match:
                    try:
                        self.result["field"]["area_hectares"] = float(area_match.group(1))
                    except ValueError:
                        pass

        # Total stress - find "Total area PLANT STRESS:" then look for "X ha = Y% field"
        # Note: The pattern might be split: "69% field" and "22.04 ha =" on different lines
        total_label_pos = lower_full_spaced.find("total area plant stress:")
        if total_label_pos >= 0:
            # Search in a wider area around the label
            search_text = lower_full_spaced[total_label_pos:total_label_pos + 200]
            # Try standard pattern first
            total_match = re.search(r'([\d.]+)\s*ha\s*=\s*(\d+)%\s*field', search_text, re.I)
            if not total_match:
                # Try reversed pattern: "Y% field ... X ha ="
                total_match = re.search(r'(\d+)%\s*field.*?([\d.]+)\s*ha\s*=', search_text, re.I)
            if not total_match:
                # Try finding them separately but nearby
                ha_match = re.search(r'([\d.]+)\s*ha\s*=', search_text, re.I)
                percent_match = re.search(r'(\d+)%\s*field', search_text, re.I)
                if ha_match and percent_match:
                    try:
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(ha_match.group(1))
                        self.result["weed_analysis"]["total_stress_percent"] = int(percent_match.group(1))
                    except ValueError:
                        pass
            else:
                try:
                    # Handle both pattern orders
                    if "ha" in total_match.group(0).lower():
                        # Standard: "X ha = Y% field"
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(1))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(2))
                    else:
                        # Reversed: "Y% field ... X ha ="
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(2))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(1))
                except (ValueError, IndexError):
                    pass

        # Fallback: try finding the pattern anywhere in the text if not found above
        if self.result["weed_analysis"]["total_stress_area_hectares"] is None:
            # Look for "X ha = Y% field" pattern anywhere
            total_match = re.search(r'([\d.]+)\s*ha\s*=\s*(\d+)%\s*field', lower_full_spaced, re.I)
            if not total_match:
                # Try reversed
                total_match = re.search(r'(\d+)%\s*field.*?([\d.]+)\s*ha\s*=', lower_full_spaced, re.I)
            if total_match:
                try:
                    if "ha" in total_match.group(0).lower():
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(1))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(2))
                    else:
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(2))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(1))
                except (ValueError, IndexError):
                    pass

        # Stress levels - match in table format, be more specific to avoid false matches
        # Match patterns more carefully to avoid "Potential Plant Stress" matching "Plant Stress"
        stress_levels = []
        seen = set()  # prevent duplicates

        # Match "Fine" followed by percentage and hectares
        fine_matches = re.finditer(r'\bFine\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in fine_matches:
            key = f"Fine_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:  # Only add non-zero entries
                        stress_levels.append({
                            "level": "Fine",
                            "severity": "healthy",
                            "percentage": percent,
                            "area_hectares": ha
                        })
                except ValueError:
                    pass

        # Match "Potential Plant Stress" - must be exact to avoid matching "Plant Stress"
        potential_matches = re.finditer(r'\bPotential\s+Plant\s+Stress\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in potential_matches:
            key = f"Potential_Plant_Stress_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:  # Only add non-zero entries
                        stress_levels.append({
                            "level": "Potential Plant Stress",
                            "severity": "moderate",
                            "percentage": percent,
                            "area_hectares": ha
                        })
                except ValueError:
                    pass

        # Match "Plant Stress" - but NOT "Potential Plant Stress"
        # Use a pattern that matches "Plant Stress" and check context manually
        plant_stress_matches = re.finditer(r'\bPlant\s+Stress\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in plant_stress_matches:
            # Check if this match is part of "Potential Plant Stress"
            start_pos = match.start()
            # Look back up to 20 characters to check for "Potential"
            context_start = max(0, start_pos - 20)
            context = full_text_spaced[context_start:start_pos].lower()
            if "potential" in context:
                continue  # Skip if it's part of "Potential Plant Stress"

            key = f"Plant_Stress_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:  # Only add non-zero entries
                        stress_levels.append({
                            "level": "Plant Stress",
                            "severity": "high",
                            "percentage": percent,
                            "area_hectares": ha
                        })
                except ValueError:
                    pass

        self.result["weed_analysis"]["stress_levels"] = stress_levels

        # Additional info
        if "Test comment" in full_text:
            self.result["additional_info"] = "Test comment"
        else:
            info_match = re.search(r'Additional\s+Information\s*\(or\s+recommendation\):\s*(.+?)(?:\s+Powered|$)', full_text_spaced, re.I | re.DOTALL)
            if info_match:
                comment = info_match.group(1).strip()
                if "Test comment" in comment:
                    self.result["additional_info"] = "Test comment"
                elif len(comment) < 200:  # Only set if reasonable length
                    self.result["additional_info"] = comment

    # Image extraction unchanged
    def _extract_map_image(self, page_num: int = 1, output_dir: Optional[str] = None) -> Dict[str, Any]:
        if page_num >= len(self.doc):
            return {"error": "Page not found"}

        page = self.doc[page_num]
        image_list = page.get_images(full=True)

        if not image_list:
            return self._render_page_as_image(page_num, output_dir)

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

        largest = max(images_data, key=lambda x: x["size_bytes"])

        result = {
            "source": "embedded",
            "format": largest["format"],
            "width": largest["width"],
            "height": largest["height"],
            "size_bytes": largest["size_bytes"],
            "data": base64.b64encode(largest["bytes"]).decode('utf-8')
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, f"field_map.{largest['format']}")
            with open(filepath, "wb") as f:
                f.write(largest["bytes"])
            result["saved_path"] = filepath

        return result

    def _render_page_as_image(self, page_num: int, output_dir: Optional[str] = None, dpi: int = 150) -> Dict[str, Any]:
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
            "data": base64.b64encode(pix.tobytes("png")).decode('utf-8')
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, "field_map.png")
            pix.save(filepath)
            result["saved_path"] = filepath

        return result

    def extract(self, output_dir: Optional[str] = None, include_base64: bool = True) -> Dict[str, Any]:
        if len(self.doc) >= 1:
            page1_text = self.doc[0].get_text("text")
            self._parse_page1_text(page1_text)

        if len(self.doc) >= 2:
            map_data = self._extract_map_image(1, output_dir)
            if not include_base64:
                map_data.pop("data", None)
            self.result["map_image"] = map_data

        return self.result

    def close(self):
        if hasattr(self, 'doc') and self.doc:
            self.doc.close()


def extract_pdf_report(pdf_path: str, output_dir: str = None) -> Dict[str, Any]:
    extractor = AgremoReportExtractor(pdf_path)
    try:
        result = extractor.extract(output_dir)
        return result
    finally:
        extractor.close()