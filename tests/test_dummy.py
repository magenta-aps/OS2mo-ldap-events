from mo_ldap_events.ldap_agent import settings


def test_initial() -> None:
    print(settings)
    assert None is None
