import os
import re
from pypdf import PdfReader

class PDFExtractor:
    """Extracts text and structured metadata from PDF search report files."""
    
    def __init__(self, base_dir=None):
        self.base_dir = base_dir

    def extract_metadata_from_path(self, file_path):
        """Extract category, entity name, document name from path relative to base_dir."""
        norm_path = os.path.normpath(file_path)
        parts = norm_path.split(os.sep)
        
        file_name = parts[-1]
        category = "General"
        entity_name = "Unknown"

        # Search for known top categories in path
        for i, part in enumerate(parts):
            if part.lower() in ["roc search", "debtor based search - entities", "asset based search", "litigation search"]:
                category = part
                if i + 1 < len(parts) - 1:
                    entity_name = parts[i + 1]
                elif i + 1 == len(parts) - 1 and not parts[i + 1].endswith('.pdf'):
                    entity_name = parts[i + 1]
                break

        if entity_name == "Unknown" and len(parts) >= 2:
            entity_name = parts[-2]

        return {
            "category": category,
            "entity_name": entity_name,
            "file_name": file_name,
            "file_path": norm_path
        }

    def extract_key_fields_from_text(self, text):
        """Extract father name, state/location, person names, CIN/DIN from document page text."""
        fields = {}

        # Father's name heuristics: s/o, son of, father's name, etc.
        father_match = re.search(r'(?:s/o|son of|father[\'s\s:]+)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})', text, re.IGNORECASE)
        if father_match:
            fields['father_name'] = father_match.group(1).strip()

        # State heuristics: Karnataka, Telangana, Andhra Pradesh, Maharashtra, etc.
        states = ['Karnataka', 'Telangana', 'Andhra Pradesh', 'Maharashtra', 'Delhi', 'Tamil Nadu', 'Kerala', 'Gujarat']
        found_states = [st for st in states if re.search(r'\b' + re.escape(st) + r'\b', text, re.IGNORECASE)]
        if found_states:
            fields['state'] = found_states[0]

        # DIN / CIN regex
        din_match = re.search(r'\bDIN[:\s]*(\d{8})\b', text, re.IGNORECASE)
        if din_match:
            fields['din'] = din_match.group(1)

        cin_match = re.search(r'\b[UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b', text)
        if cin_match:
            fields['cin'] = cin_match.group(0)

        # Person name mentions (e.g., G Janardhan Reddy, Janardhana Reddy, etc.)
        person_match = re.search(r'\b([A-Z]\.?\s*[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+Reddy|\s+Rao|\s+Kumar)?)\b', text)
        if person_match:
            fields['mentioned_person'] = person_match.group(1).strip()

        return fields

    def parse_pdf(self, file_path):
        """Extract page-by-page text and metadata from a PDF file."""
        meta = self.extract_metadata_from_path(file_path)
        pages_content = []

        try:
            reader = PdfReader(file_path)
            total_pages = len(reader.pages)
            meta['total_pages'] = total_pages

            for page_num, page in enumerate(reader.pages, start=1):
                raw_text = page.extract_text() or ""
                clean_text = raw_text.strip()
                if not clean_text:
                    continue

                page_fields = self.extract_key_fields_from_text(clean_text)
                
                pages_content.append({
                    "page_number": page_num,
                    "text": clean_text,
                    "fields": page_fields
                })

        except Exception as e:
            print(f"Error reading PDF '{file_path}': {e}")
            meta['total_pages'] = 0

        return {
            "document_metadata": meta,
            "pages": pages_content
        }
