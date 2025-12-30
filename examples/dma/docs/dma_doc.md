WISHBONE
DMA/Bridge
IP Core

Author: Rudolf Usselmann
rudi@asics.ws
www.asics.ws

Rev. 1.5
January 27, 2002

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Revision History

Rev.

Date

Author

Description

0.1

23/1/01

Rudolf
Usselmann

First Draft
Internal release

0.2

0.3

28/1/01

13/3/01

RU

RU

0.4

16/3/01

RU

1.0

00/3/01

RU

1.01

8/4/01

RU

1.2

6/6/01

RU

First public release

- Removed buffers and all references to buffered transfers
- Updated WISHBONE interface signals
- Updated Pass-Through mode section
- Added Linked List Buffers
- Updated registers
- Added Bandwidth Allocation Section

- Added DMA Request and Acknowledge Section
- Added Forcing Next Descriptor Section
- Added NDn_I signals
- Moved the USE_ED bit from COR to Channel CSR register
- Added SZ_WB bit to channel CSR register

- Added Appendix B: Core File Structure
- Modiﬁed Introduction
- Removed “Preliminary Draft” notice

- Corrected syntax and grammar
- Fixed some descriptions
- Clariﬁed the linked lists

- Changed Register Order, major reorganization.
- Added Circular Buffer Support (Address Mask Registers).
- Added FIFO support in memory (Software pointer Register).
- Modiﬁed to support up to 31 channels.
- Modiﬁed to support 2,4 and 8 priority levels.
- Filled in Appendix A, Core HW Conﬁguration.
- Added Circular Buffers Section.
- Added FIFO Buffers Section.

1.3

15/8/01

RU

- Changed IO names to be more clear.
- Uniquifyed deﬁne names to be core speciﬁc.
- Added Section 3.10, describing DMA restart.

1.4

1.5

19/10/01

25/01/02

RU

RU

- Modiﬁed the core to be parameterized - Changed Appendix A.

- Minor Document Cleanup and Clariﬁcations.

www.opencores.org

Rev. 1.5

1 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

(This page intentionally left blank)

2 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

1

Introduction

This core provides DMA transfers between two WISHBONE interfaces. Trans-
fers can also be performed on the same WISHBONE interface. It can also act as a
bridge, allowing masters on each WISHBONE interface to directly access slaves
on the other interface.

This implementation is designed to work with two WISHBONE interfaces run-

ning at the same clock.

The WISBONE speciﬁcation and additional information about WISHBONE

SoC can be found at:

http://www.opencores.org/wishbone/

The Main features of the DMA/Bridge are:

• Up to 31 DMA Channels
2, 4 or 8 priority levels
•
• Linked List Descriptors Support
• Circular Buffer Support
FIFO buffer support
•
• Hardware handshake support

www.opencores.org

Rev. 1.5

3 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

4 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

2

Architecture

Below ﬁgure illustrates the overall architecture of the core.

Figure 1: Core Architecture Overview

HW
Handshake

Interrupt

WISHBONE IF 0

DMA
Engine

Pass-
through

WISHBONE IF 1

It consists of 3 main building blocks: Two WISHBONE interfaces, a DMA

engine and pass through logic.

2.1. WISHBONE Interface

The DMA/Bridge core has two master and slave capable WISHBONE inter-
faces. Both interfaces are WISHBONE SoC bus speciﬁcation Rev. B compliant.

www.opencores.org

Rev. 1.5

5 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

This implementation implements a 32 bit bus width and does not support other bus
widths.

WISHBONE
COMPATIBLE

2.2. DMA Engine

The DMA engine is a up to 31 channel DMA engine that supports transfers
between the two interfaces as well as transfers on the same interface (block copy).
Each channel can be programmed to have a different priority. Channels with the
same priority are serviced in a round robin fashion.

2.3. Pass Through

This block performs the bridging operation between the two WISHBONE
interfaces. It includes a two entry deep write buffer in each direction. The write
buffer can be disabled if desired.

6 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

3

Operation

The WISHBONE DMA/Bridge consists of up to 31 DMA channels, the actual

DMA engine, and a channel prioritizing arbiter (see “Figure 2: DMA Engine”).

Figure 2: DMA Engine

Channel
Priorities

Prioritizing
Arbiter

Channel 0

Channel 1

...

Channel n-1

Channel n

M
U
X

DMA
Engine

WISHBONE
Interface 0

WISHBONE
Interface 1

3.1. Prioritizing Arbiter

The prioritizing arbiter will select the next channel to process, based ﬁrst on

priority, and secondarily, if all priorities are equal, in a round robin way. Each
1
 bit priority value associated with it. A value of 0 identiﬁes a chan-
channel has a 3
nel with very low priority, a value of 7 identiﬁes a channel with very high priority.

1. Implementation Dependent. This core supports 2, 4 and 8 priority levels. Please see Appendix A “Core

HW Conﬁguration” on page 31 for more information.

www.opencores.org

Rev. 1.5

7 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Channels with the same priority are processed in a round robin way, as long as
there are no channels with a higher priority.

“Figure 3: Channel Arbiter” on page 8 illustrates the internal operation of the

