#!/usr/bin/env python3
"""ND intro right-flap / digit-rain regression (SCUS-94426).

Boots headless recomp, waits for digit rain, then checks:
  - PSX_ND_SIB_FLAP_LAST=0 (default/clean): right-flap green≈0, wood present on
    the right half (no empty cut), digit fountain alive — relies on AVSZ MAC0
    OT indexing, not the 0x36 skip
  - optional --legacy-skip: also boot with FLAP_LAST=1 (metrics only; shreds glow)
  - optional OT/face probe dump (CODE+228, sibling main OT, GP0 ranks)

ctest: use --ctest (FLAP_LAST=0 clean path). Missing disc/binary → sys.exit(77)
(CMake SKIP_RETURN_CODE 77). Kill only via recorded PID (never pkill -f).

Examples:
  python3 tools/nd_intro_flap_check.py
  python3 tools/nd_intro_flap_check.py --ctest
  python3 tools/nd_intro_flap_check.py --legacy-skip --out /tmp/ctr-nd-check
  python3 tools/nd_intro_flap_check.py --duck-port 4371
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN = ROOT / "build-debugtcp" / "Crash_Team_Racing__Recompiled"
DISC = ROOT / "disc" / "CTR - Crash Team Racing (USA).cue"
GAME = ROOT / "game.toml"
CLIENT = ROOT / "psxrecomp" / "tools" / "debug_client.py"
CTEST_SKIP = 77

CODE_MODEL = 0x800FF390
GLOW_MODEL = 0x800FF294
TAG_CODE = 0x45444F43
TAG_GLOW = 0x574F4C47


def rpc(port: int, *args: str) -> dict:
    r = subprocess.run(
        ["python3", str(CLIENT), "--port", str(port), *args],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout or "")[:400], "err": (r.stderr or "")[:200]}


def u32(x) -> int:
    if x is None:
        return 0
    if isinstance(x, str):
        return int(x, 16) if x.lower().startswith("0x") else int(x)
    return int(x) & 0xFFFFFFFF


def sxy(w: str):
    v = int(w, 16) & 0xFFFFFFFF
    x = v & 0xFFFF
    y = (v >> 16) & 0xFFFF
    if x >= 0x8000:
        x -= 0x10000
    if y >= 0x8000:
        y -= 0x10000
    return x, y


def rain_info(dump: dict) -> dict | None:
    n36 = n68 = n30w = 0
    ranks30: list[int] = []
    ranks36: list[int] = []
    for e in dump.get("entries") or []:
        op = int(e.get("op", "0"), 16)
        ot = e.get("ot")
        if op == 0x36:
            n36 += 1
            if ot is not None:
                ranks36.append(ot)
        elif op == 0x68:
            n68 += 1
        elif op == 0x30:
            ws = e.get("w") or []
            if any(sxy(ws[i])[0] > 350 for i in (1, 3, 5) if i < len(ws)):
                n30w += 1
                if ot is not None:
                    ranks30.append(ot)
    # FLAP_LAST skips right-band 0x36 (~half), so gate on n36>=40 plus stars
    # (0x68). Requiring 60 missed the intro and latched onto a later scene.
    if n36 < 40 or n30w < 2 or n68 < 20:
        return None
    return {
        "n36": n36,
        "n68": n68,
        "n30w": n30w,
        "wide30_ot": [min(ranks30), max(ranks30)] if ranks30 else None,
        "op36_ot": [min(ranks36), max(ranks36)] if ranks36 else None,
    }


def fb_metrics(png: Path) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return {"ok": False, "error": "Pillow not installed"}
    if not png.exists():
        return {"ok": False, "error": f"missing {png}"}
    im = Image.open(png).convert("RGB")
    px = im.load()
    w, h = im.size

    def region(x0, y0, x1, y1):
        g = org = n = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g_, b = px[x, y]
                n += 1
                if g_ > r + 15 and g_ > b + 15 and g_ > 60:
                    g += 1
                if r > 100 and g_ > 60 and b < 80:
                    org += 1
        return {"green": g, "orange": org, "n": n}

    # Mid-band wood check: FLAP_LAST two-pass regress emptied x>~256 (warmR≈0).
    def warm_band(x0, x1):
        warm = 0
        y0, y1 = h // 4, 3 * h // 4
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g_, b = px[x, y]
                # Wood / crate browns + lit flaps (not pure green glow).
                if r > 70 and g_ > 40 and b < 100 and r + g_ > b + 40:
                    warm += 1
        return warm

    mid = w // 2
    return {
        "ok": True,
        "size": [w, h],
        "right_flap": region(int(w * 0.55), h // 4, int(w * 0.82), 3 * h // 4),
        "digit_col": region(int(w * 0.35), h // 5, int(w * 0.50), 4 * h // 5),
        "warm_left": warm_band(mid // 4, mid),
        "warm_right": warm_band(mid, mid + 3 * mid // 4),
    }


def mem_word(port: int, addr: int) -> int | None:
    r = rpc(port, "mem_words", f"addr=0x{addr:08X}", "count=1")
    words = r.get("words") or []
    if not words:
        return None
    return u32(words[0])


def kill_pidfile(pidfile: Path) -> None:
    if not pidfile.exists():
        return
    try:
        os.kill(int(pidfile.read_text().strip()), signal.SIGTERM)
    except Exception:
        pass
    pidfile.unlink(missing_ok=True)
    time.sleep(0.8)


def resolve_bin(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    env_bin = os.environ.get("CTR_RECOMP_BIN")
    if env_bin:
        return Path(env_bin)
    return DEFAULT_BIN


def boot_recomp(
    port: int,
    out: Path,
    flap_last: str,
    extra_env: dict,
    bin_path: Path,
) -> subprocess.Popen:
    cwd = bin_path.resolve().parent
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env["SDL_VIDEODRIVER"] = env.get("SDL_VIDEODRIVER", "x11")
    env["PSX_ND_SIB_FLAP_LAST"] = flap_last
    # Keep experimental OT rewrites off for the regression gate.
    env["PSX_ND_SIB_OT_BATCH"] = "0"
    env.update(extra_env)
    log = open(out / f"recomp_flap{flap_last}.log", "w")
    game_arg = str(GAME) if not (cwd / ".." / "game.toml").exists() else "../game.toml"
    proc = subprocess.Popen(
        [
            str(bin_path),
            "--no-launcher",
            "--debug-port",
            str(port),
            "--game",
            game_arg,
            "--disc",
            str(DISC),
            "--headless",
        ],
        cwd=str(cwd),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc


def wait_ping(port: int, timeout_s: float = 40.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if rpc(port, "ping").get("ok"):
            return True
        time.sleep(0.25)
    return False


def wait_rain(port: int, timeout_s: float = 90.0) -> tuple[dict | None, int, dict]:
    t0 = time.time()
    last_dump: dict = {}
    while time.time() - t0 < timeout_s:
        st = rpc(port, "gpu_ring_stats")
        nf = st.get("newest_frame") or 0
        dump = rpc(port, "gpu_frame_dump", f"frame={nf}", "count=8192")
        last_dump = dump
        info = rain_info(dump)
        if info:
            info["frame"] = nf
            return info, nf, dump
        time.sleep(0.12)
    return None, 0, last_dump


def bucket_order(dump: dict, rank: int) -> dict:
    seq = []
    for e in dump.get("entries") or []:
        if e.get("ot") != rank:
            continue
        op = int(e.get("op", "0"), 16)
        if op == 0x36:
            seq.append("36")
        elif op == 0x30:
            ws = e.get("w") or []
            if any(sxy(ws[i])[0] > 350 for i in (1, 3, 5) if i < len(ws)):
                seq.append("30")
    return {
        "rank": rank,
        "n30": seq.count("30"),
        "n36": seq.count("36"),
        "first": seq[:6],
        "last": seq[-6:],
        "digits_after_flaps": bool(seq)
        and seq.index("30") < len(seq)
        and "36" in seq
        and seq.index("30") < (len(seq) - 1 - seq[::-1].index("36")),
    }


def probe_ot(port: int, out: Path) -> dict:
    """Phased OT dump during rain (64-sample ring — avoid WoodEmit flood)."""

    def tag_name(v: int) -> str:
        b = (v & 0xFFFFFFFF).to_bytes(4, "little")
        return b.decode() if all(32 <= c < 127 for c in b) else f"0x{v:08X}"

    def pull(pcs: str, sleep_s: float = 0.5) -> dict:
        arm = rpc(port, "pc_probe_arm", "n=64", f"pcs={pcs}")
        time.sleep(sleep_s)
        return {"arm": arm, "dump": rpc(port, "pc_probe_dump")}

    p_setup = pull("0x8006AAF0")
    p_sib = pull("0x80069BB0,0x80069CC4")
    p_wood = pull("0x8006A608")
    (out / "pc_probe_setup.json").write_text(json.dumps(p_setup["dump"], indent=2))
    (out / "pc_probe_sib.json").write_text(json.dumps(p_sib["dump"], indent=2))
    (out / "pc_probe_wood.json").write_text(json.dumps(p_wood["dump"], indent=2))

    def by_pc(dump: dict) -> dict:
        d = defaultdict(list)
        for s in dump.get("samples") or []:
            d[u32(s.get("pc"))].append(s)
        return d

    setup = []
    for s in by_pc(p_setup["dump"]).get(0x6AAF0, []):
        setup.append(
            {
                "frame": s.get("frame"),
                "tag": tag_name(u32(s.get("ot_base"))),
                "ot228": f"0x{u32(s.get('ot_index')):08X}",
                "helper": f"0x{u32(s.get('depth')):08X}",
                "model": f"0x{u32(s.get('v0')):08X}",
            }
        )

    face_a3 = Counter()
    for s in by_pc(p_sib["dump"]).get(0x69CC4, []):
        face_a3[u32(s.get("t0") or s.get("depth"))] += 1

    sib = []
    for s in by_pc(p_sib["dump"]).get(0x69BB0, []):
        # mode/depth at sibling entry are CODE/GLOW +228 (debug_server probe).
        code228 = u32(s.get("mode"))
        main = u32(s.get("ot_base"))
        # face_hi≈0 ⇒ AddPrim slot == a3 == main+4092
        sib.append(
            {
                "frame": s.get("frame"),
                "main_ot": f"0x{main:08X}",
                "a3_last_slot": f"0x{(main + 4092) & 0xFFFFFFFF:08X}" if main else "0x0",
                "face_hi_expected": 0,
                "code228": f"0x{code228:08X}",
                "glow228": f"0x{u32(s.get('depth')):08X}",
                "cached_batch": f"0x{u32(s.get('ot_index')):08X}",
            }
        )

    code_tag = mem_word(port, CODE_MODEL + 8)
    glow_tag = mem_word(port, GLOW_MODEL + 8)
    code228 = mem_word(port, CODE_MODEL + 228)
    glow228 = mem_word(port, GLOW_MODEL + 228)
    wood_bases = Counter(
        u32(s.get("ot_base")) for s in by_pc(p_wood["dump"]).get(0x6A608, [])
    )

    return {
        "code_model": {
            "addr": f"0x{CODE_MODEL:08X}",
            "tag_ok": code_tag == TAG_CODE,
            "tag": f"0x{(code_tag or 0):08X}",
            "plus228": f"0x{(code228 or 0):08X}",
        },
        "glow_model": {
            "addr": f"0x{GLOW_MODEL:08X}",
            "tag_ok": glow_tag == TAG_GLOW,
            "tag": f"0x{(glow_tag or 0):08X}",
            "plus228": f"0x{(glow228 or 0):08X}",
        },
        "setup_samples": setup[:24],
        "sibling_samples": sib[:12],
        "face_loop_a3": [(hex(a), n) for a, n in face_a3.most_common(4)],
        "wood_emit_bases": [(hex(a), n) for a, n in wood_bases.most_common(6)],
        "code228_in_wood": bool(code228 and code228 in wood_bases),
        "note": (
            "Look-up flaps: face_hi≈0 → AddPrim at a3=main_ot+4092 (ot_rank 0). "
            "Digits: CODE+228 + (MAC0>>17). FLAP_LAST skips right-band 0x36."
        ),
    }


def run_case(
    *,
    port: int,
    out: Path,
    flap_last: str,
    expect_fixed: bool,
    do_probe: bool,
    bin_path: Path,
) -> dict:
    pidfile = out / "game.pid"
    kill_pidfile(pidfile)
    proc = boot_recomp(port, out, flap_last, {}, bin_path)
    pidfile.write_text(str(proc.pid))
    result: dict = {"flap_last": flap_last, "pid": proc.pid, "ok": False}
    try:
        if not wait_ping(port):
            result["error"] = "no ping"
            result["log_tail"] = (out / f"recomp_flap{flap_last}.log").read_text()[-800:]
            return result
        info, nf, dump = wait_rain(port)
        if not info:
            result["error"] = "no digit rain"
            return result
        result["rain"] = info
        (out / f"gp0_flap{flap_last}.json").write_text(
            json.dumps({"frame": nf, "rain": info, "n_entries": len(dump.get("entries") or [])})
        )

        png = out / f"fb_flap{flap_last}.png"
        shot = rpc(port, "screenshot_file", f"path={png}")
        result["screenshot"] = {"ok": shot.get("ok"), "path": str(png)}
        fb = fb_metrics(png)
        result["fb"] = fb

        if info.get("wide30_ot") and info["wide30_ot"][0] == info["wide30_ot"][1]:
            if info.get("op36_ot") and info["op36_ot"][0] == info["wide30_ot"][0]:
                result["same_bucket"] = bucket_order(dump, info["wide30_ot"][0])

        if do_probe:
            result["ot_probe"] = probe_ot(port, out)

        right_g = (fb.get("right_flap") or {}).get("green")
        right_org = (fb.get("right_flap") or {}).get("orange")
        digit_g = (fb.get("digit_col") or {}).get("green")
        warm_l = fb.get("warm_left")
        warm_r = fb.get("warm_right")
        if right_g is None or digit_g is None or warm_l is None or warm_r is None:
            result["error"] = "fb metrics failed"
            return result

        if expect_fixed:
            # Fixed: no green on right flap; wood still drawn on right half;
            # digit fountain still present. (green≈0 alone passed when FLAP_LAST
            # cut the right half empty.)
            right_wood_ok = (right_org or 0) >= 80 or warm_r >= 600
            half_ok = warm_r >= max(600, warm_l // 4)
            ok = right_g <= 30 and digit_g >= 200 and right_wood_ok and half_ok
            result["checks"] = {
                "right_flap_clean": right_g <= 30,
                "right_wood_present": right_wood_ok,
                "right_half_not_cut": half_ok,
                "digit_fountain_alive": digit_g >= 200,
                "right_g": right_g,
                "right_orange": right_org,
                "warm_left": warm_l,
                "warm_right": warm_r,
                "digit_g": digit_g,
            }
        else:
            # Bug baseline: green overpaint on right flap; fountain alive;
            # geometry still present (proves overpaint, not empty cut).
            ok = right_g >= 150 and digit_g >= 200 and warm_r >= 600
            result["checks"] = {
                "right_flap_overpaint": right_g >= 150,
                "digit_fountain_alive": digit_g >= 200,
                "right_geometry_present": warm_r >= 600,
                "right_g": right_g,
                "warm_right": warm_r,
                "digit_g": digit_g,
            }
        result["ok"] = ok
        return result
    finally:
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        pidfile.unlink(missing_ok=True)
        time.sleep(0.5)


def try_duck(port: int, out: Path) -> dict | None:
    if not rpc(port, "ping").get("ok"):
        return {"ok": False, "error": f"DuckStation not reachable on {port}"}
    info, nf, dump = wait_rain(port, timeout_s=5.0)
    if not info:
        # Oracle may already be parked on rain — try newest frame only.
        st = rpc(port, "gpu_ring_stats")
        nf = st.get("newest_frame") or 0
        dump = rpc(port, "gpu_frame_dump", f"frame={nf}", "count=8192")
        info = rain_info(dump)
        if info:
            info["frame"] = nf
    if not info:
        return {"ok": False, "error": "DuckStation: no rain frame in ring"}
    png = out / "fb_duck.png"
    shot = rpc(port, "screenshot_file", f"path={png}")
    fb = fb_metrics(png) if shot.get("ok") else {"ok": False}
    return {
        "ok": True,
        "port": port,
        "rain": info,
        "fb": fb,
        "note": "Compare right_flap.green (~0) and warm_right (wood present) to recomp FLAP_LAST=0.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4373)
    ap.add_argument("--out", type=Path, default=Path("/tmp/ctr-nd-flap-check"))
    ap.add_argument("--bin", type=Path, default=None, help="Path to Crash_Team_Racing__Recompiled")
    ap.add_argument(
        "--legacy-skip",
        action="store_true",
        help="Also boot FLAP_LAST=1 (metrics only; known to shred crate glow)",
    )
    ap.add_argument("--bug", action="store_true", help=argparse.SUPPRESS)  # alias
    ap.add_argument("--probe", action="store_true", help="Dump CODE+228 / sibling OT probe during rain")
    ap.add_argument("--duck-port", type=int, default=0, help="If set, try DuckStation oracle compare")
    ap.add_argument("--only-bug", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--ctest",
        action="store_true",
        help="ctest mode: FLAP_LAST=0 clean path; exit 77 if disc/binary missing",
    )
    args = ap.parse_args()

    if args.bug:
        args.legacy_skip = True
    if args.ctest:
        args.legacy_skip = False
        args.only_bug = False

    bin_path = resolve_bin(args.bin)
    if not bin_path.is_file() or not DISC.is_file():
        msg = []
        if not bin_path.is_file():
            msg.append(f"missing binary: {bin_path}")
        if not DISC.is_file():
            msg.append(f"missing disc: {DISC}")
        print("SKIP: " + "; ".join(msg), flush=True)
        if args.ctest:
            # Keep the literal sys.exit(77) for source guards / SKIP_RETURN_CODE.
            sys.exit(77)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"cases": [], "bin": str(bin_path)}
    rc = 0

    if not args.only_bug:
        print("== FLAP_LAST=0 (expect clean flaps + fountain) ==", flush=True)
        fixed = run_case(
            port=args.port,
            out=args.out,
            flap_last="0",
            expect_fixed=True,
            do_probe=args.probe,
            bin_path=bin_path,
        )
        summary["cases"].append(fixed)
        print(json.dumps(fixed.get("checks") or fixed.get("error"), indent=2), flush=True)
        if not fixed.get("ok"):
            rc = 1

    if args.legacy_skip:
        print("== FLAP_LAST=1 (legacy skip; metrics only) ==", flush=True)
        legacy = run_case(
            port=args.port,
            out=args.out,
            flap_last="1",
            expect_fixed=True,
            do_probe=False,
            bin_path=bin_path,
        )
        legacy["note"] = "opt-in skip; may shred glow — not required for pass"
        summary["cases"].append(legacy)
        print(json.dumps(legacy.get("checks") or legacy.get("error"), indent=2), flush=True)
        # Do not fail ctest/default on legacy-skip metrics.

    if args.duck_port:
        print(f"== DuckStation :{args.duck_port} ==", flush=True)
        duck = try_duck(args.duck_port, args.out)
        summary["duck"] = duck
        print(json.dumps(duck, indent=2)[:1200], flush=True)

    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {args.out / 'summary.json'}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
