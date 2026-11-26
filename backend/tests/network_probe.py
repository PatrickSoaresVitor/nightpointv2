"""Run only on the client network, with a mandatory externally verified DB IP."""
import errno
import ipaddress
import json
import os
import socket
import urllib.request


def probe(ip: str, subnet: str) -> None:
    address = ipaddress.ip_address(ip)
    if not address.is_private or address.is_unspecified or address not in ipaddress.ip_network(subnet):
        raise ValueError("Invalid DB IP")
    with urllib.request.urlopen("http://api:8000/api/v1/health/ready", timeout=8) as response:
        assert response.status == 200
    for host in ("db", ip):
        try:
            with socket.create_connection((host, 5432), timeout=2):
                raise AssertionError("SEC-001 violated: client reached DB")
        except socket.gaierror:
            if host != "db":
                raise
        except TimeoutError:
            pass  # A verified, reachable-from-API DB timed out across the client boundary.
        except OSError as error:
            if error.errno not in (errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ECONNREFUSED):
                raise
    print(json.dumps({"client_to_api": "allowed", "client_to_db_dns": "denied", "client_to_db_ip": "denied"}))


if __name__ == "__main__":
    probe(os.environ["NP_DB_PRIVATE_IP"], os.environ["NP_DB_CIDR"])
