"""Local Gemma (Ollama) client shared by the perception sidecars."""

from vision_mcp.gemma.client import GemmaClient, GemmaError, encode_image

__all__ = ["GemmaClient", "GemmaError", "encode_image"]
