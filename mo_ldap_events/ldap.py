# Opret en agent der modtager amqp-events og importerer og eksporterer til LDAP
import threading
import time
from datetime import datetime
from ssl import CERT_NONE
from ssl import CERT_REQUIRED
from typing import Callable, Dict

import pytz as pytz
from fastramqpi.context import Context
from ldap3 import Connection, Server, ServerPool, Tls
from ldap3 import NTLM, RANDOM, ASYNC_STREAM, ALL

from .config import ServerConfig, Settings


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
    print("configure_ad_connection")
    """Configure an AD connection.

    Args:
        settings: The Settings instance to configure our ad connection with.

    Returns:
        ContextManager that can be opened to establish an AD connection.
    """
    servers = list(map(construct_server, settings.ad_controllers))
    # Pick the next server to use at random, discard non-active servers
    server_pool = ServerPool(servers, RANDOM, active=True, exhaust=True)
    print(server_pool)
    print(settings.ad_domain + "\\" + settings.ad_user)
    print(settings.ad_password.get_secret_value())

    print(Server(host="mo_ldap_events_test_ldap", port=1389, get_info=ALL))
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
    # connection = Connection(
    #     server=server_pool,
    #     # We always authenticate via NTLM
    #     # user=settings.ad_domain + "\\" + settings.ad_user,
    #     user=f"cn=admin,dc=ad,dc=addev",
    #     # password=settings.ad_password.get_secret_value(),
    #     password="password",
    #     # authentication=NTLM,
    #     # client_strategy=RESTARTABLE,
    #     client_strategy=client_strategy,
    #     read_only=True,
    #     pool_keepalive=True,
    #     auto_bind="DEFAULT",
    # )
    print("got connection")

    return connection


def setup_listener(context: Context, callback: Callable):
    print("setup_listener")

    connection = context["user_context"]["ad_async_connection"]

    search_parameters = {
        "search_base": "dc=ad,dc=addev",
        "search_filter": "(cn=*)",
        # search_scope=SUBTREE,
        # dereference_aliases=DEREF_NEVER,
        "attributes": ["objectGUID"],
        # controls=None,
    }

    setup_persistent_search(context, callback, search_parameters)

    # MS Persistent search, gives only modifications, not creates or deletes
    # connection.extend.microsoft.persistent_search(
    #     **{
    #         key: value
    #         for key, value in search_parameters.items()
    #         if key in ("search_base", "attributes")
    #     },
    #     streaming=False,
    #     callback=ad_listener,
    # )
    #

    # Polling search
    # setup_poller(context, callback, search_parameters, now)


def setup_persistent_search(
    context: Context, callback: Callable, search_parameters: dict
):
    connection = context["user_context"]["ad_async_connection"]

    def ad_listener(event: dict) -> None:
        """
        Callback for our persistent search
        Persistent searches are specified in https://www.ietf.org/proceedings/50/I-D/ldapext-psearch-03.txt
        but not all LDAP servers implement this
        If LDAP server does not support persistent searches, the search will run as a normal search,
        and we will get an event of type "searchResDone"
        """
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


def _poller(
    connection: Connection,
    search_parameters: dict,
    callback: Callable,
    init_search_time: datetime,
) -> None:
    """
    Method to run in a thread, that polls the LDAP server every 5 seconds,
    with a search that includes the timestamp for the last search
    and calls the `callback` for each result found
    """
    last_search_time = init_search_time
    while True:
        time.sleep(5)
        search_parameters = set_search_params_modify_timestamp(
            search_parameters, last_search_time
        )
        last_search_time = datetime.now(tz=pytz.utc)
        connection.search(**search_parameters)
        for event in connection.response:
            if event.get("type") == "searchResEntry":
                callback(event)


def setup_poller(
    context: Context,
    callback: Callable,
    search_parameters: dict,
    init_search_time: datetime = None,
):
    connection = context["user_context"]["ad_sync_connection"]
    if init_search_time is None:
        init_search_time = datetime.now(tz=pytz.utc)
    poll = threading.Thread(
        target=_poller,
        args=(connection, search_parameters, callback, init_search_time),
        daemon=True,
    )
    poll.start()


def set_search_params_modify_timestamp(search_parameters: Dict, timestamp: datetime):
    changed_str = (
        "(modifyTimestamp>="
        + timestamp.strftime("%Y%m%d%H%M%S")
        + "."
        + str(int(timestamp.microsecond / 1000))
        + (timestamp.strftime("%z") or "-0000")
        + ")"
    )
    print(changed_str)
    return {
        **search_parameters,
        "search_filter": "(&" + changed_str + search_parameters["search_filter"] + ")",
    }
