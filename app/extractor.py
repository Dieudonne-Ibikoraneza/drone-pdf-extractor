#!/usr/bin/env python3
"""
Agremo PDF Report Extractor - Optimized for Plant_Stress_*.pdf
With Cloudinary upload for map images (no base64 in response)
"""

import fitz
import re
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from app.config import settings

if settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True
    )
else:
    print("Warning: Cloudinary credentials not configured in settings")

logger = __import__('logging').getLogger(__name__)


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
                "extractor_version": "2.1-cloudinary"
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
                "source": None,
                "url": None,
                "public_id": None,
                "width": None,
                "height": None,
                "format": None,
                "bytes": None,
                "error": None
            }
        }

    def _parse_page1_text(self, text: str) -> None:
        blocks = self.doc[0].get_text("blocks")
        full_text = '\n'.join([b[4].strip() for b in blocks if len(b[4].strip()) > 3])
        full_text_spaced = ' '.join([b[4].strip() for b in blocks if len(b[4].strip()) > 3])
        lower_full = full_text.lower()
        lower_full_spaced = full_text_spaced.lower()

        # Survey date
        date_match = re.search(r'Survey\s+date:\s*(\d{2}-\d{2}-\d{4})', full_text_spaced, re.I)
        if not date_match:
            date_match = re.search(r'(\d{2}-\d{2}-\d{4})', full_text_spaced)
        if date_match:
            self.result["report"]["survey_date"] = date_match.group(1)

        # Report type
        if "Crop Monitoring" in full_text:
            self.result["report"]["type"] = "Crop Monitoring"
        if "Plant Health Monitoring" in full_text:
            self.result["report"]["type"] = "Plant Health Monitoring"

        # Analysis name
        analysis_match = re.search(r'Analysis\s+name:\s*([\w\s]+?)(?:\s+(?:Growing|Field|STRESS|Total|Additional)|$)', full_text_spaced, re.I)
        if analysis_match:
            name = analysis_match.group(1).strip()
            if "STRESS LEVEL" not in name.upper() and len(name) < 50:
                self.result["report"]["analysis_name"] = name
        if "Plant Stress" in full_text and not self.result["report"]["analysis_name"]:
            self.result["report"]["analysis_name"] = "Plant Stress"

        # Crop
        crop_label_pos = full_text_spaced.find("Crop:")
        if crop_label_pos >= 0:
            crop_patterns = [
                r'(?:sugar\s+beet|wheat|corn|soybean|rice|barley|potato|tomato|cotton|canola)',
                r'([a-z]+\s+[a-z]+)',
                r'([a-z]{4,})',
            ]
            search_start = crop_label_pos + 5
            search_text = full_text_spaced[search_start:search_start + 200].lower()
            for pattern in crop_patterns:
                match = re.search(pattern, search_text, re.I)
                if match:
                    crop = match.group(1 if match.lastindex else 0).strip()
                    if crop and crop.lower() not in ['total', 'area', 'stress', 'field', 'growing', 'stage', 'analysis', 'name', 'plant', 'health', 'monitoring']:
                        self.result["field"]["crop"] = crop
                        break

        # Growing stage
        stage_label_pos = full_text_spaced.find("Growing stage:")
        if stage_label_pos >= 0:
            search_text = full_text_spaced[stage_label_pos:stage_label_pos + 100]
            stage_match = re.search(r'BBCH\s*\d+|BBCH\d+', search_text, re.I)
            if stage_match:
                self.result["field"]["growing_stage"] = stage_match.group(0).strip()
            else:
                stage_match = re.search(r'BBCH\s*\d+|BBCH\d+', full_text_spaced, re.I)
                if stage_match:
                    self.result["field"]["growing_stage"] = stage_match.group(0).strip()

        # Field area
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
            area_match = re.search(r'([\d.]+)\s*Hectare', full_text_spaced, re.I)
            if area_match:
                try:
                    self.result["field"]["area_hectares"] = float(area_match.group(1))
                except ValueError:
                    pass

        # Total stress area & percentage
        total_label_pos = lower_full_spaced.find("total area plant stress:")
        if total_label_pos >= 0:
            search_text = lower_full_spaced[total_label_pos:total_label_pos + 200]
            total_match = re.search(r'([\d.]+)\s*ha\s*=\s*(\d+)%\s*field', search_text, re.I)
            if not total_match:
                total_match = re.search(r'(\d+)%\s*field.*?([\d.]+)\s*ha\s*=', search_text, re.I)
            if not total_match:
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
                    if "ha" in total_match.group(0).lower():
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(1))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(2))
                    else:
                        self.result["weed_analysis"]["total_stress_area_hectares"] = float(total_match.group(2))
                        self.result["weed_analysis"]["total_stress_percent"] = int(total_match.group(1))
                except (ValueError, IndexError):
                    pass

        if self.result["weed_analysis"]["total_stress_area_hectares"] is None:
            total_match = re.search(r'([\d.]+)\s*ha\s*=\s*(\d+)%\s*field', lower_full_spaced, re.I)
            if not total_match:
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

        # Stress levels table parsing (unchanged)
        stress_levels = []
        seen = set()

        fine_matches = re.finditer(r'\bFine\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in fine_matches:
            key = f"Fine_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:
                        stress_levels.append({
                            "level": "Fine",
                            "severity": "healthy",
                            "percentage": percent,
                            "area_hectares": ha
                        })
                except ValueError:
                    pass

        potential_matches = re.finditer(r'\bPotential\s+Plant\s+Stress\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in potential_matches:
            key = f"Potential_Plant_Stress_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:
                        stress_levels.append({
                            "level": "Potential Plant Stress",
                            "severity": "moderate",
                            "percentage": percent,
                            "area_hectares": ha
                        })
                except ValueError:
                    pass

        plant_stress_matches = re.finditer(r'\bPlant\s+Stress\s+([\d.]+)%\s+([\d.]+)\b', full_text_spaced, re.I)
        for match in plant_stress_matches:
            start_pos = match.start()
            context_start = max(0, start_pos - 20)
            context = full_text_spaced[context_start:start_pos].lower()
            if "potential" in context:
                continue
            key = f"Plant_Stress_{match.group(1)}_{match.group(2)}"
            if key not in seen:
                seen.add(key)
                try:
                    percent = float(match.group(1))
                    ha = float(match.group(2))
                    if percent > 0 or ha > 0:
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
                elif len(comment) < 200:
                    self.result["additional_info"] = comment

    def _upload_to_cloudinary(self, image_bytes: bytes, img_format: str) -> Dict[str, Any]:
        """Upload image bytes to Cloudinary and return relevant info"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            public_id = f"agremo_map_{timestamp}"

            upload_result = cloudinary.uploader.upload(
                image_bytes,
                resource_type="image",
                public_id=public_id,
                folder=settings.cloudinary_folder or "drone-reports",
                format=img_format.lower(),
                overwrite=False,
            )

            return {
                "url": upload_result["secure_url"],
                "public_id": upload_result["public_id"],
                "width": upload_result.get("width"),
                "height": upload_result.get("height"),
                "format": upload_result.get("format"),
                "bytes": upload_result.get("bytes"),
            }

        except CloudinaryError as e:
            logger.error(f"Cloudinary upload error: {str(e)}")
            return {"error": f"Cloudinary upload failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error during Cloudinary upload: {str(e)}")
            return {"error": str(e)}

    def _extract_map_image(self, page_num: int = 1, output_dir: Optional[str] = None) -> Dict[str, Any]:
        if page_num >= len(self.doc):
            return {"error": "Page not found"}

        page = self.doc[page_num]
        image_list = page.get_images(full=True)

        image_bytes = None
        img_format = "png"
        width = None
        height = None

        source = "unknown"

        if image_list:
            images_data = []
            for img in image_list:
                xref = img[0]
                base_image = self.doc.extract_image(xref)
                bytes_data = base_image["image"]
                images_data.append({
                    "bytes": bytes_data,
                    "format": base_image["ext"],
                    "size": len(bytes_data),
                    "width": base_image.get("width", 0),
                    "height": base_image.get("height", 0),
                })

            largest = max(images_data, key=lambda x: x["size"])
            image_bytes = largest["bytes"]
            img_format = largest["format"]
            width = largest["width"]
            height = largest["height"]
            source = "embedded"

        else:
            # Fallback: render the whole page
            zoom = 150 / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            image_bytes = pix.tobytes("png")
            width = pix.width
            height = pix.height
            source = "page_render"

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, "field_map.png")
                pix.save(filepath)

        if not image_bytes:
            return {"error": "Could not extract or render map image"}

        # Upload to Cloudinary
        upload_result = self._upload_to_cloudinary(image_bytes, img_format)

        if "error" in upload_result:
            return {
                "source": source,
                "error": upload_result["error"],
                "width": width,
                "height": height,
                "format": img_format
            }

        # Success
        return {
            "source": "cloudinary",
            "url": upload_result["url"],
            "public_id": upload_result["public_id"],
            "width": upload_result.get("width", width),
            "height": upload_result.get("height", height),
            "format": upload_result.get("format", img_format),
            "bytes": upload_result.get("bytes")
        }

    def extract(self, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Main extraction method - no more include_base64 flag"""
        if len(self.doc) >= 1:
            page1_text = self.doc[0].get_text("text")
            self._parse_page1_text(page1_text)

        if len(self.doc) >= 2:
            map_data = self._extract_map_image(1, output_dir)
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