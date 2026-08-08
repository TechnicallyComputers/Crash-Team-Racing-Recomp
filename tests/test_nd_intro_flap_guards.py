#!/usr/bin/env python3
"""Source-invariant guards for CTR ND intro flap / digit-rain OT path.

Hermetic: no disc, no binary. Keeps the opt-in FLAP_LAST DMA hook and docs,
and asserts CTR no longer default-enables FLAP_LAST=1 (shreds crate glow after
AVSZ MAC0 fix).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    dma = (ROOT / "psxrecomp/runtime/src/dma.c").read_text(encoding="utf-8")
    main_cpp = (ROOT / "psxrecomp/runtime/src/main.cpp").read_text(encoding="utf-8")
    nd_ot = (ROOT / "psxrecomp/runtime/src/nd_intro_ot.c").read_text(encoding="utf-8")
    game = (ROOT / "game.toml").read_text(encoding="utf-8")
    symbols = (ROOT / "symbols.toml").read_text(encoding="utf-8")
    check = ROOT / "tools/nd_intro_flap_check.py"

    required = [
        (dma, "PSX_ND_SIB_FLAP_LAST", "dma.c missing PSX_ND_SIB_FLAP_LAST hook"),
        (dma, "op == 0x36u", "dma.c missing 0x36 glow skip predicate"),
        (dma, "sx_max >= 280", "dma.c missing s11 sx_max>=280 filter for 0x36"),
        (dma, "ot_rank >= 1600u", "dma.c missing digit-rain OT-rank gate for 0x36 skip"),
        (dma, "xy & 0x7FFu", "dma.c missing signed-11-bit SX parse for 0x36"),
        (dma, "opt-in", "dma.c missing opt-in wording for FLAP_LAST"),
        (main_cpp, "AVSZ3 MAC0", "main.cpp missing AVSZ MAC0 / FLAP_LAST default-off note"),
        (nd_ot, "0x45444F43u", "nd_intro_ot.c missing CODE fourcc preference"),
        (nd_ot, "psx_nd_note_wood_batch_ot_tagged", "nd_intro_ot.c missing tagged batch OT cache"),
        (game, "PSX_ND_SIB_FLAP_LAST", "game.toml missing FLAP_LAST documentation"),
        (game, "Default off", "game.toml missing Default off for FLAP_LAST"),
        (game, "nd_intro_flap_check.py", "game.toml missing regression tool pointer"),
        (symbols, "NdIntroSiblingRtptEmit", "symbols.toml missing NdIntroSiblingRtptEmit"),
        (symbols, "PSX_ND_SIB_FLAP_LAST", "symbols.toml note missing FLAP_LAST mention"),
        (symbols, "0x800FF390", "symbols.toml missing stable CODE model address"),
    ]

    failures = []
    for source, needle, message in required:
        if needle not in source:
            failures.append(message)

    # Must not re-introduce CTR default-on FLAP_LAST=1.
    if 'setenv("PSX_ND_SIB_FLAP_LAST", "1"' in main_cpp:
        failures.append("main.cpp must not default-setenv PSX_ND_SIB_FLAP_LAST=1")
    if "_putenv_s(\"PSX_ND_SIB_FLAP_LAST\", \"1\")" in main_cpp:
        failures.append("main.cpp must not _putenv_s PSX_ND_SIB_FLAP_LAST=1")

    if not check.is_file():
        failures.append(f"missing runtime check script: {check}")
    else:
        body = check.read_text(encoding="utf-8")
        for needle, message in (
            ("PSX_ND_SIB_FLAP_LAST", "flap check missing FLAP_LAST env control"),
            ("right_flap", "flap check missing right_flap green metric"),
            ("digit_col", "flap check missing digit_col fountain metric"),
            ("warm_right", "flap check missing warm_right half-cut guard"),
            ("--ctest", "flap check missing --ctest mode"),
            ("sys.exit(77)", "flap check missing ctest SKIP_RETURN_CODE 77"),
            ('flap_last="0"', "flap check must verify FLAP_LAST=0 as the clean path"),
        ):
            if needle not in body:
                failures.append(message)

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("PASS: CTR ND intro flap source guards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
