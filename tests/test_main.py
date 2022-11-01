import os
from collections.abc import Iterator
from typing import Dict
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastramqpi.main import FastRAMQPI
from mo_ldap_events.main import create_fastramqpi
from mo_ldap_events.main import create_app


@pytest.fixture
def ad_connection() -> Iterator[MagicMock]:
    """Fixture to construct a mock ad_connection.

    Yields:
        A mock for ad_connection.
    """
    yield MagicMock()


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


def test_create_app(
    load_settings_overrides: dict[str, str],
) -> None:
    """Test that we can construct our FastAPI application."""

    with patch("mo_ldap_events.main.configure_ad_connection", new_callable=MagicMock):
        app = create_app()
    assert isinstance(app, FastAPI)
