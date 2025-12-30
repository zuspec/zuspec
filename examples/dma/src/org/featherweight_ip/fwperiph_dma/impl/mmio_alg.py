"""MMIO-based algorithmic implementation of WISHBONE DMA/Bridge

This module provides a behavioral implementation of the DMA engine that
monitors MMIO registers, arbitrates between channels, and performs transfers
through a memory interface.

The implementation follows the WISHBONE DMA/Bridge specification:
- Priority-based arbitration with round-robin for equal priorities
- Chunked transfers with re-arbitration between chunks
- Normal and HW handshake modes
- Circular buffer and linked list descriptor support
"""

from __future__ import annotations
import zuspec.dataclasses as zdc
from typing import cast, Optional, Tuple
from ..mmio import (
    DmaMMIO, DmaChannel, DmaChannelCSR, DmaChannelSZ,
    DmaChannelAddr, DmaChannelAddrMask, DmaChannelDesc
)


@zdc.dataclass
class ChannelState(zdc.Component):
    """Per-channel state tracking for DMA engine
    
    Tracks working values during transfer execution. These are loaded
    from registers when a channel is enabled and updated during transfers.
    """
    # Working values (not visible in registers during transfer)
    src_addr : zdc.u32 = zdc.field(default=0)
    dst_addr : zdc.u32 = zdc.field(default=0)
    remaining : zdc.u32 = zdc.field(default=0)  # Words remaining
    
    # State flags
    active : bool = zdc.field(default=False)
    waiting_hw_req : bool = zdc.field(default=False)
    
    # Last arbitration info for round-robin
    last_serviced : zdc.u64 = zdc.field(default=0)