channel arbiter.

Figure 3: Channel Arbiter

Channel priorities

Ch. 0

Ch. 1

Priority 0

Ch. n

Ch. n-1

Ch. 0

Ch. 1

Priority 1

Ch. n

Ch. n-1

Priority
Encoder

Ch. 0

Ch. 1

Priority n-1

Ch. n

Ch. n-1

Ch. 0

Ch. 1

Ch. n

Ch. n-1

Priority n

M
U
X

Next
Channel

8 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Care should be taken when using priorities, as channels with lower priorities
may be locked out and never serviced, if channels with higher priority are being
continuously serviced.

3.2. DMA Engine

The DMA engine can be programmed to perform various transfer operations.

This section will illustrate several transfer options and their operation.

3.2.1.

Normal (Software) DMA Operation

This is a simple DMA operation performing a block copy. “Figure 4: Normal

DMA Operation” illustrates the operation.

Figure 4: Normal DMA Operation

Bus not relinquished until transfer (or one chunk transfer) is completed.
Main bus arbiter (external) is responsible for limiting bus time.

Transfers are
performed on
the same interface

Different Interfaces

Interface A

Read 0 Write 0

Read N Write N

Read 0 Read 1

Read N-1 Read N

Interface B

Write 0

Write 1

Write N-1

Write N

Start

Done
(INT)

 signal asserted until it has completed the transfer. The

In this example the DMA engine performs a block copy from one location to
another, either on the same interface or on a different interface. The DMA engine
1
will leave the CYC_O
transfer begins when either the local controller/CPU writes to the channel CSR
register. When the transfer is completed, the DMA engine will assert an interrupt
(if enabled) or go to the idle state. If the auto restart bit (ARS) is set, it immediately
restarts the operation. When the ARS bit is set, the DMA engine will continue
restarting until the ARS bit is cleared in the channel CSR register. The software
can also force the channel to stop by writing a one to the STOP bit in the channel

1. CYC_O is a WISHBONE interface signal. See Section 5 “Core IOs” on page 29 for more information.

www.opencores.org

Rev. 1.5

9 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

CSR register. In this case the DMA channel will immediately stop and indicate an
error condition by setting the ERR bit in the channel CSR register and asserting an
error interrupt (if enabled).

If CHK_SZ is not zero, the channel has to re-arbitrate for the interfaces after
each CHK_SZ of words has been transferred. This is particularly useful when set-
ting up all channels with the same priority and requiring “fair” bus usage distribu-
tion and low latency.

3.2.2. HW Handshake Mode

Below ﬁgure illustrates HW handshake DMA operations, where one full DMA

transfer requires more than one external trigger.

Figure 5: HW Handshake DMA Operation

Bus not relinquished until a chunk completes.
Main bus arbiter is responsible for limiting bus time.

First Chunk

Last Chunk

R 0

W N

R 0

W N

Transfers are
performed on
the same interface

Different Interfaces

Interface A

R 0

R N

R 0

R N

Interface B

W 0

W N

W 0

W N

DMA_REQ_I

DMA_ACK_O

INT_O

In this mode the DMA engine will wait for the external trigger (DMA_REQ_I)
to be asserted before starting the DMA transfer. Each time the trigger is asserted it
will transfer CHK_SZ number of words (one chunk). After each chunk transfer it
will assert DMA_ACK_O to acknowledge the transfer. After TOT_SZ number of
words have been transferred, an interrupt is asserted (if enabled).

After each chunk transfer the DMA channel has to re-arbitrate internally for

the usage of the WISHBONE interfaces.

If the ARS bit is set, the DMA channel will reload the values programmed into

the channel registers and restart the operation. This loop will continue until the

10 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

ARS bit is cleared or the STOP bit is set. When the STOP bit is set, the DMA
engine will immediately stop the transfer, set the ERR bit, and assert an error inter-
rupt (if enabled).

3.3. Linked List Descriptors

In this mode the DMA engine will fetch the channel descriptors from memory
attached to interface 0. The descriptors are similar to the channel registers, except
that after completion a new descriptor may be loaded. The descriptors are provided
in a linked list format.

Figure 6: Linked List Descriptor’

DESCn

DESC_CSR

DESC_ADR0

DESC_ADR1

DESC_NEXT

DESC_CSR

DESC_ADR0

DESC_ADR1

DESC_NEXT

DESC_CSR:

DESC_ADR0:

DESC_ADR1:

DESC_NEXT:

Conf. Bits

Total Transfer Size

Source Address (address 0)

Destination Address (address 1)

Next pointer

31

20

16

11

0

Reserved

Table 1: Deﬁnition of bits in the DESC_CSR word

Bit #

Description

20

19

18

17

16

EOL: If set, indicates that this is the last descriptor in the list

Increment Source Address (same as INC_SRC in CSR)

Increment Destination Address (same as INC_DSR in CSR)

 Source Select (same as SRC_SEL in SCR)

Destination Select (same as DST_SEL in CSR)

11-0

Total Transfer Size (same as TOT_SZ in SZ register)

To use external descriptors, the Linked List Descriptor Pointer register for the

