import os
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Dict
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytz
from fastapi import FastAPI
from fastramqpi.main import FastRAMQPI
from ldap3 import ASYNC_STREAM
from ldap3 import Connection
from ldap3 import MOCK_ASYNC
from ldap3 import MOCK_SYNC
from ldap3 import Server

from mo_ldap_events.ldap import datetime_to_ldap_timestamp
from mo_ldap_events.main import create_app
from mo_ldap_events.main import create_fastramqpi


@pytest.fixture
def ad_sync_connection() -> Iterator[MagicMock]:
    """Fixture to construct a mock ad_connection.

    Yields:
        A mock for ad_connection.
    """
    connections = {}

    def method(settings, client_strategy):
        print("METHOD CALLED")
        if client_strategy == ASYNC_STREAM:
            client_strategy = MOCK_ASYNC
        else:
            client_strategy = MOCK_SYNC
        if client_strategy in connections:
            return connections[client_strategy]
        server = Server("fake_server")
        connections[client_strategy] = Connection(
            server,
            user="cn=user,ou=test,o=lab",
            password="my_password",
            client_strategy=client_strategy,
        )
        connections[client_strategy].bind()
        return connections[client_strategy]

    yield method


# objectGUIDs = []
# @pytest.fixture()
# def listener() -> Iterator[Callable]:
#     def _listener(event):
#         print("listener called")
#         objectGUID = event.get("attributes", {}).get("objectGUID", None)
#         objectGUIDs.append(objectGUID)
#     yield _listener


@pytest.fixture
def fastramqpi(
    disable_metrics: None, load_settings_overrides: dict[str, str]
) -> Iterator[FastRAMQPI]:
    """Fixture to construct a FastRAMQPI system.

    Yields:
        FastRAMQPI system.
    """
    with patch("mo_ldap_events.main.configure_ad_connection", new_callable=MagicMock):
        yield create_fastramqpi()


@pytest.fixture
def app(fastramqpi: FastRAMQPI) -> Iterator[FastAPI]:
    """Fixture to construct a FastAPI application.

    Yields:
        FastAPI application.
    """
    yield create_app()


@pytest.fixture
def settings_overrides() -> Iterator[Dict[str, str]]:
    """Fixture to construct dictionary of minimal overrides for valid settings.

    Yields:
        Minimal set of overrides.
    """
    overrides = {
        "AD_CONTROLLERS": '[{"host": "111.111.111.111"}]',
        "CLIENT_ID": "foo",
        "CLIENT_SECRET": "bar",
        "AD_DOMAIN": "AD",
        "AD_USER": "foo",
        "AD_PASSWORD": "foo",
        "AD_SEARCH_BASE": "DC=ad,DC=addev",
    }
    yield overrides


@pytest.fixture
def load_settings_overrides(
    settings_overrides: Dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Dict[str, str]]:
    """Fixture to set happy-path settings overrides as environmental variables.

    Note:
        Only loads environmental variables, if variables are not already set.

    Args:
        settings_overrides: The list of settings to load in.
        monkeypatch: Pytest MonkeyPatch instance to set environmental variables.

    Yields:
        Minimal set of overrides.
    """
    for key, value in settings_overrides.items():
        if os.environ.get(key) is not None:
            continue
        monkeypatch.setenv(key, value)
    yield settings_overrides


def test_poller(
    load_settings_overrides: Dict[str, str], ad_sync_connection, mocker
) -> None:
    patched_listener = mocker.patch("mo_ldap_events.main.listener")
    guid = "{e38bf5d7-342a-4fce-a38f-ca197625c98e}"
    with patch("mo_ldap_events.main.configure_ad_connection", ad_sync_connection):
        app = create_app()
        app.state.context["user_context"]["ad_sync_connection"].strategy.add_entry(
            "dc=ad,cn=tester2,ou=test,dc=ad",
            {
                "objectGUID": guid,
                "cn": "tester",
                "email": "test@example.com",
                "modifyTimestamp": datetime_to_ldap_timestamp(
                    datetime.now(tz=pytz.utc)
                ),
            },
        )
        time.sleep(6)  # Poller retries every 5 seconds
        patched_listener.assert_called()
        found_guid_lists = [
            call.args[0].get("attributes", {}).get("objectGUID", None)
            for call in patched_listener.call_args_list
        ]
        found_guids = [x for lst in found_guid_lists for x in lst]
        assert guid in found_guids
