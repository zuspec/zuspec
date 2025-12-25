
import zuspec.dataclasses as zdc
from typing import Protocol, Tuple

@zdc.dataclass
class DmaChannel(Protocol):

    async def configure(self):
        ...

    async def m2m(self,
                  src : zdc.u32,
                  dst : zdc.u32,
                  tot_sz : zdc.u16,
                  chk_sz : zdc.u16):
        ...

@zdc.dataclass
class Dma(Protocol):
    channels : Tuple[DmaChannel, ...] = zdc.tuple(size=16)

