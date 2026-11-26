"""Restrict only project-owned synthetic files; refuse unsafe existing paths."""
import csv
import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import shutil


def windows_sid() -> str:
    row = next(csv.reader(io.StringIO(subprocess.check_output(
        ["whoami", "/user", "/fo", "csv", "/nh"], text=True))))
    return row[1]


def verify_private(path: Path) -> None:
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise ValueError("Redirected private path refused")
    if os.name == "nt":
        literal = str(path).replace("'", "''")
        script = "$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath '" + literal + "'; @{owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value; identities=@($a.Access | Where-Object AccessControlType -eq Allow | ForEach-Object {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value})} | ConvertTo-Json -Compress"
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        environment = dict(os.environ)
        environment.pop("PSModulePath", None)  # Do not pass PowerShell 7 module paths to Windows PowerShell.
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            raise ValueError("PowerShell ACL verification unavailable")
        result = subprocess.run([shell, "-NoProfile", "-EncodedCommand", encoded], env=environment, capture_output=True, text=True, check=True)
        acl = json.loads(result.stdout)
        identities = acl["identities"]
        owner = windows_sid()
        if acl["owner"] != owner or not identities or set(identities) - {owner, "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}:
            raise ValueError("Private ACL is not restricted to owner/system/administrators")
    elif path.stat().st_uid != os.getuid() or path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("Private file permissions are too broad")


def create_directory(directory: Path) -> None:
    if any(item.is_symlink() or item.is_junction() for item in (directory, *directory.parents)):
        raise ValueError("Redirected private directory refused")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == "nt":
        subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r",
                        f"*{windows_sid()}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                        "*S-1-5-32-544:(OI)(CI)F"], check=True, capture_output=True)
    verify_private(directory)


def write_private(path: Path, value: str) -> None:
    verify_private(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
    verify_private(path)
