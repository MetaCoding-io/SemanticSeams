# Generated once by the seams handler stub generator from the chat-app model.
# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).
# model-hash: sha256:<model-hash>
# context-hash: sha256:<context-hash>

from typing import NotRequired, TypedDict


class MessageShape(TypedDict):
    """:MessageShape (sh:NodeShape): one key per sh:property."""

    content: str
    role: NotRequired[str]
    status: NotRequired[str]
    timestamp: NotRequired[str]


def notify_manager(entity: MessageShape) -> MessageShape:
    """comm:handler "notify.notify_manager" of :py_impl (comm:PythonHandler).

    Implements :send_message_op (seam:implementedBy :py_impl).
    entity: the current :MessageShape entity (seam:acceptsShape).
    Returns: a :MessageShape entity (seam:returnsShape).
    Invoked by :persist_user_msg (seam:invokes), a proc:ServiceTask of :send_message_process.
    Fires :t_send (seam:fires): :s_composing -> :s_sending.
    """
    raise NotImplementedError("notify.notify_manager: write the handler for :send_message_op")
