import zuspec.dataclasses as zdc
from typing import Protocol, Tuple

class Object():
    pass

@zdc.dataclass
class MyS(zdc.Struct):
    pass

@zdc.dataclass
class ChannelRegs(zdc.RegFile):
    pass

@zdc.dataclass
class DmaChannel(Protocol):
    ev : zdc.Event = zdc.field()
    regs : ChannelRegs = zdc.field()
    a : str = zdc.field()
    b : zdc.uint32_t = zdc.field()
    c : zdc.u32 = zdc.field()

    def abc(self):
        # Error: use of named access
        if getattr(self, "abc") == 2:
            pass

    # Error: Object is not Zuspec-derived
    def ghi(self, a : MyS):
        # This is an error because Object is not
        # a known Zuspec type
        b = Object()
        c = 20
        x = MyS()


@zdc.dataclass
class Dma(Protocol):
    channels : Tuple[DmaChannel] = zdc.field()
