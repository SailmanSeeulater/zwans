//! Landlock: the kernel's own say on which paths the command may touch, a second line
//! behind the mount namespace. Everything visible can be read; only the workspace, /tmp and
//! /dev can be written. On a kernel without Landlock this does nothing, and the jail's stats
//! say so (landlock_abi 0).

use landlock::{
    path_beneath_rules, Access, AccessFs, Ruleset, RulesetAttr, RulesetCreatedAttr, ABI,
};
use std::path::Path;

const ABI_USED: ABI = ABI::V3;
const CREATE_RULESET_VERSION: libc::c_uint = 1;

pub fn restrict(workspace: &Path) -> Result<(), String> {
    let writable = [workspace, Path::new("/tmp"), Path::new("/dev")];
    Ruleset::default()
        .handle_access(AccessFs::from_all(ABI_USED))
        .and_then(|ruleset| ruleset.create())
        .and_then(|ruleset| {
            ruleset.add_rules(path_beneath_rules(["/"], AccessFs::from_read(ABI_USED)))
        })
        .and_then(|ruleset| {
            ruleset.add_rules(path_beneath_rules(writable, AccessFs::from_all(ABI_USED)))
        })
        .and_then(|ruleset| ruleset.restrict_self())
        .map(|_| ())
        .map_err(|e| format!("Landlock: {e}"))
}

/// The Landlock ABI this kernel speaks, or 0 without Landlock.
pub fn abi_version() -> i64 {
    let version = unsafe {
        libc::syscall(
            libc::SYS_landlock_create_ruleset,
            std::ptr::null::<libc::c_void>(),
            0usize,
            CREATE_RULESET_VERSION,
        )
    };
    version.max(0)
}
