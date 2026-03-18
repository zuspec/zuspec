#!/usr/bin/env python3
"""PSS → Python Runtime demo.

Run from any directory:
    python examples/pss_demo/run_demo.py

Or from this directory:
    python run_demo.py

The model is defined in bus.pss (loaded from the same directory as this script).
"""

import pathlib
import sys
from zuspec.fe.pss import load_pss_files
from zuspec.dataclasses import randomize

HERE = pathlib.Path(__file__).parent


def hr(title: str):
    print(f"\n── {title} {'─' * (54 - len(title))}")


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║       PSS → Python Runtime  ·  bus.pss demo          ║")
    print("╚══════════════════════════════════════════════════════╝")

    ns = load_pss_files([HERE / "bus.pss"])

    # ── 1. Struct: scalar constraints + bit-slice alignment ──────────────────
    hr("1. BusCmd — scalar constraints + modulo alignment")
    for seed in range(4):
        cmd = ns.BusCmd()
        randomize(cmd, seed=seed)
        aligned  = cmd.addr % 4 == 0
        in_range = 0x100 <= cmd.addr < 0x1000
        print(f"  seed={seed}: addr=0x{cmd.addr:04x}  prot={cmd.prot}"
              f"  aligned={aligned}  in-range={in_range}")
    assert aligned and in_range

    # ── 2. Struct inheritance: WriteCmd : BusCmd ─────────────────────────────
    hr("2. WriteCmd : BusCmd — struct inheritance")
    for seed in range(4):
        w = ns.WriteCmd()
        randomize(w, seed=seed)
        print(f"  seed={seed}: addr=0x{w.addr:04x}  data=0x{w.data:08x}"
              f"  byte_en=0b{w.byte_en:04b}  "
              f"aligned={w.addr%4==0}  be>0={w.byte_en>0}")
    assert w.addr % 4 == 0 and w.byte_en > 0

    # ── 3. Struct inheritance: ReadCmd : BusCmd ──────────────────────────────
    hr("3. ReadCmd : BusCmd — struct inheritance")
    for seed in range(4):
        r = ns.ReadCmd()
        randomize(r, seed=seed)
        print(f"  seed={seed}: addr=0x{r.addr:04x}  burst_len={r.burst_len}"
              f"  aligned={r.addr%4==0}  1≤len≤8={1<=r.burst_len<=8}")
    assert r.addr % 4 == 0 and 1 <= r.burst_len <= 8

    # ── 4. Fixed array: direct-index + foreach constraints ───────────────────
    hr("4. BurstPayload — fixed array with index + foreach constraints")
    for seed in range(4):
        bp = ns.BurstPayload()
        randomize(bp, seed=seed)
        hexbytes = " ".join(f"0x{b:02x}" for b in bp.bytes)
        sync_ok  = bp.bytes[0] == 0xA5
        nozero   = all(b > 0 for b in bp.bytes)
        print(f"  seed={seed}: [{hexbytes}]  sync={sync_ok}  no-zeros={nozero}")
    assert sync_ok and nozero

    # ── 5. Unique constraint over scalar fields ───────────────────────────────
    hr("5. ArbConfig — unique priority per master")
    for seed in range(4):
        arb = ns.ArbConfig()
        randomize(arb, seed=seed)
        prios = [arb.prio_m0, arb.prio_m1, arb.prio_m2, arb.prio_m3]
        print(f"  seed={seed}: prios={prios}  all<8={all(p<8 for p in prios)}"
              f"  distinct={len(set(prios))==4}")
    assert len(set(prios)) == 4

    # ── 6. Component actions + action inheritance ─────────────────────────────
    hr("6. BusCtrl actions — action inheritance + bit-slice alignment")
    for seed in range(4):
        w = ns.BusCtrl.Write()
        randomize(w, seed=seed)
        print(f"  Write seed={seed}: addr=0x{w.addr:04x}  data=0x{w.data:08x}"
              f"  byte_en=0b{w.byte_en:04b}  "
              f"aligned={w.addr%4==0}  be>0={w.byte_en>0}")
    for seed in range(4):
        r = ns.BusCtrl.Read()
        randomize(r, seed=seed)
        print(f"  Read  seed={seed}: addr=0x{r.addr:04x}  burst_len={r.burst_len}"
              f"  aligned={r.addr%4==0}  1≤len≤8={1<=r.burst_len<=8}")
    assert w.addr % 4 == 0 and r.addr % 4 == 0

    print("\n✓ All assertions passed.\n")


if __name__ == "__main__":
    # Suppress the low-level zsp-parser debug noise on stderr
    import os
    os.environ.setdefault("ZSP_PARSER_QUIET", "1")
    main()
