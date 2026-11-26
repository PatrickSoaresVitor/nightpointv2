from typing import Protocol
from .domain import CursorPosition


class CursorCodec(Protocol):
    def encode(self,position: CursorPosition,binding: dict[str,object]) -> str: ...
    def decode(self,token: str,binding: dict[str,object]) -> CursorPosition: ...
