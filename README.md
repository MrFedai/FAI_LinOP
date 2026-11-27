# FAI_LinOP v3

**Set up a Linux machine from one profile — packages, GNOME, monitors, shell, gaming, security — with a plan you see first, a journal of every change and a rollback.**

[![CI](https://github.com/MrFedai/FAI_LinOP/actions/workflows/ci.yml/badge.svg)](https://github.com/MrFedai/FAI_LinOP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Status](https://img.shields.io/badge/v3.0.0-native%20test%20pending-yellow)

## Install — one line

```bash
git clone https://github.com/MrFedai/FAI_LinOP.git ~/FAI_LinOP && ~/FAI_LinOP/setup.sh
```

- Run it as your **normal user**, not with `sudo` — FAI_LinOP asks for sudo only for the commands that need it.
- Needs `git` (`sudo pacman -S git` · `sudo apt install git` · `sudo dnf install git`).
- `setup.sh` only prepares [uv](https://docs.astral.sh/uv/) (distro package on Arch/Fedora; on Debian/Ubuntu `python3-venv` + uv in a private venv — never `curl | sh`) and starts the wizard: **questions → plan → one confirmation → apply**.

| Want to… | Run |
|---|---|
| see what would change first (nothing is modified) | `~/FAI_LinOP/setup.sh plan` |
| use the owner's profile | `~/FAI_LinOP/setup.sh --profile ~/FAI_LinOP/profiles/mrfedai.toml` |
| update FAI_LinOP | `git -C ~/FAI_LinOP pull` |
| undo the file and monitor-layout changes of the last run | `~/FAI_LinOP/setup.sh rollback` |

## What is FAI_LinOP?

FAI_LinOP turns a fresh Linux install into *your* machine. You describe the result once in a TOML profile — which package groups, which desktop settings, which shell, gaming or security tools — and FAI_LinOP does the rest on Arch, Debian, Ubuntu or Fedora.

v3 is a rewrite of [ArCoN v2.5](legacy/v2.5/README.md), a 1885-line Bash script, in Python. The working v2.5 stays at [MrFedai/ArCoN](https://github.com/MrFedai/ArCoN); this repository keeps its full history (tag `v2.5.0`). Every v2.5 feature is kept, fixed or explicitly marked in [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md).

What makes v3 different from a setup script:

- **Plan first, one confirmation.** All questions are asked up front; you see every package, file, setting and service with its risk before anything changes.
- **Journal + rollback.** Every run is logged; changed files and GNOME settings are backed up and can be restored. Snapper/Timeshift snapshots are used when available.
- **Idempotent.** Run it again and it prints "Nothing to do" — or continues where an interrupted run stopped (`linop resume`).
- **Your dotfiles stay yours.** `configs/` (GNOME `gno.conf`, Terminator, Hyprland) is deployed byte-identical in its native format; only documented substitutions (user name, wallpaper) are made.
- **Nothing is guessed.** Package names are mapped per distro (repo → AUR → Flatpak); anything missing is reported, not improvised.

### What it sets up

| Module | What it does |
|---|---|
| system | full upgrade; Arch: mirror ranking, multilib, optional keyring reset |
| packages | groups (base, essentials, media, cyber, remote, privacy, power) from the distro repos, AUR (Arch) or Flatpak fallback |
| gnome | dark theme, keybindings, app folders from `configs/gno.conf`; optional debloat |
| display | detects every monitor's best resolution/refresh rate, keeps your layout, falls back if a mode does not work |
| hyprland | optional desktop with FAI_LinOP's own config and a generated monitor block |
| dotfiles | deploys `configs/`; `linop dotfiles diff\|capture` compares or copies them back |
| terminal / shell | Terminator/Kitty/Alacritty themes; Zsh + Oh-My-Zsh (pinned commits), Fish/Bash + Starship |
| gaming | Steam, GameMode, MangoHud; GPU detected automatically (NVIDIA open/DKMS, AMD, Intel) |
| security | all opt-in: firewall, sysctl hardening, SSH hardening, ClamAV, OpenSnitch, USBGuard, scans; BlackArch on Arch |
| optimization / cleanup | ZRAM, SSD TRIM, Bluetooth; orphaned packages, package cache (keeps recent versions) |

## How a run works

```
wizard (all questions up front) -> plan (every package, file, setting, service; risk; reversibility)
  -> one confirmation -> preflight (disk, network, live ISO, pacman lock, sudo) -> snapshot if Snapper/Timeshift
  -> apply + verify each action -> report from real results -> reboot prompt only if needed
```

- **Dry run** (`linop plan`): read-only probes run, every change is only recorded. GNOME monitor changes are checked by Mutter itself ("verify" mode).
- **Journal**: `~/.local/state/linop/runs/<run>/journal.jsonl` — drives `linop resume` and `linop rollback`.
- **Rollback**: files, GNOME settings and the GNOME monitor layout are restored (each item reported, failures marked FAILED); installed packages are listed, never "rolled back" silently.

## Commands

`setup.sh` passes everything to `linop`, so `~/FAI_LinOP/setup.sh plan` = `linop plan`.

| Command | What it does |
|---|---|
| `linop` | wizard → plan → confirm → apply |
| `linop plan` / `linop apply` | dry run / apply the saved profile |
| `linop wizard` | answer the questions, save the profile |
| `linop resume` | continue an interrupted or failed run |
| `linop rollback [RUN]` | restore files + dconf changed by a run |
| `linop runs` | list runs |
| `linop profile init\|show\|validate\|path` | documented profile template, effective values, checks |
| `linop display show\|capture` | monitors, best modes; save the current layout into the profile |
| `linop dotfiles diff\|capture` | compare deployed dotfiles with the repo; copy them back |
| `linop reset [--uninstall] [--gnome]` | Smart Factory Reset (backup first, typed `CLEAN`) |
| `linop doctor` | detected OS, GPU, disk, kernels, snapshot tool |

Global options work before or after the command: `--profile FILE`, `-n/--dry-run`, `-y/--yes` (never answers typed confirmations), `--keep-going`, `-v`.

## Profile

The wizard saves your answers to `~/.config/linop/profile.toml` and offers to reuse them next time. `linop profile init` writes a template with every key documented ([fai_linop/data/profile.template.toml](fai_linop/data/profile.template.toml)). Unknown keys and invalid values are errors. The owner's profile: [profiles/mrfedai.toml](profiles/mrfedai.toml).

## Platform status (honest)

| Platform | Status |
|---|---|
| Arch Linux | full scope; unit tested; container CI (real run) under investigation; native test on the owner's machine pending |
| Debian / Ubuntu | full scope (one provider); real `apply` + `rollback` pass in container CI on debian:stable and ubuntu:24.04 (packages, dconf, dotfiles, shell); one-line install verified on a fresh minimal Ubuntu 24.04 |
| Fedora | full scope; unit tested; container CI (real run) under investigation |
| Derivatives (EndeavourOS, CachyOS, Mint, Nobara, …) | run as their parent family, marked *experimental* |
| Windows, macOS | interfaces only — FAI_LinOP v3.0 changes nothing there |

Nothing has been run on real hardware yet (GPU drivers, monitors, Hyprland). Details and evidence: [docs/TESTING.md](docs/TESTING.md), [docs/PROGRESS.md](docs/PROGRESS.md).

## Coming from v2.5

Read [docs/MIGRATION.md](docs/MIGRATION.md). The v2.5 script is kept unchanged in `legacy/v2.5/` and at tag `v2.5.0`.

## Development

```bash
uv run pytest                                      # unit + characterization + golden tests
LINOP_REAL_RUN=1 uv run pytest tests/integration   # REAL installs — disposable container/VM only
python3 scripts/verify_catalog.py                  # check the package catalog on the current distro
```

Project rules and decisions: [CLAUDE.md](CLAUDE.md). Audit of v2.5: [docs/AUDIT.md](docs/AUDIT.md).

## License

MIT — see [LICENSE](LICENSE). Hyprland, Oh-My-Zsh, Starship and the other tools FAI_LinOP installs keep their own licences.
