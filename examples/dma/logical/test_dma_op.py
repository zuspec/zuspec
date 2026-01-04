import asyncio
import pytest
import zuspec.dataclasses as zdc
from zuspec.dataclasses import profiles
from zuspec.dataclasses.rt.lock_rt import LockRT
from ..op import DmaImpl


def _wr32(mem: bytearray, addr: int, val: int):
    mem[addr:addr+4] = int(val).to_bytes(4, "little")


def _rd32(mem: bytearray, addr: int) -> int:
    return int.from_bytes(mem[addr:addr+4], "little")


@zdc.dataclass(profile=profiles.PythonProfile)
class MemModel(zdc.Component):
    """Memory model with DRAM-like latency characteristics.
    
    Latency model:
    - Sequential access (same row): fast (10ns)
    - Row change (different row, same bank): slower (50ns row precharge + activate)
    - Bank change: moderate (30ns)
    
    DRAM organization:
    - Row size: 8KB (2048 x 32-bit words)
    - 4 banks
    - Addresses: [bank:2][row:11][col:11][byte:2]
    """
    __test__ = False

    mem : zdc.MemIF = zdc.export()
    data : bytearray = zdc.field(default_factory=lambda: bytearray(0x10000))
    
    # DRAM state tracking
    _last_bank : int = zdc.field(default=-1)
    _last_row : int = zdc.field(default=-1)
    _last_addr : int = zdc.field(default=-1)
    
    # Timing parameters (ns)
    _sequential_latency : int = zdc.field(default=10)
    _bank_switch_latency : int = zdc.field(default=30)
    _row_switch_latency : int = zdc.field(default=50)

    def __bind__(self):
        return {
            self.mem.read8: self._read8,
            self.mem.read16: self._read16,
            self.mem.read32: self._read32,
            self.mem.read64: self._read64,
            self.mem.write8: self._write8,
            self.mem.write16: self._write16,
            self.mem.write32: self._write32,
            self.mem.write64: self._write64,
        }

    def _chk(self, addr: zdc.u64, nbytes: zdc.u64):
        if addr < 0 or (addr + nbytes) > len(self.data):
            raise IndexError(f"Address 0x{addr:x} out of range")

    def _get_bank(self, addr: int) -> int:
        """Extract bank from address (bits [13:12])."""
        return (addr >> 12) & 0x3

    def _get_row(self, addr: int) -> int:
        """Extract row from address (bits [24:14])."""
        return (addr >> 14) & 0x7FF

    async def _apply_latency(self, addr: int):
        """Apply DRAM-like access latency based on address pattern."""
        bank = self._get_bank(addr)
        row = self._get_row(addr)
        
        # Determine latency based on access pattern
        if self._last_bank == bank and self._last_row == row:
            # Sequential access within same row - fastest
            latency = self._sequential_latency
        elif self._last_bank == bank:
            # Same bank, different row - row switch penalty
            latency = self._row_switch_latency
        elif self._last_bank != -1:
            # Different bank - bank switch penalty
            latency = self._bank_switch_latency
        else:
            # First access - use sequential latency
            latency = self._sequential_latency
        
        # Update state
        self._last_bank = bank
        self._last_row = row
        self._last_addr = addr
        
        # Apply the delay
        await self.wait(zdc.Time.ns(latency))

    async def _read8(self, addr: zdc.u64) -> zdc.u8:
        self._chk(addr, 1)
        await self._apply_latency(addr)
        return self.data[addr]

    async def _read16(self, addr: zdc.u64) -> zdc.u16:
        self._chk(addr, 2)
        await self._apply_latency(addr)
        return int.from_bytes(self.data[addr:addr+2], "little")

    async def _read32(self, addr: zdc.u64) -> zdc.u32:
        self._chk(addr, 4)
        await self._apply_latency(addr)
        return int.from_bytes(self.data[addr:addr+4], "little")

    async def _read64(self, addr: zdc.u64) -> zdc.u64:
        self._chk(addr, 8)
        await self._apply_latency(addr)
        return int.from_bytes(self.data[addr:addr+8], "little")

    async def _write8(self, addr: zdc.u64, data: zdc.u8):
        self._chk(addr, 1)
        await self._apply_latency(addr)
        self.data[addr] = int(data) & 0xFF

    async def _write16(self, addr: zdc.u64, data: zdc.u16):
        self._chk(addr, 2)
        await self._apply_latency(addr)
        self.data[addr:addr+2] = int(data).to_bytes(2, "little")

    async def _write32(self, addr: zdc.u64, data: zdc.u32):
        self._chk(addr, 4)
        await self._apply_latency(addr)
        self.data[addr:addr+4] = int(data).to_bytes(4, "little")

    async def _write64(self, addr: zdc.u64, data: zdc.u64):
        self._chk(addr, 8)
        await self._apply_latency(addr)
        self.data[addr:addr+8] = int(data).to_bytes(8, "little")


