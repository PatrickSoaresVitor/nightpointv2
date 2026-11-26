"""Inspect exact stack identity and run/remove one temporary client-network probe."""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str]) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True, timeout=180)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose", default=str(ROOT / "infra/compose.yaml"))
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    command = ["docker", "compose", "-p", args.project, "-f", args.compose]
    config = json.loads(run(command + ["--profile", "quality", "config", "--format", "json"]))
    if config["services"]["db"].get("ports"):
        raise ValueError("DB must not publish ports")
    data_name = config["networks"]["data"]["name"]
    client_name = config["networks"]["client"]["name"]
    database = json.loads(run(["docker", "inspect", run(command + ["ps", "-q", "db"]).strip()]))[0]
    if database["Config"]["Labels"]["com.docker.compose.project"] != args.project:
        raise ValueError("Wrong project")
    if database["HostConfig"]["PortBindings"] or set(database["NetworkSettings"]["Networks"]) != {data_name}:
        raise ValueError("Invalid DB bindings or network membership")
    network = json.loads(run(["docker", "network", "inspect", data_name]))[0]
    if not network["Internal"] or network["Labels"]["com.docker.compose.project"] != args.project:
        raise ValueError("Invalid internal network provenance")
    if set(config["services"]["client-probe"]["networks"]) != {"client"} or data_name == client_name:
        raise ValueError("Client must have a different network")
    ip = database["NetworkSettings"]["Networks"][data_name]["IPAddress"]
    subnet = network["IPAM"]["Config"][0]["Subnet"]
    address = ipaddress.ip_address(ip)
    if not address.is_private or address.is_unspecified or address not in ipaddress.ip_network(subnet):
        raise ValueError("Invalid mandatory DB IP")
    print(run(command + ["--profile", "quality", "run", "--rm", "--no-deps", "-e", "NP_DB_PRIVATE_IP=" + ip,
                         "-e", "NP_DB_CIDR=" + subnet, "client-probe"]), end="")
    print("Exact project/network/IP verified; API allowed; DB DNS and TCP denied")


if __name__ == "__main__":
    main()
