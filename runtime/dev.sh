#!/usr/bin/env bash
# Run a command in the Linux dev container, with this repo at /work. For example:
#   runtime/dev.sh cargo build --release --manifest-path runtime/Cargo.toml
#   runtime/dev.sh pytest -q tests/test_jail.py
# Docker's own seccomp and AppArmor profiles are lifted so the jail can create namespaces,
# and /proc is left unmasked so it can mount a fresh one (the kernel allows that only where
# /proc is fully visible), as on an ordinary Linux machine. The container still runs as an
# unprivileged user.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
exec docker run --rm -i \
    --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined \
    -v "$repo:/work" -v zwans-jail-target:/target \
    -e CARGO_HOME=/target/cargo-home -e ZWANS_JAIL=/target/release/zwans-jail \
    zwans-jail-dev "$@"