appropriate channel must be programmed with the address of a valid descriptor.
The chunk size must also be set to the desired value in the channel SZ register.
Then the USE_ED bit in the channel CSR register must be set to enable external
descriptors. After that, the channel enable bit (CH_EN) must be set in the CSR of

www.opencores.org

Rev. 1.5

11 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

the channel. Now the DMA engine will start processing descriptors from memory.
Normal (Software) and hardware handshake modes are supported with external
descriptors. The ARS bit in the channel CSR register has no meaning when using
external descriptors and is ignored.

When the DMA engine ﬁnishes processing a descriptor, it will attempt to load
the next descriptor, pointed to by the DESC_NEXT entry in the descriptor. If the
EOL bit in the current DESC_CSR entry is set, the DMA engine will stop, set the
DONE bit in the channel CSR register, and assert an interrupt, if enabled.

Note:
Bits 19-16 in the DESC_CSR register are copied to the channel CSR regis-
ter bits 4-1.
Bits 11-0 in the DESC_CSR are copied to the channel SZ register bits 11-0.
DESC_ADR0 is copied to channels address 0 register.
DESC_ADR1 is copied to channels address 1 register.
DESC_NEXT is copied to the channels DESC register.

3.4. Circular Buffers

Circular buffers are buffers that will never go beyond the allocated memory
space. These buffers will “wrap-around” and start at the beginning f the buffer
when they have reached the last entry in the buffer. They are implemented by pro-
viding a Mask register for both the source and destination address. This mask is
applied to the address when it is incremented. Only bits that are set to ‘1’ in the
mask will be incremented.

The lower four bits of the Address Mask are ignored, making the circular

buffer at least 4 entries (16 bytes) deep.

Figure 7:  Circular Buffers Implementation

‘1’

+

r
e

i

t
s
g
e
R
s
s
e
r
d
d
A

Address Mask

4

31

4

31

4

31

Next Address

4

31

X
U
M

.
.
.

X
U
M

12 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

3.5. FIFO Buffer Implementation

The DMA engine supports implementing FIFO style buffers in main memory.
This is accomplished using circular buffers and using a Software Pointer Register
to determine the last location software has read or written.

The Software Pointer Register is compared to the current DMA Address, and if

they are equal, the DMA will stop processing the channel until the Software
pointer is updated. The software is responsible for properly updating the Software
Pointer Register.

Software Pointer is always compared to the DMA address that will be placed

on the WISHBONE Interface 0.

3.6. Pass Through Operation

In pass through mode, this core acts as a bridge. It does not add any functional-

ity to pass-through trafﬁc. The pass-through logic is combinatorial only (e.g. in
pass-through mode signals are not latched). Below ﬁgure illustrates the pass-
though logic.

Figure 8: Pass Through Logic

DMA Engine

Interface 0

Interface 1

Master
Interface

Slave
Interface

Register
File

Master
Interface

Slave
Interface

3.7. Bandwidth Allocation

 The CHK_SZ ﬁeld can also be used to distribute bandwidth between channels.

This is done by setting up all channels with equal priority values. Then the band-
width for each channel can be calculated as follows:

// Calculate the total bandwidth available (100%)
TOT_BW = CH0_CHK_SZ + CH1_CHK_SZ + CH2_CHK_SZ + CH3_CHK_SZ

www.opencores.org

Rev. 1.5

13 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

CH0_BW = CH0_CHK_SZ/TOT_BW*100 // Channel 0 bandwidth (percent)
CH1_BW = CH1_CHK_SZ/TOT_BW*100 // Channel 1 bandwidth (percent)
CH2_BW = CH2_CHK_SZ/TOT_BW*100 // Channel 2 bandwidth (percent)
CH3_BW = CH3_CHK_SZ/TOT_BW*100 // Channel 3 bandwidth (percent)

Example:
CH0_CHK_SZ = 8
CH1_CHK_SZ = 4
CH2_CHK_SZ = 4
CH3_CHK_SZ = 1
TOT_BW = 8+4+4+1 = 17 (100%)
CH0_BW = 8/17*100 = 47%
CH1_BW = 4/17*100 = 23.5%
CH2_BW = 4/17*100 = 23.5%
CH3_BW = 1/17*100 = 5.8%

3.8. DMA Request and Acknowledge (HW Handshake)

In Hardware Handshake mode external request and acknowledge signals are
used to start a transfer of a chunk and indicate when the transfer has completed. If
CHK_SZ is zero, TOT_SZ number of words will be transferred.

Figure 9: DMA_REQ/DMA_ACK Timing

CLK

CYC_O

ACK_I

DMA_REQ_I

DMA_ACK_O

0 or more cycles to complete the transfer

The DMA_ACK_O signal will be asserted one cycle after a chunk has been
transferred. The chunk size may also be set to one, in which case only one WISH-
BONE
DMA_ACK_O is asserted, another transfer will be initiated, after the channel has
re-arbitrated for.

 transfer will occur. If DMA_REQ_I is not de-asserted after

1

1. For simplicity reasons only a partial WISHBONE signal list is shown.

14 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Figure 10: Back to Back DMA Transfers

CLK

CYC_O

ACK_I

