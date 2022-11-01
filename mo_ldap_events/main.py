# SPDX-FileCopyrightText: 2019-2020 Magenta ApS
#
# SPDX-License-Identifier: MPL-2.0
"""Event handling."""
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi import FastAPI
from fastramqpi.main import FastRAMQPI
from ldap3 import ASYNC_STREAM
from ldap3 import Connection
from ldap3 import RESTARTABLE

from .config import Settings
from .ldap import configure_ad_connection
from .ldap import setup_listener

logger = structlog.get_logger()
fastapi_router = APIRouter()


@asynccontextmanager
async def open_ad_connection(ad_connection: Connection) -> AsyncIterator[None]:
    """Open the AD connection during FastRAMQPI lifespan.

    Yields:
        None
    """
    with ad_connection:
        yield


def listener(event):
    objectGUID = event.get("attributes", {}).get("objectGUID", None)
    if objectGUID:
        print(f"listener({objectGUID})")
    else:
        print(f"Got event without objectGUID: {event}")


def create_fastramqpi(**kwargs: Any) -> FastRAMQPI:
    """FastRAMQPI factory.

    Returns:
        FastRAMQPI system.
    """
    settings = Settings(**kwargs)
    fastramqpi = FastRAMQPI(application_name="adevent", settings=settings.fastramqpi)
    fastramqpi.add_context(settings=settings)

    ad_async_connection = configure_ad_connection(
        settings, client_strategy=ASYNC_STREAM
    )
    fastramqpi.add_context(ad_async_connection=ad_async_connection)
    ad_sync_connection = configure_ad_connection(settings, client_strategy=RESTARTABLE)
    fastramqpi.add_context(ad_sync_connection=ad_sync_connection)
    # fastramqpi.add_healthcheck(name="ADConnection", healthcheck=ad_healthcheck)
    # fastramqpi.add_lifespan_manager(open_ad_connection(ad_async_connection), 1500)

    context = fastramqpi.get_context()
    setup_listener(context, listener)

    return fastramqpi


def create_app(**kwargs: Any) -> FastAPI:
    """FastAPI application factory.

    Returns:
        FastAPI application.
    """

    handler = logging.StreamHandler(stream=sys.stdout)
    root_logger = logging.getLogger("ldap3")
    root_logger.addHandler(handler)
    root_logger.setLevel(20)

    root_logger.log(level=20, msg="Logger works")

    fastramqpi = create_fastramqpi(**kwargs)

    app = fastramqpi.get_app()
    app.include_router(fastapi_router)

    return app
