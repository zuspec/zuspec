"""WISHBONE DMA/Bridge Core Register Model

This module defines the register interface for the WISHBONE DMA/Bridge core
as described in the OpenCores WISHBONE DMA/Bridge specification Rev. 1.5.

The DMA core supports up to 31 DMA channels with configurable priorities,
linked list descriptors, circular buffers, and hardware handshake support.

This is the logical view of MMIO. 
"""

import zuspec.dataclasses as zdc
from typing import Protocol, Tuple, Type


@zdc.dataclass
class DmaMainCSR(zdc.PackedStruct):
    """Main Configuration and Status Register (CSR) - Offset 0x00
    
    Controls the overall DMA engine operation.
    
    Bit layout:
    [0]     - PAUSE: Pause/Resume DMA engine
    [31:1]  - Reserved
    """
    pause : zdc.u1 = zdc.field(default=0)
    reserved : zdc.u31 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelCSR(zdc.PackedStruct):
    """Channel Control/Status Register (CHn_CSR)
    
    Configures channel operation mode and reports status.
    
    Bit layout:
    [0]     - CH_EN: Channel Enable
    [1]     - DST_SEL: Destination Interface Select (0=IF0, 1=IF1)
    [2]     - SRC_SEL: Source Interface Select (0=IF0, 1=IF1)
    [3]     - INC_DST: Increment Destination Address
    [4]     - INC_SRC: Increment Source Address
    [5]     - MODE: Transfer Mode (0=Normal, 1=HW Handshake)
    [6]     - ARS: Auto Restart
    [7]     - USE_ED: Use External Descriptor
    [8]     - SZ_WB: Size Write Back Enable
    [9]     - STOP: Stop Channel (Write Only)
    [10]    - BUSY: Channel Busy (Read Only)
    [11]    - DONE: Channel Done (Read Only)
    [12]    - ERR: Channel Error (Read Only)
    [15:13] - Priority: Channel Priority (0-7)
    [16]    - REST_EN: Hardware Restart Enable
    [17]    - INE_ERR: Interrupt Enable on Error
    [18]    - INE_DONE: Interrupt Enable on Done
    [19]    - INE_CHK_DONE: Interrupt Enable on Chunk Done
    [20]    - INT_ERR: Interrupt Source - Error
    [21]    - INT_DONE: Interrupt Source - Done
    [22]    - INT_CHK_DONE: Interrupt Source - Chunk Done
    [31:23] - Reserved
    """
    ch_en : zdc.u1 = zdc.field(default=0)
    dst_sel : zdc.u1 = zdc.field(default=0)
    src_sel : zdc.u1 = zdc.field(default=0)
    inc_dst : zdc.u1 = zdc.field(default=0)
    inc_src : zdc.u1 = zdc.field(default=0)
    mode : zdc.u1 = zdc.field(default=0)
    ars : zdc.u1 = zdc.field(default=0)
    use_ed : zdc.u1 = zdc.field(default=0)
    sz_wb : zdc.u1 = zdc.field(default=0)
    stop : zdc.u1 = zdc.field(default=0)
    busy : zdc.u1 = zdc.field(default=0)
    done : zdc.u1 = zdc.field(default=0)
    err : zdc.u1 = zdc.field(default=0)
    priority : zdc.u3 = zdc.field(default=0)
    rest_en : zdc.u1 = zdc.field(default=0)
    ine_err : zdc.u1 = zdc.field(default=0)
    ine_done : zdc.u1 = zdc.field(default=0)
    ine_chk_done : zdc.u1 = zdc.field(default=0)
    int_err : zdc.u1 = zdc.field(default=0)
    int_done : zdc.u1 = zdc.field(default=0)
    int_chk_done : zdc.u1 = zdc.field(default=0)
    reserved : zdc.u9 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelSZ(zdc.PackedStruct):
    """Channel Size Register (CHn_SZ)
    
    Specifies total and chunk transfer sizes.
    
    Bit layout:
    [11:0]  - TOT_SZ: Total Transfer Size (in 32-bit words, max 16KB)
    [15:12] - Reserved
    [24:16] - CHK_SZ: Chunk Transfer Size (in 32-bit words, max 2KB)
    [31:25] - Reserved
    """
    tot_sz : zdc.u12 = zdc.field(default=0)
    reserved0 : zdc.u4 = zdc.field(default=0)
    chk_sz : zdc.u9 = zdc.field(default=0)
    reserved1 : zdc.u7 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelAddr(zdc.PackedStruct):
    """Channel Address Register (CHn_A0, CHn_A1)
    
    Specifies source (A0) or destination (A1) address.
    
    Bit layout:
    [1:0]   - Reserved
    [31:2]  - Address: 30-bit word-aligned address
    """
    reserved : zdc.u2 = zdc.field(default=0)
    address : zdc.u30 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelAddrMask(zdc.PackedStruct):
    """Channel Address Mask Register (CHn_AM0, CHn_AM1)
    
    Specifies increment mask for circular buffers.
    
    Bit layout:
    [3:0]   - Reserved
    [31:4]  - Address Mask: Mask applied to address increment
    """
    reserved : zdc.u4 = zdc.field(default=0)
    mask : zdc.u28 = zdc.field(default=0x0FFFFFFF)


