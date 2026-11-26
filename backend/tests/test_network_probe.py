from typing import Self
import socket
import pytest
from tests import network_probe


class Response:
    status = 200

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def response(*_args: object, **_kwargs: object) -> Response:
    return Response()


@pytest.mark.parametrize("address", ["", "db", "0.0.0.0", "192.168.99.1"])
def test_invalid_ip_never_counts_as_isolation(address: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Network must not be accessed for an invalid target")
    monkeypatch.setattr(network_probe.urllib.request, "urlopen", unexpected)
    with pytest.raises(ValueError):
        network_probe.probe(address, "172.27.0.0/16")


def test_open_database_connection_is_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(network_probe.urllib.request, "urlopen", response)
    monkeypatch.setattr(network_probe.socket, "create_connection", response)
    with pytest.raises(AssertionError, match="client reached DB"):
        network_probe.probe("172.27.0.2", "172.27.0.0/16")


def test_dns_denial_and_verified_ip_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(network_probe.urllib.request, "urlopen", response)

    def refused(address: tuple[str, int], **_kwargs: object) -> None:
        if address[0] == "db":
            raise socket.gaierror("synthetic DNS denial")
        raise TimeoutError("synthetic boundary timeout")

    monkeypatch.setattr(network_probe.socket, "create_connection", refused)
    network_probe.probe("172.27.0.2", "172.27.0.0/16")