@zdc.dataclass
class TestDMAOp(zdc.Component):
    __test__ = False

    dma : DmaImpl = zdc.inst()
    mem : MemModel = zdc.inst()

    def __bind__(self):
        return {
            self.dma.memif: self.mem.mem
        }


def test_dma_single_xfer():
    tb = TestDMAOp()
    assert isinstance(tb.dma.memif_lock, LockRT)

    src = 0x1000
    dst = 0x2000

    for i in range(16):
        _wr32(tb.mem.data, src + 4*i, 0xAABBCC00 + i)

    async def run():
        start_time = tb.time()
        await tb.dma.channels[0].m2m(src, dst, 16, 4)
        end_time = tb.time()
        
        # Verify timing: 16 transfers * 2 accesses (read+write) * latency
        # Sequential accesses within row = 10ns per access
        elapsed_ns = end_time.as_ns() - start_time.as_ns()
        print(f"Transfer time: {elapsed_ns}ns")
        
        # Should be roughly 16*2*10 = 320ns (all sequential within row)
        assert elapsed_ns >= 300  # Account for some overhead

    asyncio.run(run())

    for i in range(16):
        assert _rd32(tb.mem.data, dst + 4*i) == (0xAABBCC00 + i)

    tb.shutdown()


def test_dma_partial_last_chunk():
    tb = TestDMAOp()

    src = 0x1000
    dst = 0x3000

    for i in range(10):
        _wr32(tb.mem.data, src + 4*i, 0x11223300 + i)

    async def run():
        await tb.dma.channels[0].m2m(src, dst, 10, 4)

    asyncio.run(run())

    for i in range(10):
        assert _rd32(tb.mem.data, dst + 4*i) == (0x11223300 + i)

    tb.shutdown()


def test_dma_indexed_channel_access():
    tb = TestDMAOp()

    src = 0x1000
    dst = 0x4000

    for i in range(8):
        _wr32(tb.mem.data, src + 4*i, 0x55667700 + i)

    async def run():
        # Verify tuple wrapper supports indexing
        await tb.dma.channels[3].m2m(src, dst, 8, 8)

    asyncio.run(run())

    for i in range(8):
        assert _rd32(tb.mem.data, dst + 4*i) == (0x55667700 + i)

    tb.shutdown()


def test_dma_concurrent_channels():
    tb = TestDMAOp()

    src0 = 0x1000
    dst0 = 0x5000
    src1 = 0x2000
    dst1 = 0x6000

    for i in range(16):
        _wr32(tb.mem.data, src0 + 4*i, 0xAA000000 + i)
        _wr32(tb.mem.data, src1 + 4*i, 0xBB000000 + i)

    async def run():
        start_time = tb.time()
        await asyncio.gather(
            tb.dma.channels[0].m2m(src0, dst0, 16, 4),
            tb.dma.channels[1].m2m(src1, dst1, 16, 4),
        )
        end_time = tb.time()
        
        elapsed_ns = end_time.as_ns() - start_time.as_ns()
        print(f"Concurrent transfer time: {elapsed_ns}ns")
        
        # Two channels arbitrating for same memory via lock
        # Transfers serialize, so timing is ~2x single channel
        # But with interleaving, may see bank/row switches
        assert elapsed_ns >= 600

    asyncio.run(run())

    for i in range(16):
        assert _rd32(tb.mem.data, dst0 + 4*i) == (0xAA000000 + i)
        assert _rd32(tb.mem.data, dst1 + 4*i) == (0xBB000000 + i)

    tb.shutdown()


