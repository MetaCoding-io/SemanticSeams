# Generated once by the seams handler stub generator from the expenses model.
# Owned code from now on: edit it freely. The generator never overwrites this file (ADR-0012).
# model-hash: sha256:91cc5d544e080514650657969e9c446a1a70dfe7295afe0f39ab666588d84763

# Who the notification is for: the approval process only runs this handler on
# the path the routing table sends to the manager.
RECIPIENT = "manager"


def notify_manager(entity: dict) -> dict:
    """comm:handler "notify.notify_manager" of :notify_manager_impl (comm:PythonHandler).

    Implements :notify_manager_op (seam:implementedBy :notify_manager_impl).
    entity: the current :ExpenseShape entity (seam:acceptsShape).
    Returns: a :NotificationShape entity (seam:returnsShape).

    Pure computation: the runtime validates the returned dict against
    :NotificationShape and the notify task stores it (seam:writes).
    """
    message = f"{entity['description']} ({entity['amount']}, {entity['date']}) is waiting for your approval."
    return {"recipient": RECIPIENT, "message": message}