DMA_REQ_I

DMA_ACK_O

3.9. Forcing Next Descriptor

The DMA core provides a special feature that allows a device to force the
DMA engine to advance to the next descriptor in a Linked List. This feature is par-
ticularly useful to devices that wish to keep a dedicated descriptor for a certain
piece of data (e.g one packet payload) but do not know the exact size of the data.
This feature only works with external descriptors in linked lists and hardware

handshake mode.

There are two ways to force the next descriptor:
The ﬁrst way is to assert the DMA_ND_I signal at least two cycles before the
DMA_REQ_I signal. In this case the descriptor for the channel will be invalidated
and marked as “serviced” and when the DMA_REQ_I is asserted the next descrip-
tor will be fetched from the address pointed to by the current descriptor. If the cur-
rent descriptor’s EOL bit is set, the DMA channel will stop and clear the enable bit
in the channel’s CSR. To start DMA operation on this channel again, software has
to reset the DESCn register and the channel CSR register.

The second way is to assert DMA_ND_I together with DMA_REQ_I. It must

stay asserted until DMA_ACK_O is asserted by the DMA, at which point
DMA_ND_I must be de-asserted. In this case, the DMA will ﬁrst ﬁnish transfer-
ring the current chunk size and than invalidate the current descriptor by marking it
“serviced”. If the SZ_WB bit is set in the channel CSR register, the DMA will
write the total number of remaining bytes to be transferred back to the DESC_CSR
in memory. This will allow the software to easily track the actual number of bytes
transferred.

3.10. Restarting DMA Transfers

In some cases it is desired to restart a DMA transfer. An example is a Ethernet
MAC, that needs to restart a transfer due to a collision or other errors. This can be
accomplished by asserting the DMA_REST_I for any given channel. This will

www.opencores.org

Rev. 1.5

15 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

reload the channels working registers with the original values that have been pro-
grammed either by software or from a previous descriptor fetch. This feature will
only work if the channel has been deﬁned to support ARS, see Appendix A “Core
HW Conﬁguration” on page 31 for more details.

The DMA_REST_I must only be asserted when there is no transfer in

progress.

16 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

4

Core Registers

This section describes all control and status register inside the WISHBONE

Address

 speciﬁes the number of bits in the register, and

DMA/Bridge core. The
Width
access types to that register. RW stands for read and write access, RO for read only
access. A ‘C’ appended to RW or RO indicates that some or all of the bits are
cleared after a read.

 ﬁeld indicates a relative address in hexadecimal.
Access

 speciﬁes the valid

All RESERVED bits should always be written with zero. Reading RESERVED
bits will return undeﬁned values. Software should follow this model to be compat-
ible to future releases of this core.

Name

CSR

INT_MSK_A

INT_MSK_B

INT_SRC_A

0

4

8

c

INT_SRC_B

10

CH0_CSR

CH0_SZ

CH0_A0

CH0_AM0

CH0_A1

CH0_AM1

CH0_DESC

CH0_SWPTR

20

24

28

2c

30

34

38

3c

Table 2: Control/Status Registers

.
r
d
d
A

h
t
d
i
W

s
s
e
c
c
A

Description

32 RW Main Conﬁguration & Status Register

32 RW Interrupt Mask for INTA_O output

32 RW Interrupt Mask for INTB_O output

32

32

RO Interrupt Source for INTA_O output

RO Interrupt Source for INTB_O output

Channel 0 Registers

32 RW Control Status Register

32 RW Transfer Size

32 RW Address 0

32 RW Address Mask 0

32 RW Address 1

32 RW Address Mask1

32 RW Linked List Descriptor Pointer

32 RW Software Pointer

Channel 1 Registers

www.opencores.org

Rev. 1.5

17 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Name

CH1_CSR

CH1_SZ

CH1_A0

CH1_AM0

CH1_A1

CH1_AM1

CH1_DESC

CH1_SWPTR

CH2_CSR

CH2_SZ

CH2_A0

CH2_AM0

CH2_A1

CH2_AM1

CH2_DESC

.
r
d
d
A

40

44

48

4c

50

54

58

5c

60

64

68

6c

70

74

78

Table 2: Control/Status Registers

h
t
d
i
W

s
s
e
c
c
A

Description

32 RW Control Status Register

32 RW Transfer Size

32 RW Address 0

32 RW Address Mask 0

32 RW Address 1

32 RW Address Mask1

32 RW Linked List Descriptor Pointer

32 RW Software Pointer

Channel 2 Registers

32 RW Control Status Register

32 RW Transfer Size

32 RW Address 0

32 RW Address Mask 0

32 RW Address 1

32 RW Address Mask1

32 RW Linked List Descriptor Pointer

CH2_SWPTR

7c

32 RW Software Pointer

CH3_CSR

CH3_SZ

CH3_A0

CH3_AM0

CH3_A1

CH3_AM1

CH3_DESC

CH3_SWPTR

Starting Addr.

Starting Addr.

Starting Addr.

80

84

88

8c

90

94

98

9c

a0

c0

e0

Starting Addr.

100

Channel 3 Registers

32 RW Control Status Register

32 RW Transfer Size

