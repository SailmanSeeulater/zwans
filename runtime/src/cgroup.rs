//! A cgroup for one sandbox, with memory and process limits, when the machine lets this
//! user make one.
//!
//! cgroup v2 only allows that inside a subtree delegated to the user, which systemd gives
//! each desktop login (user@<uid>.service) but containers and CI runners often don't. When
//! it isn't possible, the jail falls back to resource limits (RLIMIT_DATA, RLIMIT_NPROC),
//! which are coarser but always available, and says so in its stats.

use std::fs;
use std::path::{Path, PathBuf};

const ROOT: &str = "/sys/fs/cgroup";

pub struct Cgroup {
    path: PathBuf,
    original: PathBuf, // where the jail was, to go back to before removing this one
}

impl Cgroup {
    /// Make a cgroup next to the jail's own and move the jail into it, so the sandbox it
    /// forks starts inside. Next to it, not under it: a cgroup with processes of its own
    /// can't also have children with limits.
    pub fn create(memory_mb: u64, max_processes: u64) -> Result<Self, String> {
        let membership = fs::read_to_string("/proc/self/cgroup").map_err(|e| e.to_string())?;
        let relative = membership
            .lines()
            .find_map(|line| line.strip_prefix("0::"))
            .ok_or("not on cgroup v2")?;
        let original = Path::new(ROOT).join(relative.trim_start_matches('/'));
        let parent = original.parent().ok_or("at the cgroup root")?;
        let path = parent.join(format!("zwans-jail-{}", std::process::id()));
        fs::create_dir(&path).map_err(|e| format!("create {}: {e}", path.display()))?;
        let cgroup = Cgroup { path, original };
        if let Err(message) = cgroup.configure(memory_mb, max_processes) {
            let _ = fs::remove_dir(&cgroup.path);
            return Err(message);
        }
        Ok(cgroup)
    }

    fn configure(&self, memory_mb: u64, max_processes: u64) -> Result<(), String> {
        self.write("memory.max", &(memory_mb << 20).to_string())?;
        let _ = self.write("memory.swap.max", "0"); // not every kernel has swap accounting
        self.write("pids.max", &max_processes.to_string())?;
        self.write("cgroup.procs", &std::process::id().to_string())
    }

    fn write(&self, file: &str, value: &str) -> Result<(), String> {
        fs::write(self.path.join(file), value).map_err(|e| format!("{file}: {e}"))
    }

    /// Whether the kernel killed something in the sandbox for going over memory.max.
    pub fn oom_killed(&self) -> bool {
        fs::read_to_string(self.path.join("memory.events"))
            .ok()
            .and_then(|events| {
                events
                    .lines()
                    .find_map(|line| line.strip_prefix("oom_kill "))
                    .and_then(|n| n.trim().parse::<u64>().ok())
            })
            .is_some_and(|n| n > 0)
    }

    pub fn remove(self) {
        let _ = fs::write(
            self.original.join("cgroup.procs"),
            std::process::id().to_string(),
        );
        // The sandbox's processes are gone once init has been reaped, but the kernel can take
        // a moment to notice.
        for _ in 0..50 {
            if fs::remove_dir(&self.path).is_ok() {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    }
}
