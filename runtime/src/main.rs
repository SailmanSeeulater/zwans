//! `zwans-jail`: run one command in a sandbox.
//!
//! Reads a JSON spec on stdin (see spec.rs), runs the command with its output (stdout and
//! stderr together) on stdout, and exits with its exit code, or 128 plus the signal that
//! killed it. The jail's own messages go to stderr and start with "zwans-jail:"; if it can't
//! build the sandbox it exits with 125 before running anything.
//!
//!     zwans-jail [--stats] < spec.json
//!
//! --stats prints a JSON line of timings and what the kernel allowed to stderr at the end.

mod spec;

#[cfg(target_os = "linux")]
mod cgroup;
#[cfg(target_os = "linux")]
mod landlock_rules;
#[cfg(target_os = "linux")]
mod sandbox;
#[cfg(target_os = "linux")]
mod seccomp_filter;

use std::io::Read;

const SETUP_FAILED: i32 = 125;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--version") {
        println!("zwans-jail {}", env!("CARGO_PKG_VERSION"));
        return;
    }
    let stats = args.iter().any(|a| a == "--stats");
    if let Some(unknown) = args.iter().find(|a| *a != "--stats") {
        fail(&format!(
            "unknown argument {unknown}; usage: zwans-jail [--stats] < spec.json"
        ));
    }
    let mut input = String::new();
    if let Err(e) = std::io::stdin().read_to_string(&mut input) {
        fail(&format!("read the spec: {e}"));
    }
    let spec: spec::Spec = match serde_json::from_str(&input) {
        Ok(spec) => spec,
        Err(e) => fail(&format!("the spec isn't valid: {e}")),
    };
    if let Err(message) = spec.check() {
        fail(&message);
    }
    std::process::exit(run(&spec, stats));
}

#[cfg(target_os = "linux")]
fn run(spec: &spec::Spec, show_stats: bool) -> i32 {
    let mut stats = sandbox::Stats::default();
    let code = match sandbox::run(spec, &mut stats) {
        Ok(code) => code,
        Err(message) => fail(&message),
    };
    if show_stats {
        eprintln!("{}", serde_json::to_string(&stats).unwrap_or_default());
    }
    code
}

#[cfg(not(target_os = "linux"))]
fn run(_spec: &spec::Spec, _show_stats: bool) -> i32 {
    fail("the jail needs Linux (namespaces, cgroups v2, seccomp, Landlock)")
}

fn fail(message: &str) -> ! {
    eprintln!("zwans-jail: {message}");
    std::process::exit(SETUP_FAILED)
}