32 RW Address 0

32 RW Address Mask 0

32 RW Address 1

32 RW Address Mask1

32 RW Linked List Descriptor Pointer

32 RW Software Pointer

Channel 4 Registers

Channel 5 Registers

Channel 6 Registers

Channel 7 Registers

18 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Table 2: Control/Status Registers

Name

.
r
d
d
A

h
t
d
i
W

s
s
e
c
c
A

Description

Starting Addr.

120

Starting Addr.

140

Starting Addr.

160

Starting Addr.

180

Starting Addr.

1a0

Starting Addr.

1c0

Starting Addr.

1e0

Starting Addr.

200

Starting Addr.

220

Starting Addr.

240

Starting Addr.

260

Starting Addr.

280

Starting Addr.

2a0

Starting Addr.

2c0

Starting Addr.

2e0

Starting Addr.

300

Starting Addr.

320

Starting Addr.

340

Starting Addr.

360

Starting Addr.

380

Starting Addr.

3a0

Starting Addr.

3c0

Starting Addr.

3e0

Channel 8 Registers

Channel 9 Registers

Channel 10 Registers

Channel 11 Registers

Channel 12 Registers

Channel 13 Registers

Channel 14 Registers

Channel 15 Registers

Channel 16 Registers

Channel 17 Registers

Channel 18 Registers

Channel 19 Registers

Channel 20 Registers

Channel 21 Registers

Channel 22 Registers

Channel 23 Registers

Channel 24 Registers

Channel 25 Registers

Channel 26 Registers

Channel 27 Registers

Channel 28 Registers

Channel 29 Registers

Channel 30 Registers

4.1. Main Conﬁguration Status Register (CSR)

This is the main conﬁguration register of the DMA/Bridge core.

Table 3: CSR Register

Description

Bit #

s
s
e
c
c
A

31:1

RO RESERVED

www.opencores.org

Rev. 1.5

19 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Table 3: CSR Register

Description

Bit #

s
s
e
c
c
A

0

RW PAUSE

Writing a 1 to this register will pause the DMA engine (all channels).
Writing a 0 will enable/resume all operations.
Reading this bit will return the status of the DMA engine: 1-Paused; 0-
Normal Operation. The DMA engine will only pause after it has com-
pleted the current transfer.

Value after reset:
COR: 00 h

4.2.

Interrupt Mask Register (INT_MSK_n)

The interrupt mask registers deﬁne the functionality of the

intb_o
outputs. A bit set to a logical one enables the generation of the interrupt for that
source, a zero disables the generation of an interrupt. The interrupt mask register
INT_MSK_A speciﬁes the behavior for the
 output.
ister for the

 output, the INT_MASK_B reg-

intb_o

inta_o

inta_o

 and

Bit #

s
s
e
c
c
A

Table 4: Interrupt Mask Register

Description

31

30

29

28

27

26

25

24

23

22

21

20

19

18

17

RO RESERVED

RW Interrupt Enable: Enable DMA Channel 30 Interrupts

RW Interrupt Enable: Enable DMA Channel 29 Interrupts

RW Interrupt Enable: Enable DMA Channel 28 Interrupts

RW Interrupt Enable: Enable DMA Channel 27 Interrupts

RW Interrupt Enable: Enable DMA Channel 26 Interrupts

RW Interrupt Enable: Enable DMA Channel 25 Interrupts

RW Interrupt Enable: Enable DMA Channel 24 Interrupts

RW Interrupt Enable: Enable DMA Channel 23 Interrupts

RW Interrupt Enable: Enable DMA Channel 22 Interrupts

RW Interrupt Enable: Enable DMA Channel 21 Interrupts

RW Interrupt Enable: Enable DMA Channel 20 Interrupts

RW Interrupt Enable: Enable DMA Channel 19 Interrupts

RW Interrupt Enable: Enable DMA Channel 18 Interrupts

RW Interrupt Enable: Enable DMA Channel 17 Interrupts

20 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Bit #

s
s
e
c
c
A

Table 4: Interrupt Mask Register

Description

16

15

14

13

12

11

10

9

8

7

6

5

4

3

2

1

0

RW Interrupt Enable: Enable DMA Channel 16 Interrupts

RW Interrupt Enable: Enable DMA Channel 15 Interrupts

RW Interrupt Enable: Enable DMA Channel 14 Interrupts

RW Interrupt Enable: Enable DMA Channel 13 Interrupts

RW Interrupt Enable: Enable DMA Channel 12 Interrupts

RW Interrupt Enable: Enable DMA Channel 11 Interrupts

RW Interrupt Enable: Enable DMA Channel 10 Interrupts

RW Interrupt Enable: Enable DMA Channel 9 Interrupts

RW Interrupt Enable: Enable DMA Channel 8 Interrupts

RW Interrupt Enable: Enable DMA Channel 7 Interrupts

RW Interrupt Enable: Enable DMA Channel 6 Interrupts

RW Interrupt Enable: Enable DMA Channel 5 Interrupts

RW Interrupt Enable: Enable DMA Channel 4 Interrupts

RW Interrupt Enable: Enable DMA Channel 3 Interrupts

