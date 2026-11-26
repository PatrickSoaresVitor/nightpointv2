"""Create and verify an independent disposable cluster; never target development."""
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from uuid import uuid4
from typing import Any, cast

from private_files import create_directory, write_private
from processes import bounded_run
from academic_image import verified_image

ROOT = Path(__file__).resolve().parents[1]


def selected_pytest_cases(arguments: list[str]) -> list[str] | None:
    """Finite selectors only, validated before creating a disposable target."""
    if not any(flag in arguments for flag in ('--pytest-only','--pytest-cases')):
        return None
    if '--pytest-only' in arguments and '--pytest-cases' in arguments:
        raise ValueError('Choose one pytest selection mode')
    if "--" not in arguments:
        raise ValueError("Provide explicit pytest selectors after --")
    cases = arguments[arguments.index("--")+1:]
    if not cases or len(cases) != len(set(cases)) or any(
        re.fullmatch(r"tests/test_[a-z0-9_]+\.py(?:::[A-Za-z0-9_\[\]-]+)*",case) is None for case in cases
    ):
        raise ValueError("Expected unique finite tests/test_*.py selectors")
    return cases


def main() -> None:
    if any(flag in sys.argv for flag in ('--performance','--performance-only','--capacity-only')):
        raise ValueError('Advanced benchmarks are outside the academic package')
    cases = selected_pytest_cases(sys.argv[1:])
    demo = '--demo' in sys.argv
    if demo and any(flag in sys.argv for flag in ('--pytest-only','--pytest-cases','--checks-only','--performance','--performance-only','--capacity-only')):
        raise ValueError('Synthetic demo is a separate explicit composition')
    if cases is not None and "--checks-only" in sys.argv:
        raise ValueError("Select either pytest-only or checks-only")
    run_id = uuid4().hex
    project = "nightpoint-foundation-audit-" + run_id[:12]
    source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                   capture_output=True, text=True).stdout.strip()
    if demo and subprocess.run(['git','status','--porcelain','--','backend','infra','contracts'],cwd=ROOT,
        capture_output=True,text=True,check=True).stdout.strip():
        raise RuntimeError('Commit the synthetic demo composition before starting it')
    directory = ROOT / "infra/local/test-runs" / run_id
    create_directory(directory)
    for name in ("admin_password", "runtime_password", "migrator_password", "test_token"):
        write_private(directory / name, secrets.token_urlsafe(36))
    # Required only for entirely synthetic files in an isolated disposable Linux CI runner.
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.name != "nt":
        for path in directory.iterdir():
            path.chmod(0o644)
    network_ids = subprocess.run(["docker","network","ls","-q"],check=True,capture_output=True,text=True).stdout.split()
    networks: list[dict[str,Any]] = json.loads(subprocess.run(["docker","network","inspect",*network_ids],check=True,capture_output=True,text=True).stdout)
    occupied: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for network in networks:
        for config in cast(list[dict[str,Any]],network["IPAM"].get("Config") or []):
            subnet = config.get("Subnet")
            if isinstance(subnet,str):
                occupied.append(ipaddress.ip_network(subnet))
    candidates = list(ipaddress.ip_network("10.254.0.0/16").subnets(new_prefix=28))
    offset = int(run_id[:4],16) % len(candidates)
    available = [candidates[(offset+i)%len(candidates)] for i in range(len(candidates))
                 if not any(candidates[(offset+i)%len(candidates)].overlaps(network)
                            for network in occupied if network.version == 4)]
    if len(available) < 2:
        raise RuntimeError("No non-overlapping dedicated test subnets available")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1",0))
        api_port=listener.getsockname()[1]
    environment = dict(os.environ, NP_TEST_RUN_DIR=str(directory), NP_TEST_API_PORT=str(api_port),
                       NP_TEST_DATA_SUBNET=str(available[0]),NP_TEST_CLIENT_SUBNET=str(available[1]),
                       NP_TEST_ARTIFACT_DIR=str(ROOT / ".artifacts/block03_1" / run_id))
    command = ["docker", "compose", "-p", project, "-f", str(ROOT / "infra/compose.test.yaml")]
    if demo:command += ['-f',str(ROOT/'infra/compose.demo.yaml')]

    def run(arguments: list[str], capture: bool = False) -> str:
        result = bounded_run(arguments, env=environment, cwd=ROOT, check=True,
                                capture_output=capture, text=True, timeout=600)
        return result.stdout if capture else ""

    if run(command + ["ps", "-aq"], True).strip():
        raise RuntimeError("Unexpected preexisting disposable project")
    (directory / "receipt.json").touch(mode=0o600)  # No proof until admin bootstrap is verified.
    write_private(directory / "run.json", json.dumps({"project": project, "directory": str(directory)}))
    artifacts = ROOT / ".artifacts/block03_1" / run_id
    artifacts.mkdir(parents=True, exist_ok=False)
    (artifacts / "preparation.json").write_text(json.dumps({"commit":source_commit,"project":project,
        "run_id":run_id,"stage":"bootstrap","attested":False}),encoding="utf-8")
    retained_demo = False
    try:
        run(command + ["up", "-d", "--wait", "--wait-timeout", "180", "db"])
        db_id = run(command + ["ps", "-q", "db"], True).strip()
        metadata = json.loads(run(["docker", "inspect", db_id], True))[0]
        if metadata["Config"]["Labels"]["com.docker.compose.project"] != project:
            raise RuntimeError("Container identity mismatch")
        volumes = [m for m in metadata["Mounts"] if m["Type"] == "volume"]
        if len(volumes) != 1 or volumes[0]["Name"] != project + "_pgdata":
            raise RuntimeError("Unexpected test volume")
        volume = json.loads(run(["docker", "volume", "inspect", volumes[0]["Name"]], True))[0]
        if volume["Labels"]["com.docker.compose.project"] != project:
            raise RuntimeError("Volume provenance mismatch")
        output = run(command + ["exec", "-T", "db", "psql", "-U", "np_admin", "-d", "nightpoint_test", "-Atc",
            "SELECT system_identifier||'|'||database_oid||'|'||token_hash FROM test_guard.identity_proof()"], True)
        identifier, oid, digest = output.strip().split("|")
        expected_hash = hashlib.sha256((directory / "test_token").read_bytes()).hexdigest()
        if digest != expected_hash:
            raise RuntimeError("Bootstrap attestation mismatch")
        receipt = {"environment": "disposable-test", "system_identifier": identifier,
                   "database_oid": int(oid), "token_hash": digest}
        (directory / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        (artifacts / "preparation.json").write_text(json.dumps({"commit":source_commit,"project":project,
            "run_id":run_id,"stage":"attested","attested":True}),encoding="utf-8")
        cached_image=verified_image(ROOT) if demo else None
        run(command + ["up", "--no-build" if cached_image else "--build", "-d", "--wait", "--wait-timeout", "180", "api"])
        (artifacts / "source.json").write_text(json.dumps({"commit": source_commit, "project": project,
            "environment": "disposable-attested", "run_id": run_id, "loopback_port":api_port,
            "data_subnet":str(available[0]),"client_subnet":str(available[1]),"api_image_id":json.loads(run(["docker","inspect",run(command+["ps","-q","api"],True).strip()],True))[0]["Image"]}), encoding="utf-8")
        phases: list[tuple[str,list[str]]] = [
            ("pytest", command + ["--profile", "quality", "run", "--rm", "--no-deps", "tests", "python", "-m", "pytest", "-v", "-p", "no:cacheprovider"]),
            ("pip", command + ["--profile", "quality", "run", "--rm", "--no-deps", "tests", "python", "-m", "pip", "check"]),
            ("pyright", command + ["--profile", "quality", "run", "--rm", "--no-deps", "tests", "python", "-m", "pyright"]),
            ("network", [sys.executable, str(ROOT / "infra/verify.py"), "--compose", str(ROOT / "infra/compose.test.yaml"), "--project", project]),
        ]
        if cases is not None:
            phases[0] = ("pytest",command + ["--profile","quality","run","--rm","--no-deps","tests",
                "python","-m","pytest","-v","-p","no:cacheprovider",*cases])
            if '--pytest-only' in sys.argv:phases=phases[:1]
        if "--checks-only" in sys.argv:
            phases = [(name,arguments) for name,arguments in phases if name != "pytest"]
        code_dirty = bool(subprocess.run(["git","status","--porcelain","--","backend","infra","contracts"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip())
        source_path=artifacts/"source.json"
        source_data=json.loads(source_path.read_text(encoding="utf-8"))
        source_data.update({"code_worktree_dirty":code_dirty,
            "git_status_porcelain":subprocess.run(["git","status","--porcelain"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines(),
            "requested_arguments":sys.argv[1:],"db_image_id":metadata["Image"],
            "quality_image_id":json.loads(run(["docker","image","inspect","nightpoint-academic-api:local"],True))[0]["Id"],
            "worktree_files":{str(path.relative_to(ROOT)).replace("\\","/"):hashlib.sha256(path.read_bytes()).hexdigest()
                for directory_name in ("backend","infra","contracts") for path in (ROOT/directory_name).rglob("*")
                if path.is_file() and path.suffix in {".py",".toml",".yaml"} and "local" not in path.parts and "__pycache__" not in path.parts},
            "docker_resources":json.loads(run(["docker","info","--format",'{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'],True)),
            "backend_tree":subprocess.run(["git","rev-parse","HEAD:backend"],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()})
        source_path.write_text(json.dumps(source_data),encoding="utf-8")
        if demo:
            api_metadata=json.loads(run(['docker','inspect',run(command+['ps','-q','api'],True).strip()],True))[0]
            bindings: dict[str,list[dict[str,str]]] = api_metadata['HostConfig']['PortBindings'] or {}
            if (set(bindings)!={'8000/tcp'} or len(bindings['8000/tcp'])!=1
                or bindings['8000/tcp'][0].get('HostIp')!='127.0.0.1'
                or bindings['8000/tcp'][0].get('HostPort')!=str(api_port)
                or metadata['HostConfig']['PortBindings']):
                raise RuntimeError('Synthetic demo requires loopback-only API and an unpublished database')
            demo_state={'mode':'synthetic','project':project,'run_id':run_id,'commit':source_commit,
                'api_url':f'http://127.0.0.1:{api_port}','web_origin':environment.get('NP_DEMO_WEB_ORIGIN','http://127.0.0.1:5173'),
                'initial_state':'ready-attested','stop_command':f'python infra/stop_demo.py {run_id}'}
            (artifacts/'demo-state.json').write_text(json.dumps(demo_state,indent=2),encoding='utf-8')
            (artifacts/'hashes.json').write_text(json.dumps({path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                for path in artifacts.iterdir() if path.is_file() and path.name!='hashes.json'},sort_keys=True),encoding='utf-8')
            retained_demo = True
            print('Synthetic local demo ready: '+json.dumps(demo_state),flush=True)
            return
        if any(name in {"performance","capacity"} for name,_ in phases) and code_dirty:
            raise RuntimeError("Commit code before a reproducible performance run")
        failed: list[str] = []
        phase_results: dict[str,int] = {}
        for name, arguments in phases:
            print("Running " + name + " for " + project,flush=True)
            result = subprocess.run(arguments, env=environment, cwd=ROOT, capture_output=True,
                                    text=True, timeout=600)
            output = result.stdout + result.stderr
            (artifacts / (name + ".txt")).write_text(output, encoding="utf-8")
            phase_results[name] = result.returncode
            (artifacts / "phase-results.json").write_text(json.dumps(phase_results,sort_keys=True),encoding="utf-8")
            print(output, end="", flush=True)
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts.iterdir() if p.is_file() and p.name!="hashes.json"}
            (artifacts/"hashes.json").write_text(json.dumps(hashes,sort_keys=True),encoding="utf-8")
            if result.returncode:
                failed.append(name)
                if name in {"performance","capacity"}:
                    raise RuntimeError(f"{name} failed; output preserved at {artifacts / (name + '.txt')}")
        if failed:
            raise RuntimeError("Disposable checks failed: " + ",".join(failed) + "; evidence=" + str(artifacts))
        print("Requested disposable phases completed: " + ",".join(name for name,_ in phases) + "; project=" + project)
    finally:
        if not retained_demo:
            run(command + ["stop"])
            print("Stopped only the disposable project; retained its volume and private run receipt")
        else:
            print('Retained only the authorized synthetic demo; use its recorded stop command')


if __name__ == "__main__":
    main()