@zdc.dataclass
class DmaMMIOAlg(zdc.Component):
    """Algorithmic implementation of DMA via MMIO interface
    
    Implements the DMA engine behavior by:
    1. Monitoring channel registers for enabled channels
    2. Arbitrating between active channels based on priority
    3. Executing transfers through the memory interface
    4. Updating status registers and signaling events
    
    This provides a functional model that responds to register writes
    and implements the complete DMA specification behavior.
    """
    
    # Physical interfaces
    mmio : DmaMMIO = zdc.field()  # MMIO register interface
    memif : zdc.MemIF = zdc.port()  # Memory interface for transfers
    
    # Arbitration state
    memif_lock : zdc.Lock = zdc.inst()  # Serialize access to memory interface
    channel_states : Tuple[ChannelState, ...] = zdc.tuple(size=4, elem_factory=ChannelState)
    
    # Global state
    paused : bool = zdc.field(default=False)
    arb_counter : zdc.u64 = zdc.field(default=0)  # For round-robin fairness
    
    # The engine runs continuously, monitoring and servicing channels
    @zdc.process    
    async def _engine_task(self):
        """Main DMA engine task - runs continuously
        
        This task:
        1. Polls channel registers to detect enabled channels
        2. Arbitrates between active channels
        3. Executes chunk transfers
        4. Updates status and signals events
        """
        while True:
            # Check if DMA is paused
            main_csr = await self.mmio.global_regs.csr.read()
            if main_csr.pause:
                self.paused = True
                await self.wait(zdc.Time.ns(100))  # Poll interval
                continue
            self.paused = False
            
            # Update channel states from registers
            # TODO: Wait for an active channel with pause false
            # TODO: making this functional simplifies conversion 
            # to a single 'poll' loop
            await self._update_channel_states()
            
            # Select next channel to service
            channel_idx = await self._arbitrate()
            
            if channel_idx is not None:
                # Service the selected channel
                await self._service_channel(channel_idx)
            else:
                # No active channels, wait a bit
                await self.wait(zdc.Time.ns(10))
    
    async def _update_channel_states(self):
        """Poll channel registers and update internal state
        
        Detects newly enabled channels and loads their configuration.
        """

        # Ideally, do this in a functional way -> simplifies 
        for i in range(4):
            ch = self.mmio.channels[i]
            state = self.channel_states[i]
            
            # Read CSR to check if channel is enabled
            csr = await ch.regs.csr.read()
            
            if csr.ch_en and not state.active:
                # Channel newly enabled - load configuration
                await self._load_channel_config(i)
            elif not csr.ch_en and state.active:
                # Channel disabled
                state.active = False
    
    async def _load_channel_config(self, idx : int):
        """Load channel configuration when enabled
        
        Reads registers and initializes working state for transfer.
        """
        ch = self.mmio.channels[idx]
        state = self.channel_states[idx]
        
        # Read configuration registers
        csr = await ch.regs.csr.read()
        sz = await ch.regs.sz.read()
        a0 = await ch.regs.a0.read()
        a1 = await ch.regs.a1.read()
        
        # Check if using external descriptors
        if csr.use_ed:
            # Load from descriptor
            desc_reg = await ch.regs.desc.read()
            desc_addr = desc_reg.desc_addr << 2
            
            # Fetch descriptor from memory
            await self._load_descriptor(idx, desc_addr)
        else:
            # Use register values directly
            state.src_addr = a0.address << 2  # Convert to byte address
            state.dst_addr = a1.address << 2
            state.remaining = sz.tot_sz
            state.active = True
            state.waiting_hw_req = (csr.mode == 1)
            
            # Update CSR to show BUSY
            csr.busy = 1
            await ch.regs.csr.write(csr)
    
    async def _load_descriptor(self, idx : int, desc_addr : zdc.u32):
        """Load descriptor from memory for linked list mode
        
        Fetches descriptor structure and updates channel configuration.
        """
        ch = self.mmio.channels[idx]
        state = self.channel_states[idx]
        
        # Read descriptor from memory (4 words)
        desc_csr = await self.memif.read32(desc_addr)
        desc_a0 = await self.memif.read32(desc_addr + 4)
        desc_a1 = await self.memif.read32(desc_addr + 8)
        desc_next = await self.memif.read32(desc_addr + 12)
        
        # Parse descriptor CSR
        eol = (desc_csr >> 20) & 0x1
        inc_src = (desc_csr >> 19) & 0x1
        inc_dst = (desc_csr >> 18) & 0x1
        src_sel = (desc_csr >> 17) & 0x1
        dst_sel = (desc_csr >> 16) & 0x1
        tot_sz = desc_csr & 0xFFF
        
        # Update channel registers with descriptor values
        csr = await ch.regs.csr.read()
        csr.inc_src = inc_src
        csr.inc_dst = inc_dst
        csr.src_sel = src_sel
        csr.dst_sel = dst_sel
        await ch.regs.csr.write(csr)
        
        # Update working state
        state.src_addr = desc_a0
        state.dst_addr = desc_a1
        state.remaining = tot_sz
        state.active = True
        state.waiting_hw_req = (csr.mode == 1)
        
        # Store next descriptor pointer
        await ch.regs.desc.write(DmaChannelDesc(desc_addr=desc_next >> 2))
    
    async def _arbitrate(self) -> Optional[int]:
        """Arbitrate between active channels
        
        Implements priority-based arbitration with round-robin for
        equal priorities as described in the spec.
        
        Returns:
            Channel index to service, or None if no active channels
        """
        best_channel = None
        best_priority = -1
        best_service_time = self.arb_counter
        
        for i in range(4):
            state = self.channel_states[i]
            if not state.active:
                continue
            
            ch = self.mmio.channels[i]
            csr = await ch.regs.csr.read()
            
            # Skip if waiting for hardware request
            if state.waiting_hw_req:
                # TODO: Check DMA_REQ signal when HW handshake implemented
                continue
            
            priority = csr.priority
            
            # Select based on priority, then round-robin
            if priority > best_priority:
                best_channel = i
                best_priority = priority
                best_service_time = state.last_serviced
            elif priority == best_priority:
                # Same priority - use round-robin (oldest serviced wins)
                if state.last_serviced < best_service_time:
                    best_channel = i
                    best_service_time = state.last_serviced
        
        return best_channel
    
    async def _service_channel(self, idx : int):
        """Service a channel by performing a chunk of transfers
        
        Args:
            idx: Channel index to service
        """
        ch = self.mmio.channels[idx]
        state = self.channel_states[idx]
        
        # Read configuration
        csr = await ch.regs.csr.read()
        sz = await ch.regs.sz.read()
        am0 = await ch.regs.am0.read()
        am1 = await ch.regs.am1.read()
        
        # Determine chunk size
        chk_sz = sz.chk_sz if sz.chk_sz > 0 else state.remaining
        words_to_xfer = min(chk_sz, state.remaining)
        
        # Lock memory interface for chunk duration
        async with self.memif_lock:
            # Perform chunk transfer
            for _ in range(words_to_xfer):
                # Check software pointer if enabled
                if not await self._check_software_pointer(idx):
                    # Stalled by software pointer
                    return
                
                # Read from source
                data = await self.memif.read32(state.src_addr)
                
                # Write to destination
                await self.memif.write32(state.dst_addr, data)
                
                # Update addresses with masking for circular buffers
                if csr.inc_src:
                    state.src_addr = self._increment_masked_addr(
                        state.src_addr, am0.mask
                    )
                
                if csr.inc_dst:
                    state.dst_addr = self._increment_masked_addr(
                        state.dst_addr, am1.mask
                    )
                
                state.remaining -= 1
        
        # Update arbitration state
        self.arb_counter += 1
        state.last_serviced = self.arb_counter
        
        # Signal chunk done if enabled
        if csr.ine_chk_done and sz.chk_sz > 0:
            csr.int_chk_done = 1
            await ch.regs.csr.write(csr)
            await self._signal_event(ch.chunk_done)
        
        # Check if transfer complete
        if state.remaining == 0:
            await self._complete_channel(idx)
    
    def _increment_masked_addr(self, addr : zdc.u32, mask : zdc.u32) -> zdc.u32:
        """Increment address with masking for circular buffers
        
        Args:
            addr: Current byte address
            mask: Address mask (in word addressing)
            
        Returns:
            Next address with wrap-around applied
        """
        # Convert to word address
        word_addr = addr >> 2
        
        # Increment and apply mask
        word_addr = (word_addr + 1) & ((mask << 2) | 0x3)
        
        # Convert back to byte address
        return word_addr << 2
    
    async def _check_software_pointer(self, idx : int) -> bool:
        """Check if software pointer allows transfer
        
        Returns True if transfer can proceed, False if stalled.
        """
        ch = self.mmio.channels[idx]
        state = self.channel_states[idx]
        
        swptr_reg = await ch.regs.swptr.read()
        if not swptr_reg.swptr_en:
            return True
        
        # Check if DMA address matches software pointer
        swptr_byte_addr = swptr_reg.swptr << 2
        
        # Compare the address that will be accessed on interface 0
        csr = await ch.regs.csr.read()
        check_addr = state.src_addr if csr.src_sel == 0 else state.dst_addr
        
        if check_addr == swptr_byte_addr:
            # Stalled - cannot proceed
            return False
        
        return True
    
    async def _complete_channel(self, idx : int):
        """Complete channel transfer
        
        Updates status, signals events, and handles restart/descriptors.
        """
        ch = self.mmio.channels[idx]
        state = self.channel_states[idx]
        csr = await ch.regs.csr.read()
        
        # Check for auto-restart
        if csr.ars and not csr.use_ed:
            # Reload from registers and restart
            await self._load_channel_config(idx)
            return
        
        # Check for next descriptor in linked list
        if csr.use_ed:
            desc_reg = await ch.regs.desc.read()
            next_desc_addr = desc_reg.desc_addr << 2
            
            if next_desc_addr != 0:
                # Load next descriptor
                await self._load_descriptor(idx, next_desc_addr)
                return
            # else: EOL reached, complete normally
        
        # Mark channel done
        state.active = False
        csr.busy = 0
        csr.done = 1
        csr.ch_en = 0  # Disable channel
        
        # Signal done interrupt if enabled
        if csr.ine_done:
            csr.int_done = 1
        
        await ch.regs.csr.write(csr)
        
        # Signal done event
        await self._signal_event(ch.done)
    
    async def _signal_event(self, event : zdc.Event):
        """Signal an event
        
        This would trigger the event and potentially assert interrupt outputs.
        For now, just trigger the event.
        """
        # In a full implementation, this would also:
        # 1. Update INT_SRC_A/B registers based on INT_MSK_A/B
        # 2. Assert inta_o/intb_o outputs
        # For algorithmic model, just signal the event
        event.signal()
