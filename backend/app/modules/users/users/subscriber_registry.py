"""Durable command registration for the users module."""

from jasil.jobs.reconciliation import DurableSubscriberNet
from jasil.jobs.registry import JobHandlerRegistry

import modules.users.users.subscribers as users_subscribers


def register_durable_handlers(registry: JobHandlerRegistry) -> None:
    """Register the users command handlers.

    Args:
        registry: The durable-handler registry to register on.
    """
    users_subscribers.register_durable_handlers(registry)


DURABLE_SUBSCRIBER_NETS: tuple[DurableSubscriberNet, ...] = (
    DurableSubscriberNet(
        users_subscribers.DELETION_REQUESTED_SUBSCRIBER_ID,
        None,
        exempt_reason=(
            "A deletion is a command, not derived state. Its outcome is recorded in the shared deletion state, "
            "which an administrator polls; the account stays deactivated and signed out until a failed deletion "
            "is requested again."
        ),
    ),
)
