"""``python -m seams_runtime`` serves a generated route module (same as ``python -m seams_runtime.host``)."""

from .host import main

if __name__ == "__main__":
    raise SystemExit(main())
