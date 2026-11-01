"""Local Gemma (Ollama) client shared by the perception sidecars."""

from dobby.gemma.client import GemmaClient, GemmaError, encode_image

__all__ = ["GemmaClient", "GemmaError", "encode_image"]
