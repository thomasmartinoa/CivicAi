"""Citizen notification.

Thin stub for Phase 1b: logs instead of sending. Only reached when the graph
runner is not given an injected `deps.notify`, which no test does. Phase 1c
wires this to real email/SMS delivery.
"""

import logging

logger = logging.getLogger(__name__)


def notify_citizen(**kwargs) -> None:
    logger.info("notify_citizen (stub): %s", kwargs)
