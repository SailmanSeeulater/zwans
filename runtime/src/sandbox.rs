//! The sandbox: namespaces, a private filesystem, limits, then the command.
//!
//! Three processes:
//!
//! - **the jail** (this program) joins a fresh cgroup, unshares the user, PID, network, IPC
//!   and UTS namespaces, maps its own uid and gid into the new user namespace, and forks;
//! - **init**, PID 1 of the new PID namespace, unshares a mount namespace of its own, builds
//!   the new root and pivots into it, then forks the command and reaps every process until
//!   the command exits. Its exit takes everything else in the namespace with it;
//! - **the command**, which drops what it doesn't need (file descriptors, privileges) and
//!   locks itself down with resource limits, Landlock and seccomp before it execs.
//!
//! The jail waits for init, with the spec's timeout, and exits with the command's status:
//! its exit code, or 128 plus the signal that killed it, as a shell would report.

use crate::cgroup::Cgroup;
use crate::spec::Spec;
use crate::{landlock_rules, seccomp_filter};
use std::ffi::{CString, OsStr};
use std::fs;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{symlink, FileTypeExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The exit code when the jail itself fails, before the command runs.
pub const SETUP_FAILED: i32 = 125;

const DEVICES: [&str; 6] = ["null", "zero", "full", "random", "urandom", "tty"];

#[derive(Debug, Default, serde::Serialize)]
pub struct Stats {
    pub setup_ms: f64, // until the command was about to exec, as init saw it
    pub total_ms: f64,
    pub cgroup: bool,
    pub landlock_abi: i64, // 0 when the kernel doesn't have Landlock
    pub timed_out: bool,
    pub out_of_memory: bool,
    pub exit_code: i32,
}

pub fn run(spec: &Spec, stats: &mut Stats) -> Result<i32, String> {
    let started = Instant::now();
    let uid = unsafe { libc::getuid() };
    let gid = unsafe { libc::getgid() };
    let root = make_root_dir()?;
    let cgroup = Cgroup::create(spec.memory_mb, spec.max_processes).ok();
    stats.cgroup = cgroup.is_some();
    stats.landlock_abi = landlock_rules::abi_version();

    let flags = libc::CLONE_NEWUSER
        | libc::CLONE_NEWPID
        | libc::CLONE_NEWNET
        | libc::CLONE_NEWIPC
        | libc::CLONE_NEWUTS;
    check(unsafe { libc::unshare(flags) }, "unshare the namespaces")?;
    // A process may map only its own ids into a namespace it created, and only once it has
    // given up setgroups there.
    fs::write("/proc/self/setgroups", "deny").map_err(|e| format!("deny setgroups: {e}"))?;
    fs::write("/proc/self/uid_map", format!("{uid} {uid} 1"))
        .map_err(|e| format!("uid_map: {e}"))?;
    fs::write("/proc/self/gid_map", format!("{gid} {gid} 1"))
        .map_err(|e| format!("gid_map: {e}"))?;

    let (report_read, report_write) = pipe()?;
    let init = check(unsafe { libc::fork() }, "fork init")?;
    if init == 0 {
        unsafe { libc::close(report_read) };
        let code = match run_init(spec, &root, started, report_write) {
            Ok(code) => code,
            Err(message) => {
                eprintln!("zwans-jail: {message}");
                SETUP_FAILED
            }
        };
        unsafe { libc::_exit(code) };
    }
    unsafe { libc::close(report_write) };

    let timeout = spec.timeout_ms.map(Duration::from_millis);
    let (status, timed_out) = wait_for(init, timeout)?;
    stats.setup_ms = read_setup_ms(report_read);
    stats.timed_out = timed_out;
    if let Some(cgroup) = cgroup {
        stats.out_of_memory = cgroup.oom_killed();
        cgroup.remove();
    }
    // The root's tmpfs was mounted in init's mount namespace, so here it's an empty folder.
    let _ = fs::remove_dir(&root);
    stats.exit_code = status;
    stats.total_ms = started.elapsed().as_secs_f64() * 1000.0;
    if timed_out {
        eprintln!(
            "zwans-jail: stopped the command after {} ms",
            spec.timeout_ms.unwrap_or(0)
        );
    } else if stats.out_of_memory {
        eprintln!(
            "zwans-jail: the command ran out of memory ({} MB)",
            spec.memory_mb
        );
    }
    Ok(status)
}

// -- init: PID 1 of the sandbox

fn run_init(
    spec: &Spec,
    root: &Path,
    started: Instant,
    report: libc::c_int,
) -> Result<i32, String> {
    // If the jail dies (killed by Zwans after a timeout or Ctrl+C), so does init, and with it
    // everything in the PID namespace.
    check(
        unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) },
        "PR_SET_PDEATHSIG",
    )?;
    check(
        unsafe { libc::unshare(libc::CLONE_NEWNS) },
        "unshare the mount namespace",
    )?;
    let name = b"zwans-jail";
    check(
        unsafe { libc::sethostname(name.as_ptr().cast(), name.len()) },
        "sethostname",
    )?;
    build_root(spec, root)?;
    loopback_up();

    let setup_ms = started.elapsed().as_secs_f64() * 1000.0;
    let bytes = setup_ms.to_le_bytes();
    unsafe {
        libc::write(report, bytes.as_ptr().cast(), bytes.len());
        libc::close(report);
    }

    let command = check(unsafe { libc::fork() }, "fork the command")?;
    if command == 0 {
        let error = exec_command(spec);
        eprintln!("zwans-jail: {}: {error}", spec.argv[0]);
        unsafe {
            libc::_exit(if error.contains("not found") {
                127
            } else {
                126
            })
        };
    }

    // Reap everything (orphans included: init inherits them) until the command exits.
    let mut code = SETUP_FAILED;
    loop {
        let mut status = 0;
        let pid = unsafe { libc::waitpid(-1, &mut status, 0) };
        if pid == command {
            code = decode(status);
            break;
        }
        if pid == -1 && io::Error::last_os_error().raw_os_error() != Some(libc::EINTR) {
            break;
        }
    }
    // Whatever the command left running in the background goes with it.
    unsafe { libc::kill(-1, libc::SIGKILL) };
    Ok(code)
}

