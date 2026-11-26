"""Bound a project-owned command and clean up its CLI descendants on timeout."""
import os
from pathlib import Path
import signal
import subprocess
from collections.abc import Mapping

def bounded_run(args: list[str], *, cwd: Path, env: Mapping[str,str] | None = None,
                capture_output: bool = False, text: bool = True,
                check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    if not text: raise ValueError('Text command output required')
    process = subprocess.Popen(args,cwd=cwd,env=env,text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
        start_new_session=os.name!='nt')
    try:
        stdout,stderr=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                    capture_output=True,text=True,timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:os.killpg(process.pid,signal.SIGKILL)
        process.wait(timeout=15)
        raise
    result=subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
    if check:result.check_returncode()
    return result
