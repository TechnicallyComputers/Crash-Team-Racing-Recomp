# Crash Team Racing  Recompiled

## Disclaimer

Crash Team Racing has critical issues we need to address by debugging and working on the psxrecomp project still, specifically the post race screen is not loading after selecting Change Level, and potentially other issues I need to test for still.  When the game is stable it will be back on the catalog and released into the RetComM launcher.

Static recompilation of **Crash Team Racing** built on
[psxrecomp](https://github.com/mstan/psxrecomp) and
[recomp-ui](https://github.com/mstan/recomp-ui).

Crash Team Racing is a kart racing game featuring popular characters from the Crash Bandicoot series. The gameplay is very similar to other kart racing video games like Mario Kart: players have to choose a character and compete against the other racers on various racetracks. The story mode allows you to choose any one of the characters to complete all the main races and beat the ultimate boss Nitrous Oxide. Each of the main races are against 7 other AI competitors with 5 boss races. There are also a few arcade modes up to 4 players.

| | |
|---|---|
| Players | 4 |
| Region | USA |
| Publisher | Naughty Dog |
| Year | 1999 |

Scaffolded with the New Project Layout. See
`psxrecomp/docs/GAME_PROJECT_SETUP.md` for the full flow.

## Legal

You must own the original game. Disc images under `disc/` are gitignored and
must never be committed. Retail BIOS dumps are not redistributed; OpenBIOS is
used for Generate unless you supply your own SCPH locally.

Optional box art under `launcher_assets/img/` may come from
[libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails)
(`Named_Boxarts`); see `BOXART_SOURCE.txt` when present.

## Quick start (dev)

```bash
git submodule update --init --recursive
./psxrecomp/tools/ci/build_emitters.sh
python3 psxrecomp/psxrecomp_cli.py generate \
  --config game.toml --project-root . --disc disc/<your>.cue
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --target psx-runtime
```

Zip prefix for CI artifacts: `ctr`.

## Symbols

Progressive map: `symbols.toml` → `python3 tools/sync_symbols.py` →
`psx_symbols.h` (`PSX_FN_*`). See `psxrecomp/docs/SYMBOLS.md`.

## Framework pins

Submodule gitlinks (`psxrecomp`, optional `recomp-ui`, nested `recomp-net`)
are authoritative. `framework_pins.txt` is an optional scaffold snapshot;
release CI logs SHAs with `record_pins.sh` but builds whatever the gitlinks
resolve to. Bump submodules deliberately — do not float on `main`/`master`
in release CI.