fn decode(status: libc::c_int) -> i32 {
    if libc::WIFEXITED(status) {
        libc::WEXITSTATUS(status)
    } else if libc::WIFSIGNALED(status) {
        128 + libc::WTERMSIG(status)
    } else {
        SETUP_FAILED
    }
}

// -- the filesystem

/// The new root: an empty tmpfs with the read-only paths, the workspace, and fresh /tmp,
/// /dev and /proc mounted in it. Everything else of the machine is left behind.
fn build_root(spec: &Spec, root: &Path) -> Result<(), String> {
    // Keep these mounts from leaking back into the jail's namespace, and the other way.
    mount(
        None,
        Path::new("/"),
        None,
        libc::MS_REC | libc::MS_PRIVATE,
        None,
    )?;
    mount(
        Some("tmpfs"),
        root,
        Some("tmpfs"),
        libc::MS_NOSUID | libc::MS_NODEV,
        Some("mode=0755,size=16m"),
    )?;

    let tmp = inside(root, Path::new("/tmp"));
    mkdir_p(&tmp)?;
    let tmp_options = format!("mode=1777,size={}m", spec.tmp_mb);
    mount(
        Some("tmpfs"),
        &tmp,
        Some("tmpfs"),
        libc::MS_NOSUID | libc::MS_NODEV,
        Some(&tmp_options),
    )?;

    build_dev(root)?;

    let mut read_only: Vec<&PathBuf> = spec.read_only.iter().collect();
    read_only.sort_by_key(|p| p.components().count()); // parents before what's inside them
    read_only.dedup();
    for path in read_only {
        if path.starts_with(&spec.workspace)
            || !path.exists() && fs::symlink_metadata(path).is_err()
        {
            continue; // the workspace is mounted read-write below; missing paths are skipped
        }
        bind(path, &inside(root, path), true)?;
    }
    bind(&spec.workspace, &inside(root, &spec.workspace), false)?;

    let proc_dir = inside(root, Path::new("/proc"));
    mkdir_p(&proc_dir)?;
    // This proc shows only the sandbox's processes: init is PID 1 of its own namespace.
    mount(
        Some("proc"),
        &proc_dir,
        Some("proc"),
        libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC,
        None,
    )?;

    let old = root.join(".old-root");
    mkdir_p(&old)?;
    let new_root = cstring(root.as_os_str())?;
    let put_old = cstring(old.as_os_str())?;
    check(
        unsafe { libc::syscall(libc::SYS_pivot_root, new_root.as_ptr(), put_old.as_ptr()) }
            as libc::c_int,
        "pivot_root",
    )?;
    check(unsafe { libc::chdir(c"/".as_ptr()) }, "chdir /")?;
    check(
        unsafe { libc::umount2(c"/.old-root".as_ptr(), libc::MNT_DETACH) },
        "detach the old root",
    )?;
    fs::remove_dir("/.old-root").map_err(|e| format!("remove /.old-root: {e}"))?;
    // Nothing may be created at the top level; /tmp and the workspace are mounts of their own.
    let flags =
        libc::MS_REMOUNT | libc::MS_BIND | libc::MS_RDONLY | libc::MS_NOSUID | libc::MS_NODEV;
    mount(None, Path::new("/"), None, flags, None)
}

