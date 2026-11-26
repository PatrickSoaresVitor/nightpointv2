import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from uuid import UUID
from .domain import CursorPosition, InvalidCursor


class SignedCursor:
    """Ephemeral per-process HMAC. Contains no readable search origin; never persisted."""
    def __init__(self) -> None:
        self._key=secrets.token_bytes(32)

    def _binding(self,binding: dict[str,object]) -> str:
        return hmac.new(self._key,json.dumps(binding,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()

    def encode(self,position: CursorPosition,binding: dict[str,object]) -> str:
        payload=json.dumps({"v":1,"b":self._binding(binding),"s":position.snapshot.isoformat(),"d":position.distance_mm,
            "i":str(position.identifier),"exp":int(time.time())+300},sort_keys=True,separators=(",",":")).encode()
        return base64.urlsafe_b64encode(payload+hmac.digest(self._key,payload,"sha256")).rstrip(b"=").decode()

    def decode(self,token: str,binding: dict[str,object]) -> CursorPosition:
        try:
            if not 1<=len(token)<=2048:raise InvalidCursor()
            raw=base64.b64decode(token+"="*(-len(token)%4),altchars=b"-_",validate=True)
            payload,signature=raw[:-32],raw[-32:]
            if not hmac.compare_digest(signature,hmac.digest(self._key,payload,"sha256")):raise InvalidCursor()
            data=json.loads(payload)
            if set(data)!={"v","b","s","d","i","exp"} or data["v"]!=1 or data["b"]!=self._binding(binding) or data["exp"]<time.time():raise InvalidCursor()
            if not isinstance(data["d"],int) or isinstance(data["d"],bool) or data["d"]<0:raise InvalidCursor()
            snapshot=datetime.fromisoformat(data["s"])
            if snapshot.tzinfo is None or snapshot>datetime.now(timezone.utc):raise InvalidCursor()
            return CursorPosition(snapshot,data["d"],UUID(data["i"]))
        except (ValueError,TypeError,KeyError,OverflowError,binascii.Error):
            raise InvalidCursor("Invalid or incompatible cursor") from None
