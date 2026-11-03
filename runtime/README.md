# zwans-jail

Zwans's own sandbox: runs one command with only the workspace and the system folders it
needs, no network, and limits on memory and processes. It needs Linux (or WSL2); the
Python side is `src/zwans/executor/jail.py`, and `executor = "jail"` turns it on.

```bash
cargo build --release --manifest-path runtime/Cargo.toml   # needs libseccomp-dev
echo '{"argv": ["ls", "/"], "workspace": "'$PWD'", "read_only": ["/usr", "/bin", "/lib", "/etc"]}' \
    | runtime/target/release/zwans-jail --stats
```

## What it does

Each command gets a fresh sandbox, made in this order:

1. **cgroup.** The jail makes a cgroup with `memory.max` and `pids.max` and moves into it,
   if this user has a delegated cgroup subtree (systemd gives one to every desktop login).
   Otherwise it relies on resource limits alone, and `--stats` says `"cgroup": false`.
2. **Namespaces.** It unshares the user, PID, network, IPC and UTS namespaces and maps its
   own uid and gid into the new user namespace, then forks the sandbox's PID 1.
3. **Filesystem.** PID 1 unshares a mount namespace and builds a new root on an empty
   tmpfs: the `read_only` paths bind-mounted read-only, the workspace read-write at the
   same path, a fresh /tmp, a /dev with only null, zero, full, random, urandom and tty, and
   a /proc that shows only the sandbox's processes. It pivots into it, detaches the old
   root, and makes the top level read-only.
4. **Network.** The network namespace has a loopback interface (brought up, so tests can
   use localhost) and nothing else, so nothing leaves the machine.
5. **The command.** PID 1 forks it, and the command closes every inherited file descriptor
   but stdin, stdout and stderr, sets `RLIMIT_NPROC`, `RLIMIT_DATA` and `RLIMIT_CORE`, sets
   `no_new_privs`, applies Landlock rules (read everything visible; write only the
   workspace, /tmp and /dev), loads a seccomp allowlist, and execs.
6. **The end.** When the command exits, PID 1 kills whatever it left running and exits,
   which takes everything left in the PID namespace with it. If the jail itself is killed
   (Zwans's timeout or Ctrl+C), PID 1 gets SIGKILL from the kernel (`PR_SET_PDEATHSIG`)
   with the same effect.

The command's stdout and stderr come out together on the jail's stdout; the jail exits with
its exit code, or 128 plus the signal that killed it. The jail's own messages go to stderr
and start with `zwans-jail:`; if it can't build the sandbox it exits with 125.

## The seccomp allowlist

`src/seccomp_filter.rs` allows what Docker's default profile allows, minus what reaches
past a sandbox: `ptrace` and `process_vm_*`, `mount` and the new mount API, `unshare`,
`setns` and `clone` with namespace flags, `bpf`, `perf_event_open`, keyrings, module
loading, `kexec`, `reboot`, `io_uring`, `userfaultfd`, `open_by_handle_at`, and setting
the clock. Anything else fails with EPERM. `clone3` fails with ENOSYS, because seccomp can't
read its flags, and the C library falls back to `clone`.

## Developing on a Mac or Windows

`runtime/dev.sh` runs a command in a Linux container (built from `Dockerfile.dev`) with the
repo at `/work`, as an unprivileged user:

```bash
docker build -t zwans-jail-dev -f runtime/Dockerfile.dev runtime
runtime/dev.sh cargo build --release --manifest-path runtime/Cargo.toml
runtime/dev.sh pytest -q tests/test_jail.py      # the escape suite
runtime/dev.sh python3 runtime/bench.py jail     # startup time
```

The container lifts Docker's own seccomp and AppArmor profiles and leaves /proc unmasked,
which the jail needs to make namespaces and mount a fresh /proc, as it can on an ordinary
Linux machine. It can't delegate a cgroup, so limits there come from resource limits.

## Measured

On Docker Desktop's Linux VM (kernel 7.0, arm64), 50 runs of `true`:

| Sandbox | Median | p95 |
|---|---|---|
| zwans-jail, a fresh sandbox | 2.5 ms | 3.3 ms |
| zwans-jail, setup only | 1.0 ms | 1.4 ms |
| `docker exec` into a running container | 26.9 ms | 34.5 ms |
| `docker run`, a fresh container | 121.8 ms | 140.2 ms |

The Docker numbers were taken from the Mac, so they include Docker Desktop's trip into its
VM; CI runs both on the same Linux machine (the `jail` job).