fn build_dev(root: &Path) -> Result<(), String> {
    let dev = inside(root, Path::new("/dev"));
    mkdir_p(&dev)?;
    mount(
        Some("tmpfs"),
        &dev,
        Some("tmpfs"),
        libc::MS_NOSUID,
        Some("mode=0755,size=1m"),
    )?;
    for name in DEVICES {
        let host = Path::new("/dev").join(name);
        match fs::metadata(&host) {
            Ok(meta) if meta.file_type().is_char_device() => {
                let target = dev.join(name);
                fs::write(&target, b"").map_err(|e| format!("create {}: {e}", target.display()))?;
                mount(
                    Some(&host.to_string_lossy()),
                    &target,
                    None,
                    libc::MS_BIND,
                    None,
                )?;
            }
            _ => continue, // no tty when Zwans runs without a terminal, say
        }
    }
    for (link, target) in [
        ("fd", "/proc/self/fd"),
        ("stdin", "/proc/self/fd/0"),
        ("stdout", "/proc/self/fd/1"),
        ("stderr", "/proc/self/fd/2"),
    ] {
        symlink(target, dev.join(link)).map_err(|e| format!("link /dev/{link}: {e}"))?;
    }
    let shm = dev.join("shm");
    mkdir_p(&shm)?;
    mount(
        Some("tmpfs"),
        &shm,
        Some("tmpfs"),
        libc::MS_NOSUID | libc::MS_NODEV,
        Some("mode=1777,size=64m"),
    )
}

/// Mount `source` at `target`. A symlink, like /bin -> usr/bin on most distributions, is
/// copied as a symlink, so it keeps pointing inside the new root.
fn bind(source: &Path, target: &Path, read_only: bool) -> Result<(), String> {
    let meta = fs::symlink_metadata(source).map_err(|e| format!("{}: {e}", source.display()))?;
    if meta.file_type().is_symlink() {
        let points_to = fs::read_link(source).map_err(|e| format!("{}: {e}", source.display()))?;
        if let Some(parent) = target.parent() {
            mkdir_p(parent)?;
        }
        return symlink(&points_to, target).map_err(|e| format!("link {}: {e}", target.display()));
    }
    if meta.is_dir() {
        mkdir_p(target)?;
    } else {
        if let Some(parent) = target.parent() {
            mkdir_p(parent)?;
        }
        fs::write(target, b"").map_err(|e| format!("create {}: {e}", target.display()))?;
    }
    let source_text = source.to_string_lossy();
    mount(
        Some(&source_text),
        target,
        None,
        libc::MS_BIND | libc::MS_REC,
        None,
    )?;
    if read_only {
        // A remount in a user namespace must keep the flags the original mount was locked
        // with (nosuid, nodev, noexec, the atime ones), or the kernel refuses it.
        let flags = libc::MS_BIND | libc::MS_REMOUNT | libc::MS_RDONLY | locked_flags(target)?;
        mount(None, target, None, flags, None)?;
    }
    Ok(())
}

fn locked_flags(path: &Path) -> Result<libc::c_ulong, String> {
    let c_path = cstring(path.as_os_str())?;
    let mut info: libc::statvfs = unsafe { std::mem::zeroed() };
    check(
        unsafe { libc::statvfs(c_path.as_ptr(), &mut info) },
        "statvfs",
    )?;
    let mut flags = 0;
    for (st, ms) in [
        (libc::ST_NOSUID, libc::MS_NOSUID),
        (libc::ST_NODEV, libc::MS_NODEV),
        (libc::ST_NOEXEC, libc::MS_NOEXEC),
        (libc::ST_NOATIME, libc::MS_NOATIME),
        (libc::ST_NODIRATIME, libc::MS_NODIRATIME),
        (libc::ST_RELATIME, libc::MS_RELATIME),
    ] {
        if info.f_flag & st != 0 {
            flags |= ms;
        }
    }
    Ok(flags)
}

