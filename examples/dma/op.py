
from __future__ import annotations
import zuspec.dataclasses as zdc
from typing import cast, Optional, Tuple
from zuspec.dataclasses.rt.lock_rt import LockRT
from .logical import op

class Object:
    pass

@zdc.dataclass
class DmaChannelImpl(op.DmaChannel, zdc.Component):

    async def m2m(self,
                  src : zdc.u32,
                  dst : zdc.u32,
                  tot_sz : zdc.u16,
                  chk_sz : zdc.u16):
        xfers : zdc.u32 = 0
        assert self._impl is not None
        dma : DmaImpl = cast(DmaImpl, self._impl.parent)

        # Iterate over chunks
        while xfers < tot_sz:
            # Lock memory interface for the duration of a chunk
            async with dma.memif_lock:
                chk_i : zdc.u32 = 0
                while xfers < tot_sz and chk_i < chk_sz:
                    off : zdc.u32 = xfers * 4
                    data = await dma.memif.read32(src + off)
                    await dma.memif.write32(dst + off, data)
                    chk_i += 1
                    xfers += 1

@zdc.dataclass
class DmaImpl(op.Dma, zdc.Component):
    memif : zdc.MemIF = zdc.port()
    memif_lock : zdc.Lock = zdc.inst()

    # Annotate DMAChannelImpl as implementation?
    # TODO: can elements get parent?
    # Need channel to be able to arbitrate for 
    # TODO: Support an initialization expression?
    channels : Tuple[op.DmaChannel, ...] = zdc.tuple(size=16, elem_factory=DmaChannelImpl)


