class DocumentChunker:
    """Chunks parsed document pages into optimal sizes for vector embedding generation."""

    def __init__(self, chunk_size=800, overlap=150):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, parsed_doc):
        doc_meta = parsed_doc["document_metadata"]
        pages = parsed_doc["pages"]
        chunks = []
        chunk_counter = 0

        for page in pages:
            page_num = page["page_number"]
            text = page["text"]
            fields = page["fields"]

            if not text:
                continue

            # Split text by paragraphs / lines or fixed window with overlap
            words = text.split()
            current_chunk_words = []
            current_length = 0

            i = 0
            while i < len(words):
                word = words[i]
                current_chunk_words.append(word)
                current_length += len(word) + 1

                if current_length >= self.chunk_size or i == len(words) - 1:
                    chunk_body = " ".join(current_chunk_words)
                    
                    # Contextual header for enhanced embedding retrieval
                    header = (
                        f"[Category: {doc_meta.get('category')} | "
                        f"Entity: {doc_meta.get('entity_name')} | "
                        f"File: {doc_meta.get('file_name')} | "
                        f"Page: {page_num}]\n"
                    )
                    
                    full_chunk_text = header + chunk_body

                    # Combine metadata
                    chunk_meta = {
                        "category": doc_meta.get("category"),
                        "entity_name": doc_meta.get("entity_name"),
                        "file_name": doc_meta.get("file_name"),
                        "page_number": page_num,
                        "chunk_index": chunk_counter
                    }
                    chunk_meta.update(fields)

                    chunks.append({
                        "chunk_index": chunk_counter,
                        "page_number": page_num,
                        "chunk_text": full_chunk_text,
                        "raw_text": chunk_body,
                        "metadata": chunk_meta
                    })

                    chunk_counter += 1

                    # Overlap handling
                    overlap_words = []
                    overlap_len = 0
                    j = len(current_chunk_words) - 1
                    while j >= 0 and overlap_len < self.overlap:
                        overlap_words.insert(0, current_chunk_words[j])
                        overlap_len += len(current_chunk_words[j]) + 1
                        j -= 1

                    current_chunk_words = overlap_words
                    current_length = overlap_len

                i += 1

        return chunks