/// The network namespace starts with only a loopback interface, and it's down. Bring it up,
/// so a test that starts a server on localhost works; nothing leads out of the namespace.
fn loopback_up() {
    unsafe {
        let sock = libc::socket(libc::AF_INET, libc::SOCK_DGRAM | libc::SOCK_CLOEXEC, 0);
        if sock < 0 {
            return;
        }
        let mut request: libc::ifreq = std::mem::zeroed();
        for (i, byte) in b"lo".iter().enumerate() {
            request.ifr_name[i] = *byte as libc::c_char;
        }
        if libc::ioctl(sock, libc::SIOCGIFFLAGS, &mut request) == 0 {
            request.ifr_ifru.ifru_flags |= libc::IFF_UP as libc::c_short;
            libc::ioctl(sock, libc::SIOCSIFFLAGS, &request);
        }
        libc::close(sock);
    }
}

// -- the command

/// Lock the process down and exec the command. Returns only on failure, with why.
fn exec_command(spec: &Spec) -> String {
    match prepare(spec) {
        Ok((path, argv, env)) => {
            let argv_ptrs = pointers(&argv);
            let env_ptrs = pointers(&env);
            unsafe { libc::execve(path.as_ptr(), argv_ptrs.as_ptr(), env_ptrs.as_ptr()) };
            io::Error::last_os_error().to_string()
        }
        Err(message) => message,
    }
}

fn prepare(spec: &Spec) -> Result<(CString, Vec<CString>, Vec<CString>), String> {
    unsafe {
        // Its own session, so it has no terminal to reach back through.
        libc::setsid();
        let null = libc::open(c"/dev/null".as_ptr(), libc::O_RDONLY);
        if null >= 0 {
            libc::dup2(null, 0);
        }
        libc::dup2(1, 2); // stdout and stderr together, as Zwans reads them
    }
    close_other_fds();
    let cwd = spec.cwd.as_ref().unwrap_or(&spec.workspace);
    let c_cwd = cstring(cwd.as_os_str())?;
    check(
        unsafe { libc::chdir(c_cwd.as_ptr()) },
        "chdir to the working folder",
    )?;

    limit(libc::RLIMIT_NPROC, spec.max_processes)?;
    limit(libc::RLIMIT_CORE, 0)?;
    // Counts private writable memory, unlike RLIMIT_AS, which stops V8 and Go, as they
    // reserve far more address space than they use. A backstop for when cgroups aren't there.
    limit(libc::RLIMIT_DATA, spec.memory_mb.saturating_mul(1 << 20))?;

    check(
        unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) },
        "PR_SET_NO_NEW_PRIVS",
    )?;
    landlock_rules::restrict(&spec.workspace)?;
    let path = resolve(&spec.argv[0], spec.env.get("PATH").map(String::as_str))?;
    let argv = spec
        .argv
        .iter()
        .map(|a| cstring(OsStr::new(a)))
        .collect::<Result<Vec<_>, _>>()?;
    let env = spec
        .env
        .iter()
        .map(|(k, v)| cstring(OsStr::new(&format!("{k}={v}"))))
        .collect::<Result<Vec<_>, _>>()?;
    // Last, so nothing above is limited by it. execve itself is on the allowlist.
    seccomp_filter::load()?;
    Ok((cstring(path.as_os_str())?, argv, env))
}

fn limit(resource: libc::__rlimit_resource_t, value: u64) -> Result<(), String> {
    let rlim = libc::rlimit {
        rlim_cur: value,
        rlim_max: value,
    };
    check(unsafe { libc::setrlimit(resource, &rlim) }, "setrlimit")?;
    Ok(())
}

/// Find a program on the command's own PATH, as a shell would.
fn resolve(program: &str, path: Option<&str>) -> Result<PathBuf, String> {
    if program.contains('/') {
        return Ok(PathBuf::from(program));
    }
    for dir in path
        .unwrap_or("/usr/bin:/bin")
        .split(':')
        .filter(|d| !d.is_empty())
    {
        let candidate = Path::new(dir).join(program);
        if is_executable(&candidate) {
            return Ok(candidate);
        }
    }
    Err("command not found".into())
}

fn is_executable(path: &Path) -> bool {
    match cstring(path.as_os_str()) {
        Ok(c) => path.is_file() && unsafe { libc::access(c.as_ptr(), libc::X_OK) } == 0,
        Err(_) => false,
    }
}

/// Close every inherited file descriptor except stdin, stdout and stderr, so nothing the
/// jail's caller had open (a socket, a file outside the sandbox) is reachable from inside.
fn close_other_fds() {
    let closed = unsafe { libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32) };
    if closed == 0 {
        return;
    }
    if let Ok(entries) = fs::read_dir("/proc/self/fd") {
        let fds: Vec<i32> = entries
            .filter_map(|e| e.ok()?.file_name().to_str()?.parse().ok())
            .collect();
        for fd in fds.into_iter().filter(|fd| *fd > 2) {
            unsafe { libc::close(fd) };
        }
    }
}

