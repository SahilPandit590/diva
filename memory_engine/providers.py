"""
Diva Memory Engine v3.0 — Provider interfaces (Section 6.2).
Abstract Protocol contracts for optional external capability providers:
  - EmbeddingProvider: vector embeddings for semantic retrieval (Layer 4)
  - ReasoningProvider: LLM-backed reasoning for development operations

These are intentionally optional. Memory Engine operates fully without them.
When an EmbeddingProvider is supplied to RetrievalEngine, Layer 4 vector search
activates automatically in the retrieval cascade.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Section 6.2 — Provider interface for generating dense vector embeddings.
    Implementations may delegate to any embedding backend (Gemini, OpenAI, local, etc.)
    Memory Engine makes NO assumptions about dimensionality or provider.
    """

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of text strings.

        Args:
            texts: List of raw text strings to embed.

        Returns:
            List of float vectors, one per input text.
            All vectors MUST have the same dimensionality.
        """
        ...

    def embedding_dim(self) -> int:
        """Return the dimensionality of embeddings produced by this provider."""
        ...


@runtime_checkable
class ReasoningProvider(Protocol):
    """
    Section 6.2 — Provider interface for LLM-backed reasoning operations.
    Used by development subsystem for causal investigation, generalization, etc.
    Memory Engine owns the decision to use or discard reasoning outputs;
    reasoning providers do NOT write to Memory Engine directly.
    """

    def reason(self, prompt: str, context: str) -> str:
        """
        Generate a structured reasoning response.

        Args:
            prompt: The specific reasoning instruction or question.
            context: Supporting context from the Memory Engine (retrieved memories,
                     claims, relationships). This is read-only context; the provider
                     must NOT be given write access to Memory Engine state.

        Returns:
            A structured text response. Memory Engine validates and may reject the
            output before integrating it into any knowledge structure.
        """
        ...


class MockEmbeddingProvider:
    """
    In-process mock EmbeddingProvider for testing.
    Returns deterministic pseudo-embeddings based on text hashing.
    NOT for production use.
    """

    _DIM = 128

    def embed(self, texts: List[str]) -> List[List[float]]:
        import hashlib
        results = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            # Map bytes to floats in [-1, 1]
            vec = [(b / 127.5 - 1.0) for b in digest[:self._DIM]]
            # Pad or truncate to exactly _DIM dimensions
            vec = (vec * ((self._DIM // len(vec)) + 1))[: self._DIM]
            results.append(vec)
        return results

    def embedding_dim(self) -> int:
        return self._DIM


class MockReasoningProvider:
    """
    In-process mock ReasoningProvider for testing.
    Returns a deterministic placeholder response.
    NOT for production use.
    """

    def reason(self, prompt: str, context: str) -> str:
        return f"[MockReasoning] prompt={prompt[:50]!r} context_len={len(context)}"
