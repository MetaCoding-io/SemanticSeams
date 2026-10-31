# Generated once by the seams handler stub generator from the expenses model.
# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).
# model-hash: sha256:91cc5d544e080514650657969e9c446a1a70dfe7295afe0f39ab666588d84763

from seams_runtime import OperationError

# Who the notification is for: the approval process only runs this handler on
# the path the routing table sends to the manager.
RECIPIENT = "manager"
# The manager is told by text message, which holds at most this many characters.
MAX_MESSAGE = 160


def notify_manager(entity: dict) -> dict:
    """comm:handler "notify.notify_manager" of :notify_manager_impl (comm:PythonHandler).

    Implements :notify_manager_op (seam:implementedBy :notify_manager_impl).
    entity: the current :ExpenseShape entity (seam:acceptsShape).
    Returns: a :NotificationShape entity (seam:returnsShape).
    Raises: OperationError("notify-failed") when the message cannot be sent
    (:notify_failed, one of the operation's hydra:possibleStatus).

    Pure computation: the runtime validates the returned dict against
    :NotificationShape and the notify task stores it (seam:writes). A raised
    notify-failed takes the process down the task's error boundary instead.
    """
    message = f"{entity['description']} ({entity['amount']}, {entity['date']}) is waiting for your approval."
    if len(message) > MAX_MESSAGE:
        raise OperationError(
            "notify-failed", f"the message is {len(message)} characters; a text message holds {MAX_MESSAGE}"
        )
    return {"recipient": RECIPIENT, "message": message}
