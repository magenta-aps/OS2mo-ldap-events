# Opret en agent der modtager amqp-events og importerer og eksporterer til LDAP
import time
from datetime import datetime
from ssl import CERT_NONE
from ssl import CERT_REQUIRED
from threading import Thread
from typing import Callable
from typing import Dict

import pytz as pytz
from fastramqpi.context import Context
from ldap3 import ASYNC_STREAM
from ldap3 import Connection
from ldap3 import NTLM
from ldap3 import RANDOM
from ldap3 import Server
from ldap3 import ServerPool
from ldap3 import Tls

from .config import ServerConfig
from .config import Settings


def construct_server(server_config: ServerConfig) -> Server:
    """Construct an LDAP3 server from settings.

    Args:
        server_config: The settings to construct the server instance from.

    Returns:
        The constructed server instance used for LDAP connections.
    """
    tls_configuration = Tls(
        validate=CERT_NONE if server_config.insecure else CERT_REQUIRED
    )
    return Server(
        host=server_config.host,
        port=server_config.port,
        use_ssl=server_config.use_ssl,
        tls=tls_configuration,
        connect_timeout=server_config.timeout,
    )


def configure_ad_connection(
    settings: Settings, client_strategy=ASYNC_STREAM
) -> Connection:
    """Configure an AD connection.

    Args:
        settings: The Settings instance to configure our ad connection with.

    Returns:
        ContextManager that can be opened to establish an AD connection.
    """
    servers = list(map(construct_server, settings.ad_controllers))
    # Pick the next server to use at random, discard non-active servers
    server_pool = ServerPool(servers, RANDOM, active=True, exhaust=True)

    connection = Connection(
        server=server_pool,
        # We always authenticate via NTLM
        user=settings.ad_domain + "\\" + settings.ad_user,
        password=settings.ad_password.get_secret_value(),
        authentication=NTLM,
        client_strategy=client_strategy,
        read_only=True,
        pool_keepalive=True,
        auto_bind="DEFAULT",
    )

    return connection


def setup_listener(context: Context, callback: Callable):

    search_parameters = {
        "search_base": "dc=ad",
        "search_filter": "(cn=*)",
        # search_scope=SUBTREE,
        # dereference_aliases=DEREF_NEVER,
        "attributes": ["objectGUID"],
        # controls=None,
    }

    now = datetime.now(tz=pytz.utc)
    # setup_persistent_search(context, callback, search_parameters)

    # Polling search
    setup_poller(context, callback, search_parameters, now)


"""
We currently lack a good way of testing this; ldap3 can't, and OpenLDAP and AD
don't work properly with it either

def setup_persistent_search(
    context: Context, callback: Callable, search_parameters: dict
):
    connection = context["user_context"]["ad_async_connection"]

    def ad_listener(event: dict) -> None:
        #Callback for our persistent search
        #Persistent searches are specified in https://www.ietf.org/proceedings/50/I-D/ldapext-psearch-03.txt
        #but not all LDAP servers implement this
        #If LDAP server does not support persistent searches, the search will run as a normal search,
        #and we will get an event of type "searchResDone"

        if event.get("type") == "searchResDone":
            print(
                "Got SearchResultsDone in Persistent Search - Persistent Search is not supported by LDAP server, falling back to polling search"
            )
            setup_poller(context, callback, search_parameters, now)
        elif event.get("type") == "searchResEntry":
            # callback must not block
            callback(event)

    now = datetime.now(tz=pytz.utc)
    connection.bind()
    search_parameters = set_search_params_modify_timestamp(search_parameters, now)
    connection.extend.standard.persistent_search(
        **search_parameters,
        streaming=False,
        callback=ad_listener,
        changes_only=True,
    )
"""


def _poller(
    connection: Connection,
    search_parameters: dict,
    callback: Callable,
    init_search_time: datetime,
    poll_time: int = 5,
) -> None:
    """
    Method to run in a thread, that polls the LDAP server every poll_time seconds,
    with a search that includes the timestamp for the last search
    and calls the `callback` for each result found
    """
    last_search_time = init_search_time
    if poll_time < 1:
        poll_time = 1
    while True:
        time.sleep(poll_time)
        timed_search_parameters = set_search_params_modify_timestamp(
            search_parameters, last_search_time
        )
        last_search_time = datetime.now(tz=pytz.utc)
        connection.search(**timed_search_parameters)
        if connection.response:
            for event in connection.response:
                if event.get("type") == "searchResEntry":
                    callback(event)


def setup_poller(
    context: Context,
    callback: Callable,
    search_parameters: dict,
    init_search_time: datetime = None,
    poll_time: int = 5,
) -> Thread:
    connection = context["user_context"]["ad_sync_connection"]
    if init_search_time is None:
        init_search_time = datetime.now(tz=pytz.utc)
    poll = Thread(
        target=_poller,
        args=(connection, search_parameters, callback, init_search_time, poll_time),
        daemon=True,
    )
    poll.start()
    return poll


def set_search_params_modify_timestamp(search_parameters: Dict, timestamp: datetime):
    changed_str = f"(modifyTimestamp>={datetime_to_ldap_timestamp(timestamp)})"
    search_filter = search_parameters["search_filter"]
    if not search_filter.startswith("(") or not search_filter.endswith(")"):
        search_filter = f"({search_filter})"
    return {
        **search_parameters,
        "search_filter": "(&" + changed_str + search_filter + ")",
    }


def datetime_to_ldap_timestamp(dt: datetime):
    return "".join(
        [
            dt.strftime("%Y%m%d%H%M%S"),
            ".",
            str(int(dt.microsecond / 1000)),
            (dt.strftime("%z") or "-0000"),
        ]
    )
