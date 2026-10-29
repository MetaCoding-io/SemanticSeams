"""An OpenAI-compatible chat-completions gateway: a streaming proxy to an
upstream provider, or a deterministic stub when no key is configured.

    python -m seams_gateway --port 8000
"""

from .app import GatewayConfig, build_app

__all__ = ["GatewayConfig", "build_app"]