RW Interrupt Enable: Enable DMA Channel 2 Interrupts

RW Interrupt Enable: Enable DMA Channel 1 Interrupts

RW Interrupt Enable: Enable DMA Channel 0 Interrupts

Value after reset:
INT_MSK: 0000h

4.3.

Interrupt Source Register (INT_SRCn)

inta_o

This register identiﬁes the source of an interrupt. INT_SRC_A register indi-
 output, INT_SRC_B register indicates the source for

cates the source for
intb_o
 output. Whenever the function controller receives an interrupt, the interrupt
handler must read this register to determine the source and cause of the interrupt.
Some of the bits in this register will be cleared after a read. The software interrupt
handler must make sure it keeps whatever information is required to handle the
interrupt.

Table 5: Interrupt Source Register

Bit #

s
s
e
c
c
A

31

RO RESERVED

Description

www.opencores.org

Rev. 1.5

21 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Bit #

s
s
e
c
c
A

Table 5: Interrupt Source Register

Description

30

29

28

27

26

25

24

23

22

21

20

19

18

17

16

15

14

13

12

11

10

9

8

7

6

5

4

3

2

1

0

RW Interrupt Source: DMA Channel 30

RW Interrupt Source: DMA Channel 29

RW Interrupt Source: DMA Channel 28

RW Interrupt Source: DMA Channel 27

RW Interrupt Source: DMA Channel 26

RW Interrupt Source: DMA Channel 25

RW Interrupt Source: DMA Channel 24

RW Interrupt Source: DMA Channel 23

RW Interrupt Source: DMA Channel 22

RW Interrupt Source: DMA Channel 21

RW Interrupt Source: DMA Channel 20

RW Interrupt Source: DMA Channel 19

RW Interrupt Source: DMA Channel 18

RW Interrupt Source: DMA Channel 17

RW Interrupt Source: DMA Channel 16

RW Interrupt Source: DMA Channel 15

RW Interrupt Source: DMA Channel 14

RW Interrupt Source: DMA Channel 13

RW Interrupt Source: DMA Channel 12

RW Interrupt Source: DMA Channel 11

RW Interrupt Source: DMA Channel 10

RW Interrupt Source: DMA Channel 9

RW Interrupt Source: DMA Channel 8

RW Interrupt Source: DMA Channel 7

RW Interrupt Source: DMA Channel 6

RW Interrupt Source: DMA Channel 5

RW Interrupt Source: DMA Channel 4

RW Interrupt Source: DMA Channel 3

RW Interrupt Source: DMA Channel 2

RW Interrupt Source: DMA Channel 1

RW Interrupt Source: DMA Channel 0

22 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Value after reset:
INT_SRC: 0000h

4.4. Channel Registers

Each channel has 4 registers associated with it. These registers have exactly the

same deﬁnition for each channel.

Figure 11: Channel Registers

CHn_CSR:

CHn_SZ:

CHn_A0:

CHn_AM0:

CHn_A1:

CHn_AM1:

CHn_DESC:

CHn_SWPTR:

31

Control/Status Bits

Transfer Size

Source Address

Source Address Mask

Destination Address

Destination Address Mask

Linked List Descriptor Pointer

Software Pointer

0

4.4.1.

Channel CSR Register (CHn_CSR)

The conﬁguration and status bits specify the operation mode of the channel, as

well as reporting any speciﬁc channel status.

Table 6: Channel CSR Register

Bit #

s
s
e
c
c
A

31:23

RO RESERVED

Description

22

21

20

19

18

17

16

ROC Interrupt Source: Channel transferred CHK_SZ

ROC Interrupt Source: Channel Done

ROC Interrupt Source: Channel Error

RW INE_CHK_DONE

Enable Channel Interrupt after each CHK_SZ has been transferred

RW INE_DONE

Enable Channel Interrupt when Channel is Done

RW INE_ERR

Enable Channel Interrupt on Errors

RW REST_EN

Hardware restart Enable

www.opencores.org

Rev. 1.5

23 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Bit #

s
s
e
c
c
A

Table 6: Channel CSR Register

Description

15:13

RW Channel Priority

(0 Indicating the lowest priority)

12

ROC ERR

DMA channel stopped due to error

11

RO DONE

DMA channel done
(This bit will not be set unless the ARS bit is cleared.)

10

RO BUSY

DMA channel busy

9

8

7

6

5

4

3

2

1

0

WO STOP

Writing a one to this bit will cause the DMA to stop its current transfer
and set the ERR bit.

RW SZ_WB

Enables the writing back of the remaining size to the DESC_CSR when
USE_ED is set and DMA_ND_I was asserted with DMA_REQ_I. See
3.9. “Forcing Next Descriptor” on page 15 for more information.

RW USE_ED

Use External Descriptor Linked List

RW ARS

Automatically restart the channel when transfer completes
0: Auto restart disabled
1: Automatically restarts the DMA channel after TOT_SZ of bytes have
been transferred. The original values programmed into the channel reg-
isters are reloaded and the transfer starts al over again.

RW MODE

0: Normal Mode
1: HW Handshake Mode

RW INC_SRC

