# Generated once by the seams handler stub generator from the chat-app model.
# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).
# model-hash: sha256:<model-hash>


def notify_manager(entity: dict) -> dict:
    """comm:handler "notify.notify_manager" of :py_impl (comm:PythonHandler).

    Implements :send_message_op (seam:implementedBy :py_impl).
    entity: the current :MessageShape entity (seam:acceptsShape).
    Returns: a :MessageShape entity (seam:returnsShape).
    """
    raise NotImplementedError("notify.notify_manager: write the handler for :send_message_op")
