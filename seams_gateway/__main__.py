"""``python -m seams_gateway`` serves the gateway with uvicorn."""

from __future__ import annotations

import argparse
import logging


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m seams_gateway",
        description="OpenAI-compatible /v1/chat/completions gateway (upstream proxy, or stub without a key). "
                    "Configured by env: LLM_API_KEY / LLM_API_KEY_FILE, UPSTREAM_BASE_URL, LLM_MODEL, "
                    "LLM_MODEL_OVERRIDE, LLM_MODEL_ALIASES, LLM_GATEWAY_STUB.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn

    from .app import build_app

    uvicorn.run(build_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
