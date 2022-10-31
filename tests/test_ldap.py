import asyncio
import os
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Dict
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytz
from ldap3 import Connection, ASYNC_STREAM, MOCK_ASYNC, MODIFY_REPLACE
from ldap3 import MOCK_SYNC
from ldap3 import Server

from mo_ldap_events.config import Settings
from mo_ldap_events.ldap import configure_ad_connection, setup_poller, datetime_to_ldap_timestamp
from mo_ldap_events.ldap import construct_server

@pytest.fixture
def ad_connection() -> Iterator[MagicMock]:
    """Fixture to construct a mock ad_connection.

    Yields:
        A mock for ad_connection.
    """
    yield MagicMock()


@pytest.fixture
def settings_overrides() -> Iterator[dict[str, str]]:
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
        settings_overrides: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, str]]:
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


def test_construct_server(load_settings_overrides: dict[str, str]) -> None:
    settings = Settings()
    server = construct_server(settings.ad_controllers[0])
    assert isinstance(server, Server)


def test_configure_ad_connection(load_settings_overrides: dict[str, str]) -> None:
    settings = Settings()
    connection = configure_ad_connection(settings)
    assert isinstance(connection, Connection)


def test_poller(load_settings_overrides: Dict[str, str]) -> None:
    server = Server('fake_server')
    connection = Connection(server, user='cn=user,ou=test,o=lab', password='my_password', client_strategy=MOCK_SYNC)
    connection.bind()

    def listener(event):
        objectGUID = event.get("attributes", {}).get("objectGUID", None)
        if objectGUID:
            if type(objectGUID) == list:
                hits.extend(objectGUID)
            else:
                hits.append(objectGUID)

    hits = []
    setup_poller(
        context={"user_context": {"ad_sync_connection": connection}},
        callback=listener,
        search_parameters={
            "search_base": "dc=ad",
            "search_filter": "cn=*",
            "attributes": ["objectGUID"]
        },
        poll_time=1
    )
    time.sleep(1)
    connection.strategy.add_entry(
        "dc=ad,cn=tester2,ou=test,dc=ad",
        {
            "objectGUID": "{e38bf5d7-342a-4fce-a38f-ca197625c98e}",
            "cn": "tester",
            "email": "test@example.com",
            "modifyTimestamp": datetime_to_ldap_timestamp(datetime.now(tz=pytz.utc))
        }
    )
    time.sleep(1)
    assert hits == ["{e38bf5d7-342a-4fce-a38f-ca197625c98e}"]

    del hits[:]
    connection.modify(
        "dc=ad,cn=tester2,ou=test,dc=ad",
        {
            "email": [(MODIFY_REPLACE, "test2@example.com")],
            "modifyTimestamp": [(MODIFY_REPLACE, datetime_to_ldap_timestamp(datetime.now(tz=pytz.utc)))]
        }
    )
    time.sleep(1)
    assert hits == ["{e38bf5d7-342a-4fce-a38f-ca197625c98e}"]