@zdc.dataclass
class DmaChannelDesc(zdc.PackedStruct):
    """Channel Descriptor Pointer Register (CHn_DESC)
    
    Points to linked list descriptor in memory.
    
    Bit layout:
    [1:0]   - Reserved
    [31:2]  - Descriptor Address: Pointer to descriptor
    """
    reserved : zdc.u2 = zdc.field(default=0)
    desc_addr : zdc.u30 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelSWPtr(zdc.PackedStruct):
    """Channel Software Pointer Register (CHn_SWPTR)
    
    Software-managed pointer for FIFO buffer implementation.
    
    Bit layout:
    [1:0]   - Reserved
    [30:2]  - Software Pointer: Last location read/written by software
    [31]    - SWPTR_EN: Software Pointer Enable
    """
    reserved : zdc.u2 = zdc.field(default=0)
    swptr : zdc.u29 = zdc.field(default=0)
    swptr_en : zdc.u1 = zdc.field(default=0)


@zdc.dataclass
class DmaChannelRegs(zdc.RegFile):
    """Register set for a single DMA channel
    
    Each channel has 8 registers (32 bytes total):
    +0x00 - CSR: Control/Status Register
    +0x04 - SZ: Size Register
    +0x08 - A0: Address 0 (Source)
    +0x0C - AM0: Address Mask 0 (Source)
    +0x10 - A1: Address 1 (Destination)
    +0x14 - AM1: Address Mask 1 (Destination)
    +0x18 - DESC: Descriptor Pointer
    +0x1C - SWPTR: Software Pointer
    """
    csr : zdc.Reg[DmaChannelCSR] = zdc.field()
    sz : zdc.Reg[DmaChannelSZ] = zdc.field()
    a0 : zdc.Reg[DmaChannelAddr] = zdc.field()
    am0 : zdc.Reg[DmaChannelAddrMask] = zdc.field()
    a1 : zdc.Reg[DmaChannelAddr] = zdc.field()
    am1 : zdc.Reg[DmaChannelAddrMask] = zdc.field()
    desc : zdc.Reg[DmaChannelDesc] = zdc.field()
    swptr : zdc.Reg[DmaChannelSWPtr] = zdc.field()


@zdc.dataclass
class DmaChannel(Protocol):
    """Complete interface for a single DMA channel
    
    Groups together all registers and logical events for one channel.
    This provides a cohesive interface where related functionality
    (configuration, status, events) is kept together.
    
    Example usage:
        # Configure and start transfer on channel 0
        await dma.ch0.regs.csr.write(DmaChannelCSR(ch_en=1, ...))
        await dma.ch0.regs.a0.write(src_addr)
        await dma.ch0.regs.a1.write(dst_addr)
        
        # Wait for completion
        await dma.ch0.done
        
        # Check for errors
        if await dma.ch0.regs.csr.read().err:
            # Handle error
            pass
    """
    regs : DmaChannelRegs = zdc.field()
    
    # Logical events - each channel has 3 independent event sources
    error : zdc.Event = zdc.field()       # Channel error (INE_ERR, INT_ERR)
    done : zdc.Event = zdc.field()        # Transfer complete (INE_DONE, INT_DONE)
    chunk_done : zdc.Event = zdc.field()  # Chunk complete (INE_CHK_DONE, INT_CHK_DONE)


@zdc.dataclass
class DmaGlobalRegs(zdc.RegFile):
    """Global DMA control and interrupt routing registers
    
    These registers control overall DMA operation and interrupt routing:
    0x00 - CSR: Main Control/Status Register
    0x04 - INT_MSK_A: Interrupt Mask A (routes channel events to inta_o)
    0x08 - INT_MSK_B: Interrupt Mask B (routes channel events to intb_o)
    0x0C - INT_SRC_A: Interrupt Source A (shows which channels assert inta_o)
    0x10 - INT_SRC_B: Interrupt Source B (shows which channels assert intb_o)
    """
    csr : zdc.Reg[DmaMainCSR] = zdc.field()
    int_msk_a : zdc.Reg[zdc.u32] = zdc.field()
    int_msk_b : zdc.Reg[zdc.u32] = zdc.field()
    int_src_a : zdc.Reg[zdc.u32] = zdc.field()
    int_src_b : zdc.Reg[zdc.u32] = zdc.field()


@zdc.dataclass
class DmaMMIO(Protocol):
    """Protocol interface for DMA device model
    
    This defines the complete MMIO-level interface for the WISHBONE DMA/Bridge.
    
    The interface is hierarchically organized:
    - global: Global control and interrupt routing
    - ch0..ch3: Per-channel interfaces (registers + events grouped together)
    - irq_a, irq_b: Physical interrupt outputs (aggregated from channels)
    
    Design rationale:
    - Related functionality is grouped together in channel interfaces
    - Each channel is a self-contained unit with its own registers and events
    - Global registers are separated from per-channel registers
    - Physical interrupts are exposed at top level for system integration
    
    Example usage:
        # Start transfer on channel 0
        await dma.ch0.regs.a0.write(src)
        await dma.ch0.regs.a1.write(dst)
        await dma.ch0.regs.sz.write(DmaChannelSZ(tot_sz=256, chk_sz=64))
        await dma.ch0.regs.csr.write(DmaChannelCSR(ch_en=1, inc_src=1, inc_dst=1))
        
        # Wait for completion on any channel
        completed = await asyncio.wait_for_any(
            dma.ch0.done,
            dma.ch1.done,
            dma.ch2.done
        )
        
        # Handle errors
        if completed == dma.ch0.done:
            csr = await dma.ch0.regs.csr.read()
            if csr.err:
                print("Channel 0 error")
    """
    # Global control and interrupt routing
    global_regs : DmaGlobalRegs = zdc.field()
    
    # Per-channel interfaces (registers + events grouped together)
    channels : Tuple[DmaChannel, ...] = zdc.tuple(size=4)


