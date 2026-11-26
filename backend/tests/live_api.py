"""Loopback-only synthetic HTTP server; no Firebase/emulator/external services."""
from collections.abc import Generator
from contextlib import contextmanager
import socket
from threading import Thread
import time
from starlette.types import ASGIApp
import uvicorn


@contextmanager
def serve(app: ASGIApp) -> Generator[str]:
    sock=socket.socket()
    sock.bind(("127.0.0.1",0))
    port=sock.getsockname()[1]
    config=uvicorn.Config(app,host="127.0.0.1",port=port,log_level="error",access_log=False)
    server=uvicorn.Server(config)
    thread=Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True)
    thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError("Synthetic server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit=True
        thread.join(timeout=5)
        if thread.is_alive():
            server.force_exit=True
            thread.join(timeout=2)
        sock.close()
        assert not thread.is_alive(),"Synthetic server leaked a thread"