0: Do not increment source address (Address 0)
1: Increment source address (Address 0)

RW INC_DST

0: Do not increment destination address (Address 1)
1: Increment destination address (Address 1)

RW SRC_SEL

0: Interface 0 is the source
1: Interface 1 is the source

RW DST_SEL

0: Interface 0 is the destination
1: Interface 1 is the destination

RW CH_EN

Channel Enabled

24 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Value after reset:
CHn_CSR: 0000h

4.4.2.

Channel Size Register (CHn_SZ)

The transfer size register speciﬁes the total and “chunk” transfer sizes for each

channel.

Bit #

s
s
e
c
c
A

Table 7: Channel Size Register

Description

31:25

RO RESERVED

24:16

RW CHK_SZ

Chunk transfer size. Speciﬁes the number of words (4 byte entities) to
be transferred at one given time (not implying they are buffered, but that
they will be transferred for each start event in one bus request cycle). If
chunk size is zero, the DMA engine will always perform TOT_SZ trans-
fers. Maximum chunk size is 2K bytes.

15:12

RO RESERVED

11:0

RW TOT_SZ

Total Transfer Size. Speciﬁes the number of words (4 byte entities) to be
transferred. Maximum total transfer size is16K bytes.

Value after reset:
CHn_SZ: UNDEFINED

4.4.3.

Channel Address Registers (CHn_Am)

The Address Registers specify the source and destination address. Address reg-

ister zero is the source address, address register one is the destination address.
Both registers are 30 bits wide.

Table 8: Address Register

Description

Bit #

s
s
e
c
c
A

31:2

RW Address

1:0

RO RESERVED

Value after reset:
CHn_Am: UNDEFINED

www.opencores.org

Rev. 1.5

25 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

4.4.4.

Channel Address Mask Registers (CHn_AMm)

The Address Mask registers specify the increment mask for the source and des-

tination address. Address Mask Register zero is applied to the source address,
Address Mask Register one to the destination address. Both registers are 28 bits
wide.

Table 9: Address Mask Register

Description

Bit #

s
s
e
c
c
A

31:4

RW Address Mask

3:0

RO RESERVED

Value after reset:
CHn_AMm: FFFFFFFCh

4.4.5.

Linked List Descriptor Pointer (CHn_DESC)

The Linked List Descriptor Pointer register speciﬁes the location of the Linked
List Descriptor. The value of this register will be overwritten with the Next pointer
in the Descriptor, after the descriptor has been fetched.

(This page intentionally left blank)

Table 10: Linked List Descriptor Pointer

Description

Bit #

s
s
e
c
c
A

31:2

RW Address Mask

1:0

RO RESERVED

Value after reset:
CHn_DESC: UNDEFINED

4.4.6.

Software Pointer (CHn_SWPTR)

The Software Pointer is a register that is written by software and indicates the
last location in a circular buffer that has been read/written. The DMA engine will
not cross the address pointed to by the Software pointer and stall the channel until

26 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

the software pointer has been updated. This feature enables the implementation of
FIFO buffers in memory.

Table 11: Software Pointer Register

Bit #

s
s
e
c
c
A

Description

31

RW SWPTR_EN

1 - Enable Software Pointer
0 - Disable Software Pointer

30:2

RW Software pointer

1:0

RO RESERVED

Value after reset:
CHn_SWPTR: 0000h

www.opencores.org

Rev. 1.5

27 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

28 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

5

Core IOs

5.1.

Interface IOs

Both interfaces are WISHBONE Rev. B compliant. The DMA/Bridge core can
be a slave or master on either interface. Actual interface 0 signals are preﬁxed with
“wb0_”, interface 1 signals with “wb1_”. Both interfaces comprise of the follow-
ing signals.

Table 12: Host Interface (WISHBONE)

Name

addr_i

addr_o

h
t
d
i
W

n
o
i
t
c
e
r
i
D

Description

32

I Address Input (for Slave)

32 O Address Output (from Master)

m_data_i

32

I Master Interface Data Input

m_data_o

32 O Master Interface Data Output

s_data_i

32

I Slave Interface Data Input

s_data_o

32 O Slave Interface Data Output

sel_i

4

I

Input for Slave. Indicates which bytes are valid on the data bus.
Whenever this signal is not 1111b during a valid access, the
ERR_O is asserted.

sel_o

4 O Output from Master. Indicates which bytes are valid on the data

bus. Whenever this signal is not 1111b during a valid access, the
ERR_O is asserted.

1

I

Input for Slave. Indicates a Write Cycle when asserted high.

1 O Output from Master. Indicates a Write Cycle when asserted high.

1

I

Input for Slave. Encapsulates a valid transfer cycle.

1 O Output from Master. Encapsulates a valid transfer cycle.

1

I

Input for Slave. Indicates a valid transfer.

1 O Output from Master. Indicates a valid transfer.

we_i

we_o

cyc_i

cyc_o

stb_i

stb_o

www.opencores.org

Rev. 1.5

29 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

Table 12: Host Interface (WISHBONE)

Description

Name

h
t
d
i
W

n
o
i
t
c
e
r
i
D

ack_o

1 O Output from Slave. Acknowledgment Output. Indicates a normal

