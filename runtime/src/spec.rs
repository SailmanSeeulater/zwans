//! What to run and how tightly: the JSON object `zwans-jail` reads on stdin.
//!
//! ```json
//! {
//!   "argv": ["bash", "-c", "pytest -q"],
//!   "workspace": "/home/me/project",
//!   "cwd": "/home/me/project",
//!   "read_only": ["/usr", "/etc", "/opt/conda/envs/zwans"],
//!   "env": {"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
//!   "timeout_ms": 120000,
//!   "memory_mb": 2048,
//!   "max_processes": 256
//! }
//! ```
//!
//! The command sees the workspace read-write, the `read_only` paths read-only, and a fresh
//! /tmp, /dev and /proc. Nothing else of the machine exists for it, and it has no network.

use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Spec {
    pub argv: Vec<String>,
    pub workspace: PathBuf,
    /// Where the command starts; the workspace when left out.
    #[serde(default)]
    pub cwd: Option<PathBuf>,
    #[serde(default)]
    pub read_only: Vec<PathBuf>,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    /// The jail kills the command and everything it started after this long.
    #[serde(default)]
    pub timeout_ms: Option<u64>,
    #[serde(default = "default_memory_mb")]
    pub memory_mb: u64,
    #[serde(default = "default_max_processes")]
    pub max_processes: u64,
    /// The size of the private /tmp.
    #[serde(default = "default_tmp_mb")]
    pub tmp_mb: u64,
}

fn default_memory_mb() -> u64 {
    2048
}

fn default_max_processes() -> u64 {
    256
}

fn default_tmp_mb() -> u64 {
    1024
}

impl Spec {
    pub fn check(&self) -> Result<(), String> {
        if self.argv.is_empty() {
            return Err("argv is empty".into());
        }
        let absolute = |path: &PathBuf, what: &str| {
            if path.is_absolute() {
                Ok(())
            } else {
                Err(format!(
                    "{what} must be an absolute path: {}",
                    path.display()
                ))
            }
        };
        absolute(&self.workspace, "workspace")?;
        if let Some(cwd) = &self.cwd {
            absolute(cwd, "cwd")?;
        }
        for path in &self.read_only {
            absolute(path, "a read_only path")?;
        }
        if !self.workspace.is_dir() {
            return Err(format!(
                "the workspace isn't a folder: {}",
                self.workspace.display()
            ));
        }
        Ok(())
    }
}
