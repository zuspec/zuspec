
"""WISHBONE DMA/Bridge Core Operation-Level Interface

This module defines the operation-level interface for the WISHBONE DMA/Bridge
core. This is the driver-level interface that focuses on key device operations
rather than register-level details.

The interface is organized hierarchically with per-channel operation interfaces
grouped together, reflecting the hardware's ability to support independent
concurrent operation on multiple channels.
"""

import zuspec.dataclasses as zdc
from typing import Protocol, Tuple, Optional


@zdc.dataclass
class DmaChannelOp(Protocol):
    """Operation-level interface for a single DMA channel

    Provides high-level async methods for common DMA operations. Each channel
    can operate independently and concurrently with other channels.

    The interface abstracts away register-level details and presents operations
    in terms of what the driver needs to accomplish.
    """

    async def transfer(
            self,
            src: zdc.u32,
            dst: zdc.u32,
            size_bytes: zdc.u32,
            src_interface: zdc.u1 = 0,
            dst_interface: zdc.u1 = 0,
            increment_src: bool = True,
            increment_dst: bool = True):
        """Perform a basic memory-to-memory DMA transfer

        Args:
            src: Source address (word-aligned)
            dst: Destination address (word-aligned)
            size_bytes: Transfer size in bytes (must be multiple of 4)
            src_interface: Source WISHBONE interface (0 or 1)
            dst_interface: Destination WISHBONE interface (0 or 1)
            increment_src: Whether to increment source address
            increment_dst: Whether to increment destination address

        This implements the "Normal (Software) DMA Operation" mode from the
        specification. The transfer completes atomically without releasing
        the bus until done.
        """
        ...

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
        """Perform a chunked DMA transfer

        Args:
            src: Source address (word-aligned)
            dst: Destination address (word-aligned)
            size_bytes: Total transfer size in bytes (must be multiple of 4)
            chunk_bytes: Chunk size in bytes (must be multiple of 4, max 2KB)
            src_interface: Source WISHBONE interface (0 or 1)
            dst_interface: Destination WISHBONE interface (0 or 1)
            increment_src: Whether to increment source address
            increment_dst: Whether to increment destination address

        The transfer is broken into chunks, with the channel re-arbitrating
        between chunks. This allows fair bandwidth distribution across
        channels and lower latency for higher priority channels.
        """
        ...

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

        Args:
            src: Source address (word-aligned)
            dst: Destination address (word-aligned)
            size_bytes: Total transfer size in bytes (must be multiple of 4)
            chunk_bytes: Chunk size per trigger in bytes
                (must be multiple of 4)
            src_interface: Source WISHBONE interface (0 or 1)
            dst_interface: Destination WISHBONE interface (0 or 1)
            increment_src: Whether to increment source address
            increment_dst: Whether to increment destination address
            auto_restart: Automatically restart after completion

        Waits for external DMA_REQ signal before transferring each chunk.
        Asserts DMA_ACK after each chunk completes. Useful for peripherals
        that need flow control.
        """
        ...

    async def setup_circular_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure circular buffer for source or destination

        Args:
            base_addr: Buffer base address (must be aligned to buffer size)
            buffer_size_bytes: Buffer size in bytes
                (min 16 bytes, must be power of 2)
            interface: WISHBONE interface (0 or 1)
            is_source: True for source buffer, False for destination buffer

        Sets up the address mask for circular buffer operation. The address
        will wrap around when it reaches the end of the buffer.
        """
        ...

    async def setup_fifo_buffer(
            self,
            base_addr: zdc.u32,
            buffer_size_bytes: zdc.u32,
            sw_ptr: zdc.u32,
            interface: zdc.u1 = 0,
            is_source: bool = True):
        """Configure FIFO buffer using circular buffer and software pointer

        Args:
            base_addr: Buffer base address
            buffer_size_bytes: Buffer size in bytes
                (min 16 bytes, must be power of 2)
            sw_ptr: Initial software pointer (last location read/written by
                SW)
            interface: WISHBONE interface (0 or 1)
            is_source: True for source buffer, False for destination buffer

        The DMA will stall when it reaches the software pointer, preventing
        buffer overrun/underrun. Software must update the pointer as it
        consumes/produces data.
        """
        ...

    async def transfer_linked_list(
            self,
            desc_addr: zdc.u32,
            chunk_bytes: Optional[zdc.u32] = None):
        """Perform DMA transfer using linked list descriptors

        Args:
            desc_addr: Address of first descriptor in linked list
            chunk_bytes: Optional chunk size for chunked transfers

        Fetches descriptors from memory and processes them sequentially.
        Each descriptor contains transfer parameters and a pointer to the
        next descriptor. Stops when a descriptor with EOL bit set is reached.
        """
        ...

    async def set_priority(self, priority: zdc.u3):
        """Set channel priority level

        Args:
            priority: Priority level (0=lowest, 7=highest)

        Higher priority channels are serviced first. Channels with the same
        priority are serviced in round-robin fashion.
        """
        ...

    async def stop(self):
        """Stop channel operation immediately

        Stops any ongoing transfer and sets the error flag. The channel
        will generate an error interrupt if enabled.
        """
        ...

    async def wait_complete(self):
        """Wait for current transfer to complete

        Blocks until the DONE event is signaled, indicating the transfer
        has completed successfully.
        """
        ...


@zdc.dataclass
class DmaOp(Protocol):
    """Top-level operation interface for WISHBONE DMA/Bridge

    Provides access to all DMA channels. Each channel can operate
    independently and concurrently. This reflects the hardware architecture
    where multiple channels can be active simultaneously, with the arbiter
    selecting which channel accesses the WISHBONE interfaces based on
    priority.

    Example usage:
        # Perform transfers on multiple channels concurrently
        async def copy_data(dma):
            # Start transfers on multiple channels
            await dma.channels[0].transfer(
                src=0x1000, dst=0x2000, size_bytes=256)
            await dma.channels[1].transfer(
                src=0x3000, dst=0x4000, size_bytes=512)

        # Use hardware handshake for peripheral DMA
        async def peripheral_dma(dma):
            await dma.channels[2].transfer_hw_handshake(
                src=0x5000, dst=0x80000000,
                size_bytes=1024, chunk_bytes=64
            )
    """
    channels: Tuple[DmaChannelOp, ...] = zdc.tuple()