Cycle termination.

ack_i

1

I

Input for Master. Acknowledgment Output. Indicates a normal
Cycle termination.

err_o

1 O Output from Slave. Error Acknowledgment Output. Indicates an

abnormal cycle termination.

err_i

1

I

Input for Master. Error Acknowledgment Output. Indicates an
abnormal cycle termination.

rty_o

1 O Output from Slave. Retry Output. Indicates that the interface is not

ready, and the master should retry this operation.

rty_i

1

I

Input for Master. Retry Output. Indicates that the interface is not
ready, and the master should retry this operation.

5.2. Additional Control IOs

This section describes additional control signals. Except for the clock and reset

signals all other signals are special extensions and directly a part of the WISH-
BONE speciﬁcation.

Table 13: Additional IOs

Name

clk_i

rst_i

h
t
d
i
W

1

1

n
o
i
t
c
e
r
i
D

I Clock input

I Reset Input

Description

dma_req_i

31

I DMA Request (trigger input)

dma_ack_o

31 O DMA Acknowledge (Asserted when the DMA is done with the

transfer)

dma_nd_i

dma_rest_i

31

31

I

I

Force Next Descriptor advancing

Force Restart of current transfer

inta_o

intb_o

1 O Interrupt Output A

1 O Interrupt Output B

30 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Appendix A

Core HW Conﬁguration

This Appendix describes the conﬁguration of the core.
Almost all conﬁgurable items are passed to the core as parameters. This chap-

ter describes all parameters and other user adjustable deﬁnes.

A.1. Core Parameters

When instantiating the core, the user must pass various parameters to the core:

wb_dma_top#(rf_addr, pri_sel, ch_count,

ch0_conf ... ch30_conf) u0(<IO Ports ...>);

A.1.1. rf_addr

This 4 bit value is compared to WISHBONE address [31:28]. If it matches,
then the internal register ﬁle of the DMA is selected. Otherwise the DMA will
operate in Pass-Through Mode.

Note:
The entire pass-through mode is implemented in combinatorial logic only.

A.1.2. pri_sel

This two bit vector indicates how many priority levels the DMA core supports:

0 indicates 1 priority level
1 indicates 4 priority levels
2 indicates 8 priority levels

A.1.3. ch_count

This value indicates how many total DMA channels are supported.

A.1.4. chN_conf

This is a 4 bit vectors that speciﬁes the abilities of each channel.

chN_conf[0]

www.opencores.org

Rev. 1.5

31 of 33

January 27, 2002

WISHBONE DMA/Bridge Core

OpenCores

 If set to ‘1’ indicates that this channel should be present. Channel 0 must be

always present and must not be removed

chN_conf[1]

A ‘1’ indicates that the channel supports “Automatic Reload” feature.Channels

that do not support the ARS feature will ignore the ARS bit in the channel CSR
register

chN_conf[2]

A ‘1’ indicates that the channel supports “External Linked List Descriptors”.
Channels that do not support Linked List Descriptors will ignore the USE_ED bit
in the channel CSR register and will not have the Linked List Descriptor Pointer
register.

chN_conf[3]

A ‘1’ indicates that the channel supports “Circular Buffers”.Channels that do
not support circular buffers will not have the Address Mask Registers (they will be
forced to all ‘1’ internally) and will also not have the Software pointer register.

A.2. Example

wb_dma_top
#(

4'h1,
2'h1,
6,
4'hf,

// register file address
// Number of priorities (4)
// Number of channels
// Channel 0 Configuration:
// [0]=1 - Channel Exists
// [1]=1 - Channel Supports ARS
// [2]=1 - Channel Supports ED
// [3]=1 - Channel Supports CBUF
// Channel 1 Configuration
// Channel 2 Configuration
// Channel 3 Configuration
// Channel 4 Configuration
// Channel 5 Configuration
// Channel 6 Configuration
// Channel Configuration for Channel 7 - 30 will default to 4’h0

4'hf,
4'hf,
4'hf,
4'hf,
4'hf,
4'hf

)

u0(<IO Ports ...>);

32 of 33

Rev. 1.5

www.opencores.org

OpenCores

WISHBONE DMA/Bridge Core

January 27, 2002

Appendix B

File Structure

This section outlines the hierarchy structure of the WISHBONE DMA/Bridge

core Verilog Source ﬁles.

Figure 12: DMA/Bridge Core Hierarchy Structure

Top Level
wb_dma_top.v

DMA Engine
wb_dma_de.v

Channel Select
wb_dma_ch_sel.v

Register File
wb_dma_rf.v

Wishbone Interface 0
wb_dma_wb_if.v

Wishbone Interface 0
wb_dma_wb_if.v

Arbiter
wb_dma_ch_arb.v

Master interface
wb_dma_wb_mast.v

Master interface
wb_dma_wb_mast.v

Priority Encoder
wb_dma_ch_pri_enc.v

Slave Interface
wb_dma_wb_slv.v

Slave Interface
wb_dma_wb_slv.v

Priority Encoder
wb_dma_pri_enc_sub.v

www.opencores.org

Rev. 1.5

33 of 33


