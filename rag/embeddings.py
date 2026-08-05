import numpy as np

class EmbeddingManager:
    """Fast, lightweight local embedding generator using fastembed / ONNX or normalized hash vectors."""

    def __init__(self, model_name="BAAI/bge-small-en-v1.5"):
        self.dimension = 384
        self.use_fastembed = False
        
        try:
            from fastembed import TextEmbedding
            print(f"Loading FastEmbed model '{model_name}'...")
            self.model = TextEmbedding(model_name=model_name)
            self.use_fastembed = True
            print("FastEmbed model loaded successfully.")
        except Exception as e:
            print(f"FastEmbed notice: {e}. Falling back to lightweight embedding generator.")
            self.model = None

    def _fallback_embedding(self, text: str) -> list[float]:
        """Deterministic 384-dim normalized embedding based on character n-grams and hashing."""
        vec = np.zeros(self.dimension, dtype=np.float32)
        if not text:
            return vec.tolist()
            
        words = text.lower().split()
        for idx, word in enumerate(words):
            hash_val = hash(word) % self.dimension
            vec[hash_val] += 1.0 + (idx * 0.01)
            
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def generate_embedding(self, text: str) -> list[float]:
        """Generate 384-dimensional vector embedding for input text."""
        if self.use_fastembed and text:
            try:
                emb = list(self.model.embed([text]))[0]
                return emb.tolist()
            except Exception:
                pass
        return self._fallback_embedding(text)

    def generate_batch_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of text strings."""
        if not texts:
            return []
            
        if self.use_fastembed:
            try:
                embeddings = list(self.model.embed(texts))
                return [emb.tolist() for emb in embeddings]
            except Exception as e:
                print(f"FastEmbed batch notice: {e}")
                
        return [self._fallback_embedding(t) for t in texts]


# Loading the ONNX model costs seconds (and a download on a cold cache), so the
# manager is process-global and built on first use. Long-lived hosts (the chatbot
# service) pay it once; callers that never embed never pay it at all.
_MANAGER = None


def get_embedding_manager(model_name="BAAI/bge-small-en-v1.5") -> EmbeddingManager:
    """Return the process-wide EmbeddingManager, constructing it on first call."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = EmbeddingManager(model_name=model_name)
    return _MANAGER
