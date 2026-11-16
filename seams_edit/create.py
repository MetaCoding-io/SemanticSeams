"""The create path: a new model file, with its payloads, from a patch (ADR-0046 section 5).

``apply`` edits model files that exist. ``create`` writes a model that does not exist
yet: it renders the patch with the TriG text writer over a header of ``@prefix`` lines,
so the new file is laid out as the writer lays out any added text and is checked the
same way (it must re-parse to the patch's quads). Each payload (a BPMN or DMN file the
model's ``seam:renderPayload`` names) must be well-formed XML. The TriG file and the
payloads are written together, or none of them, and a path that exists is refused, so a
create never overwrites a model.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from .files import write_all
from .patch import Patch, PatchError
from .trig import apply_text
from .xml import check_payload


def create(
    path: str | os.PathLike[str],
    patch: Patch,
    *,
    prefixes: Mapping[str, str],
    payloads: Mapping[str | os.PathLike[str], str | bytes] | None = None,
) -> tuple[Path, ...]:
    """Write the new TriG file ``path`` holding the quads ``patch`` adds, and each
    payload's bytes; return the paths written, sorted.

    ``prefixes`` maps each prefix name (``""`` for the default ``:``) to its namespace,
    written in the given order as the file's header; the writer uses them to write the
    terms. Relative IRIs are resolved against ``path``, and an IRI under its folder is
    written relative, so a payload beside the file is named by its file name.

    Raises PatchError, writing nothing, when ``path`` or a payload exists, a payload is
    the TriG path or not well-formed XML, the patch removes quads, or the writer refuses
    the patch.
    """
    target = Path(path).resolve()
    files = {Path(p).resolve(): data for p, data in (payloads or {}).items()}
    if target in files:
        raise PatchError(target, "seam:renderPayload", "a payload cannot be the model file itself")
    for where in sorted([target, *files]):
        if where.exists():
            raise PatchError(where, "file", "already exists; create never overwrites a file")
    if patch.removes:
        s, p, _, _ = patch.removes[0]
        raise PatchError(s, p, "a new model has nothing to remove")
    header = "".join(f"@prefix {name}: <{namespace}> .\n" for name, namespace in prefixes.items())
    text = apply_text(header, patch, base=target.as_uri())
    contents: dict[Path, tuple[bytes, bytes]] = {target: (b"", text.encode("utf-8"))}
    for where, data in sorted(files.items()):
        raw = data.encode("utf-8") if isinstance(data, str) else data
        check_payload(where, raw)
        contents[where] = (b"", raw)
    try:
        write_all(contents)
    except OSError:
        for where in contents:
            where.unlink(missing_ok=True)
        raise
    return tuple(sorted(contents))
