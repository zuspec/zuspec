
from __future__ import annotations
import zuspec.dataclasses as zdc
from typing import cast, Optional, Tuple
from ..op import DmaChannelOp, DmaOp


@zdc.dataclass
class DmaChannelImpl(DmaChannelOp, zdc.Component):

    async def transfer(
            self,
            src: zdc.u32,
            dst: zdc.u32,
            size_bytes: zdc.u32,
            src_interface: zdc.u1 = 0,
            dst_interface: zdc.u1 = 0,
            increment_src: bool = True,
            increment_dst: bool = True):
        """Perform a basic memory-to-memory DMA transfer"""
        dma: DmaImplOpAlg = cast(DmaImplOpAlg, self._impl._parent)
        xfers: zdc.u32 = 0
        tot_sz: zdc.u32 = size_bytes // 4  # Convert bytes to words

        # Lock memory interface for the entire transfer
        async with dma.memif_lock:
            while xfers < tot_sz:
                src_off: zdc.u32 = xfers * 4 if increment_src else 0
                dst_off: zdc.u32 = xfers * 4 if increment_dst else 0
                data = await dma.memif.read32(src + src_off)
                await dma.memif.write32(dst + dst_off, data)
                xfers += 1

    async def transfer_chunked(
            self,
            src: zdc.u32,
            dst: zdc.u32,
            size_bytes: zdc.u32,
            chunk_bytes: zdc.u32,
            src_interface: zdc.u1 = 0,
            dst_interface: zdc.u1 = 0,
            increment_src: bool = True,
            increment_dst: bool = True):
        """Perform a chunked DMA transfer"""
        xfers: zdc.u32 = 0
        dma: DmaImplOpAlg = cast(DmaImplOpAlg, self._impl._parent)
        tot_sz: zdc.u32 = size_bytes // 4  # Convert bytes to words
        chk_sz: zdc.u32 = chunk_bytes // 4

        # Iterate over chunks
        while xfers < tot_sz:
            # Lock memory interface for the duration of a chunk
            async with dma.memif_lock:
                chk_i: zdc.u32 = 0
                while xfers < tot_sz and chk_i < chk_sz:
                    src_off: zdc.u32 = xfers * 4 if increment_src else 0
                    dst_off: zdc.u32 = xfers * 4 if increment_dst else 0
                    data = await dma.memif.read32(src + src_off)
                    await dma.memif.write32(dst + dst_off, data)
                    chk_i += 1
                    xfers += 1

    async def transfer_hw_handshake(
            self,
            src: zdc.u32,
            dst: zdc.u32,
            size_bytes: zdc.u32,
            chunk_bytes: zdc.u32,
            src_interface: zdc.u1 = 0,
            dst_interface: zdc.u1 = 0,
            increment_src: bool = True,
            increment_dst: bool = True,
            auto_restart: bool = False):
        """Perform hardware handshake DMA transfer"""
        # TODO: Implement hardware handshake logic
        # For now, delegate to chunked transfer
        await self.transfer_chunked(
            src, dst, size_bytes, chunk_bytes,
            src_interface, dst_interface,
            increment_src, increment_dst)

    async def setup_circular_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure circular buffer for source or destination"""
        # TODO: Implement circular buffer configuration
        ...

    async def setup_fifo_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            sw_ptr: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure FIFO buffer using circular buffer and software pointer"""
        # TODO: Implement FIFO buffer configuration
        ...

    async def transfer_linked_list(
            self,
            desc_addr: zdc.u32,
            chunk_bytes: Optional[zdc.u32] = None):
        """Perform DMA transfer using linked list descriptors"""
        # TODO: Implement linked list transfer
        ...

    async def set_priority(self, priority: zdc.u3):
        """Set channel priority level"""
        # TODO: Implement priority setting
        ...

    async def stop(self):
        """Stop channel operation immediately"""
        # TODO: Implement stop logic
        ...

    async def wait_complete(self):
        """Wait for current transfer to complete"""
        # TODO: Implement wait logic
        ...


@zdc.dataclass
class DmaImplOpAlg(DmaOp, zdc.Component):
    """Provides an algorithmic implementation of a DMA engine with
    Operation-level physical interfaces"""
    memif: zdc.MemIF = zdc.port()
    memif_lock: zdc.Lock = zdc.inst()

    # Annotate DMAChannelImpl as implementation?
    # TODO: can elements get parent?
    # Need channel to be able to arbitrate for
    # TODO: Support an initialization expression?
    channels: Tuple[DmaChannelOp, ...] = zdc.tuple(
        size=16, elem_factory=DmaChannelImpl)