def test_dma_bank_switching():
    """Test that crossing bank boundaries incurs additional latency."""
    tb = TestDMAOp()

    # Place src and dst in different banks
    # Bank 0: addresses 0x0000-0x0FFF (bits [13:12] = 00)
    # Bank 1: addresses 0x1000-0x1FFF (bits [13:12] = 01)
    src = 0x0000  # Bank 0
    dst = 0x1000  # Bank 1

    for i in range(8):
        _wr32(tb.mem.data, src + 4*i, 0x12340000 + i)

    async def run():
        start_time = tb.time()
        await tb.dma.channels[0].m2m(src, dst, 8, 8)
        end_time = tb.time()
        
        elapsed_ns = end_time.as_ns() - start_time.as_ns()
        print(f"Bank-switching transfer time: {elapsed_ns}ns")
        
        # Each iteration: read (bank 0) then write (bank 1) = bank switch
        # 8 iterations * 2 accesses, first access in each bank costs 30ns
        # Subsequent sequential accesses in same bank cost 10ns
        # Pattern: read_bank0(30) write_bank1(30) read_bank0(30) write_bank1(30)...
        # = 8*30 + 8*30 = 480ns for bank switches
        assert elapsed_ns >= 450

    asyncio.run(run())

    for i in range(8):
        assert _rd32(tb.mem.data, dst + 4*i) == (0x12340000 + i)

    tb.shutdown()


def test_dma_row_switching():
    """Test that crossing row boundaries incurs row precharge/activate penalty."""
    tb = TestDMAOp()

    # Rows are 8KB = 2048 words (bits [24:14])
    # Row 0: addresses 0x00000-0x01FFF
    # Row 1: addresses 0x04000-0x05FFF (skip to ensure row change)
    src = 0x00000  # Row 0
    dst = 0x04000  # Row 1

    for i in range(8):
        _wr32(tb.mem.data, src + 4*i, 0xABCD0000 + i)

    async def run():
        start_time = tb.time()
        await tb.dma.channels[0].m2m(src, dst, 8, 8)
        end_time = tb.time()
        
        elapsed_ns = end_time.as_ns() - start_time.as_ns()
        print(f"Row-switching transfer time: {elapsed_ns}ns")
        
        # Each iteration: read (row 0) then write (row 1) = row switch within same bank
        # Row switches cost 50ns
        # 8 iterations * 2 accesses, each switching rows
        assert elapsed_ns >= 700  # 8*2*50 = 800ns, allow some margin

    asyncio.run(run())

    for i in range(8):
        assert _rd32(tb.mem.data, dst + 4*i) == (0xABCD0000 + i)

    tb.shutdown()

def test_dma_chunk_size_impact():
    """Demonstrate how chunk size affects memory contention patterns."""
    tb = TestDMAOp()

    src = 0x1000
    dst = 0x2000
    total = 32

    for i in range(total):
        _wr32(tb.mem.data, src + 4*i, 0xDEADBE00 + i)

    async def run_with_chunk(chunk_size):
        # Reset memory state between runs
        tb.mem._last_bank = -1
        tb.mem._last_row = -1
        
        start_time = tb.time()
        await tb.dma.channels[0].m2m(src, dst, total, chunk_size)
        end_time = tb.time()
        
        elapsed_ns = end_time.as_ns() - start_time.as_ns()
        return elapsed_ns

    async def run():
        # Small chunks: more lock overhead but better memory utilization
        time_chunk_4 = await run_with_chunk(4)
        print(f"Chunk size 4:  {time_chunk_4}ns")
        
        # Medium chunks: balanced
        time_chunk_8 = await run_with_chunk(8)
        print(f"Chunk size 8:  {time_chunk_8}ns")
        
        # Large chunks: less lock overhead, all sequential
        time_chunk_32 = await run_with_chunk(32)
        print(f"Chunk size 32: {time_chunk_32}ns")
        
        # All should complete, larger chunks generally faster for sequential access
        assert time_chunk_32 <= time_chunk_4

    asyncio.run(run())

    for i in range(total):
        assert _rd32(tb.mem.data, dst + 4*i) == (0xDEADBE00 + i)

    tb.shutdown()

