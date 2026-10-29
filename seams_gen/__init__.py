"""seams_gen: generators that turn the seams model into code (M004/S04+).

Generators read only graph facts and must reproduce the marker-stripped
goldens in docs/generation/golden/ byte for byte (D016).
"""

from .golden import golden_target, strip_markers


class GeneratorError(Exception):
    """A required graph fact is missing or ambiguous.

    The message names the subject IRI and the predicate so the model author
    can find and fix the fact.
    """

    def __init__(self, subject, predicate, detail: str = ""):
        self.subject = str(subject)
        self.predicate = str(predicate)
        self.detail = detail
        message = f"{self.subject}: {self.predicate}"
        super().__init__(f"{message}: {detail}" if detail else message)


from .fragments import fragment_for  # noqa: E402  (needs GeneratorError)
from .htmx import extract_page, generate_fragments, generate_page, render_fragments  # noqa: E402

__all__ = ["GeneratorError", "extract_page", "fragment_for", "generate_fragments", "generate_page",
           "golden_target", "render_fragments", "strip_markers"]