// -- small helpers

fn make_root_dir() -> Result<PathBuf, String> {
    let mut template = b"/tmp/zwans-jail-XXXXXX\0".to_vec();
    let made = unsafe { libc::mkdtemp(template.as_mut_ptr().cast()) };
    if made.is_null() {
        return Err(format!(
            "make the root folder: {}",
            io::Error::last_os_error()
        ));
    }
    template.pop();
    Ok(PathBuf::from(OsStr::from_bytes(&template)))
}

fn inside(root: &Path, path: &Path) -> PathBuf {
    root.join(path.strip_prefix("/").unwrap_or(path))
}

fn mkdir_p(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|e| format!("create {}: {e}", path.display()))
}

fn mount(
    source: Option<&str>,
    target: &Path,
    fstype: Option<&str>,
    flags: libc::c_ulong,
    data: Option<&str>,
) -> Result<(), String> {
    let c_source = source.map(|s| cstring(OsStr::new(s))).transpose()?;
    let c_target = cstring(target.as_os_str())?;
    let c_fstype = fstype.map(|s| cstring(OsStr::new(s))).transpose()?;
    let c_data = data.map(|s| cstring(OsStr::new(s))).transpose()?;
    let ptr = |c: &Option<CString>| c.as_ref().map_or(std::ptr::null(), |c| c.as_ptr());
    let result = unsafe {
        libc::mount(
            ptr(&c_source),
            c_target.as_ptr(),
            ptr(&c_fstype),
            flags,
            ptr(&c_data).cast(),
        )
    };
    check(result, &format!("mount {}", target.display())).map(|_| ())
}

fn cstring(value: &OsStr) -> Result<CString, String> {
    CString::new(value.as_bytes()).map_err(|_| format!("{value:?} contains a NUL byte"))
}

fn pointers(values: &[CString]) -> Vec<*const libc::c_char> {
    values
        .iter()
        .map(|v| v.as_ptr())
        .chain(std::iter::once(std::ptr::null()))
        .collect()
}

fn pipe() -> Result<(libc::c_int, libc::c_int), String> {
    let mut fds = [0; 2];
    check(
        unsafe { libc::pipe2(fds.as_mut_ptr(), libc::O_CLOEXEC) },
        "pipe",
    )?;
    Ok((fds[0], fds[1]))
}

fn read_setup_ms(fd: libc::c_int) -> f64 {
    let mut bytes = [0u8; 8];
    let read = unsafe { libc::read(fd, bytes.as_mut_ptr().cast(), bytes.len()) };
    unsafe { libc::close(fd) };
    if read == 8 {
        f64::from_le_bytes(bytes)
    } else {
        0.0
    }
}

/// Wait for init, killing it (and so the whole sandbox) when the timeout passes. Returns
/// the command's status and whether it timed out.
fn wait_for(init: libc::pid_t, timeout: Option<Duration>) -> Result<(i32, bool), String> {
    let pidfd = unsafe { libc::syscall(libc::SYS_pidfd_open, init, 0) } as libc::c_int;
    let mut timed_out = false;
    if pidfd >= 0 {
        let mut poll = libc::pollfd {
            fd: pidfd,
            events: libc::POLLIN,
            revents: 0,
        };
        let deadline = timeout.map(|t| Instant::now() + t);
        loop {
            let wait_ms = match deadline {
                Some(deadline) => deadline
                    .saturating_duration_since(Instant::now())
                    .as_millis() as i32,
                None => -1,
            };
            let ready = unsafe { libc::poll(&mut poll, 1, wait_ms) };
            if ready > 0 {
                break;
            }
            if ready == 0 {
                timed_out = true;
                unsafe { libc::kill(init, libc::SIGKILL) };
                break;
            }
            if io::Error::last_os_error().raw_os_error() != Some(libc::EINTR) {
                break;
            }
        }
        unsafe { libc::close(pidfd) };
    }
    let mut status = 0;
    loop {
        let pid = unsafe { libc::waitpid(init, &mut status, 0) };
        if pid == init {
            break;
        }
        if io::Error::last_os_error().raw_os_error() != Some(libc::EINTR) {
            return Err(format!(
                "wait for the sandbox: {}",
                io::Error::last_os_error()
            ));
        }
    }
    let code = if timed_out {
        128 + libc::SIGKILL
    } else {
        decode(status)
    };
    Ok((code, timed_out))
}

fn check<T: Into<i64> + Copy>(result: T, what: &str) -> Result<T, String> {
    if result.into() == -1 {
        Err(format!("{what}: {}", io::Error::last_os_error()))
    } else {
        Ok(result)
    }
}
