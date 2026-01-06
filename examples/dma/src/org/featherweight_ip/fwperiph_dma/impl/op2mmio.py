"""Operation to MMIO adapter for WISHBONE DMA/Bridge

This module implements the Operation-level API by translating high-level
async operations into MMIO register read/write sequences according to the
WISHBONE DMA/Bridge specification.
"""

from __future__ import annotations
import zuspec.dataclasses as zdc
from typing import cast, Optional, Tuple
from ..op import DmaOp, DmaChannelOp
from ..mmio import (
    DmaMMIO, DmaChannel, DmaChannelCSR, DmaChannelSZ,
    DmaChannelAddr, DmaChannelAddrMask, DmaChannelSWPtr, DmaChannelDesc
)


@zdc.dataclass
class DmaChannelOp2MMIO(DmaChannelOp, zdc.Component):
    """Per-channel Operation to MMIO adapter

    Implements the DmaChannelOp interface by programming the MMIO registers
    according to the DMA specification.
    """

    def _get_parent_mmio(self) -> DmaMMIO:
        """Get the parent DMA's MMIO interface"""
        parent = cast(DmaOp2MMIO, self.parent)
        return parent.mmio

    def _get_channel_idx(self) -> int:
        """Get this channel's index in the parent's channel tuple"""
        parent = cast(DmaOp2MMIO, self.parent)
        for i, ch in enumerate(parent.channels):
            if ch is self:
                return i
        raise RuntimeError("Channel not found in parent")

    def _get_mmio_channel(self) -> DmaChannel:
        """Get the MMIO channel interface for this channel"""
        mmio = self._get_parent_mmio()
        idx = self._get_channel_idx()
        return mmio.channels[idx]

    async def transfer(
            self,
            src: zdc.u32,
            dst: zdc.u32,
            size_bytes: zdc.u32,
            src_interface: zdc.u1 = 0,
            dst_interface: zdc.u1 = 0,
            increment_src: bool = True,
            increment_dst: bool = True):
        """Perform basic memory-to-memory transfer (Normal DMA Operation)

        Programs the channel registers for a simple block copy without
        chunking. Sets CHK_SZ=0 so the entire transfer completes atomically.
        """
        ch = self._get_mmio_channel()

        # Convert bytes to 32-bit words
        tot_sz = size_bytes >> 2
        assert tot_sz <= 0xFFF, "Transfer size exceeds max (16KB)"

        # Configure addresses
        await ch.regs.a0.write(DmaChannelAddr(address=src >> 2))
        await ch.regs.a1.write(DmaChannelAddr(address=dst >> 2))

        # Configure size (CHK_SZ=0 for non-chunked)
        await ch.regs.sz.write(DmaChannelSZ(tot_sz=tot_sz, chk_sz=0))

        # Configure and enable channel
        csr = DmaChannelCSR(
            ch_en=1,
            src_sel=src_interface,
            dst_sel=dst_interface,
            inc_src=1 if increment_src else 0,
            inc_dst=1 if increment_dst else 0,
            mode=0,  # Normal mode (not HW handshake)
            ine_done=1  # Enable done interrupt
        )
        await ch.regs.csr.write(csr)

        # Wait for transfer to complete
        await ch.done.wait()

        # Check for errors
        result_csr = await ch.regs.csr.read()
        if result_csr.err:
            ch_idx = self._get_channel_idx()
            raise RuntimeError(f"DMA transfer error on channel {ch_idx}")

        # Clear the channel enable bit
        await ch.regs.csr.write(DmaChannelCSR(ch_en=0))

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
        """Perform chunked DMA transfer

        Programs the channel with CHK_SZ to break the transfer into chunks.
        The channel re-arbitrates between chunks for fair bus access.
        """
        ch = self._get_mmio_channel()

        # Convert bytes to 32-bit words
        tot_sz = size_bytes >> 2
        chk_sz = chunk_bytes >> 2
        assert tot_sz <= 0xFFF, "Total size exceeds max (16KB)"
        assert chk_sz <= 0x1FF, "Chunk size exceeds max (2KB)"
        assert chk_sz > 0, "Chunk size must be > 0 for chunked transfers"

        # Configure addresses
        await ch.regs.a0.write(DmaChannelAddr(address=src >> 2))
        await ch.regs.a1.write(DmaChannelAddr(address=dst >> 2))

        # Configure size with chunking
        await ch.regs.sz.write(DmaChannelSZ(tot_sz=tot_sz, chk_sz=chk_sz))

        # Configure and enable channel
        csr = DmaChannelCSR(
            ch_en=1,
            src_sel=src_interface,
            dst_sel=dst_interface,
            inc_src=1 if increment_src else 0,
            inc_dst=1 if increment_dst else 0,
            mode=0,  # Normal mode
            ine_done=1
        )
        await ch.regs.csr.write(csr)

        # Wait for completion
        await ch.done.wait()

        # Check for errors
        result_csr = await ch.regs.csr.read()
        if result_csr.err:
            ch_idx = self._get_channel_idx()
            raise RuntimeError(f"DMA transfer error on channel {ch_idx}")

        # Disable channel
        await ch.regs.csr.write({DmaChannelCSR.ch_en: 0})

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
        """Perform hardware handshake DMA transfer

        Enables MODE=1 for HW handshake. Each chunk is triggered by
        external DMA_REQ_I and acknowledged via DMA_ACK_O.
        """
        ch = self._get_mmio_channel()

        # Convert bytes to 32-bit words
        tot_sz = size_bytes >> 2
        chk_sz = chunk_bytes >> 2
        assert tot_sz <= 0xFFF, "Total size exceeds max (16KB)"
        assert chk_sz <= 0x1FF, "Chunk size exceeds max (2KB)"
        assert chk_sz > 0, "Chunk size must be > 0 for HW handshake"

        # Configure addresses
        await ch.regs.a0.write(DmaChannelAddr(address=src >> 2))
        await ch.regs.a1.write(DmaChannelAddr(address=dst >> 2))

        # Configure size
        await ch.regs.sz.write(DmaChannelSZ(tot_sz=tot_sz, chk_sz=chk_sz))

        # Configure and enable channel with HW handshake mode
        csr = DmaChannelCSR(
            ch_en=1,
            src_sel=src_interface,
            dst_sel=dst_interface,
            inc_src=1 if increment_src else 0,
            inc_dst=1 if increment_dst else 0,
            mode=1,  # HW handshake mode
            ars=1 if auto_restart else 0,
            ine_done=1
        )
        await ch.regs.csr.write(csr)

        # Wait for completion (unless auto_restart, in which case this
        # runs forever)
        if not auto_restart:
            await ch.done.wait()

            # Check for errors
            result_csr = await ch.regs.csr.read()
            if result_csr.err:
                ch_idx = self._get_channel_idx()
                err_msg = f"DMA transfer error on channel {ch_idx}"
                raise RuntimeError(err_msg)

            # Disable channel
            await ch.regs.csr.write(DmaChannelCSR(ch_en=0))

    async def setup_circular_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure circular buffer using address mask registers

        The mask determines which address bits wrap around. For a buffer
        of size N bytes, mask should have (N/4 - 1) in the lower bits.
        """
        ch = self._get_mmio_channel()

        # Buffer size must be power of 2 and at least 16 bytes
        assert buffer_size_bytes >= 16, \
            "Buffer size must be at least 16 bytes"
        assert (buffer_size_bytes & (buffer_size_bytes - 1)) == 0, \
            "Buffer size must be power of 2"

        # Calculate mask: all bits up to buffer size should be 1
        # For a 64-byte buffer (16 words), mask bits [5:2] should be 1111
        mask = (buffer_size_bytes - 1) >> 2  # Convert to word addressing

        # Set the address mask for source or destination
        if is_source:
            await ch.regs.am0.write(DmaChannelAddrMask(mask=mask))
        else:
            await ch.regs.am1.write(DmaChannelAddrMask(mask=mask))

    async def setup_fifo_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            sw_ptr: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure FIFO buffer with circular buffer and software pointer

        First sets up circular buffer, then enables software pointer
        to prevent DMA from crossing the pointer (preventing
        overrun/underrun).
        """
        ch = self._get_mmio_channel()

        # First set up circular buffer
        await self.setup_circular_buffer(
            base_addr, buffer_size_bytes, interface, is_source)

        # Enable software pointer
        await ch.regs.swptr.write(DmaChannelSWPtr(
            swptr=sw_ptr >> 2,  # Convert to word address
            swptr_en=1
        ))

    async def transfer_linked_list(
            self,
            desc_addr: zdc.u32,
            chunk_bytes: Optional[zdc.u32] = None):
        """Perform DMA transfer using linked list descriptors

        Enables USE_ED bit to fetch descriptors from memory. The DMA
        engine will follow the linked list until EOL bit is set.
        """
        ch = self._get_mmio_channel()

        # Set descriptor pointer
        await ch.regs.desc.write(DmaChannelDesc(desc_addr=desc_addr >> 2))

        # If chunk size specified, program it
        if chunk_bytes is not None:
            chk_sz = chunk_bytes >> 2
            assert chk_sz <= 0x1FF, "Chunk size exceeds max (2KB)"
            # Read current size register, update chunk size only
            sz = await ch.regs.sz.read()
            await ch.regs.sz.write(
                DmaChannelSZ(tot_sz=sz.tot_sz, chk_sz=chk_sz))

        # Enable channel with external descriptor mode
        csr = DmaChannelCSR(
            ch_en=1,
            use_ed=1,  # Use external descriptors
            ine_done=1
        )
        await ch.regs.csr.write(csr)

        # Wait for completion
        await ch.done.wait()

        # Check for errors
        result_csr = await ch.regs.csr.read()
        if result_csr.err:
            ch_idx = self._get_channel_idx()
            raise RuntimeError(f"DMA transfer error on channel {ch_idx}")

        # Disable channel
        await ch.regs.csr.write(DmaChannelCSR(ch_en=0))

    async def set_priority(self, priority: zdc.u3):
        """Set channel priority level

        Priority can be changed dynamically. Higher values = higher priority.
        """
        ch = self._get_mmio_channel()

        # Read current CSR, modify priority, write back
        csr = await ch.regs.csr.read()
        csr.priority = priority
        await ch.regs.csr.write(csr)

    async def stop(self):
        """Stop channel immediately by setting STOP bit

        This forces the channel to stop and sets the error flag.
        """
        ch = self._get_mmio_channel()

        # Write STOP bit (write-only bit)
        await ch.regs.csr.write(DmaChannelCSR(stop=1))

        # Wait for error event
        await ch.error.wait()

    async def wait_complete(self):
        """Wait for current transfer to complete

        Blocks until the done event is signaled.
        """
        ch = self._get_mmio_channel()
        await ch.done.wait()


@zdc.dataclass
class DmaOp2MMIO(DmaOp, zdc.Component):
    """Top-level Operation to MMIO adapter for WISHBONE DMA/Bridge

    Provides the DmaOp interface by delegating to per-channel adapters
    that translate operations into MMIO register accesses.

    The MMIO interface must be provided during initialization, typically
    connected to a register file implementation or bus interface.
    """
    mmio: DmaMMIO = zdc.field()  # Expect this to be populated during init

    # Create channel adapters that implement the operation interface
    channels: Tuple[DmaChannelOp, ...] = zdc.tuple(
        size=4, elem_factory=DmaChannelOp2MMIO)

    def __post_init__(self):
        """Post-initialization hook for additional setup"""
        pass
