import asyncio
from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor
from zwans.ext.skills import find_skills, skill_folders, split_front_matter
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy
from zwans.prompt import system_prompt
from zwans.tools.base import ToolContext, ToolError
from zwans.tools.skill import SkillInput, SkillTool


def write_skill(root: Path, folder: str, front: str, body: str = "Do the thing.") -> Path:
    path = root / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")
    return path.parent


def test_front_matter_is_split_from_the_instructions() -> None:
    fields, rest = split_front_matter(
        "---\nname: notes\ndescription: 'Write notes: short ones.'\n---\n# Notes\nBe brief.\n"
    )
    assert fields == {"name": "notes", "description": "Write notes: short ones."}
    assert rest == "# Notes\nBe brief."
    assert split_front_matter("No front matter.") == ({}, "No front matter.")


def test_skills_are_found_and_a_projects_skill_wins_over_the_users(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    write_skill(home / "skills", "release", "description: The user's release notes.")
    write_skill(home / "skills", "review", "name: code-review\ndescription: Review a diff.")
    write_skill(home / "skills", "nameless", "name: no-description")
    write_skill(workspace / ".zwans" / "skills", "release", "description: The project's.")

    skills = find_skills(skill_folders(workspace, home))

    described = {skill.name: skill.description for skill in skills}
    assert described == {"release": "The project's.", "code-review": "Review a diff."}


def test_only_names_and_descriptions_go_in_the_system_prompt(tmp_path: Path) -> None:
    write_skill(tmp_path, "release", "description: Write release notes.", body="SECRET STEPS")
    skills = find_skills([tmp_path])

    prompt = system_prompt(tmp_path, "bash", [], skills=skills)

    assert "- release: Write release notes." in prompt
    assert "SECRET STEPS" not in prompt
    assert "Skill tool" not in system_prompt(tmp_path, "bash", [])


def run_skill(tool: SkillTool, tmp_path: Path, **args: str) -> str:
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    return asyncio.run(tool.run(SkillInput.model_validate(args), ctx)).content


def test_the_skill_tool_loads_instructions_and_lists_other_files(tmp_path: Path) -> None:
    folder = write_skill(tmp_path / "skills", "release", "description: Notes.", "Use the template.")
    (folder / "template.md").write_text("## Changes\n", encoding="utf-8")
    tool = SkillTool(find_skills([tmp_path / "skills"]))

    loaded = run_skill(tool, tmp_path, name="release")

    assert loaded.startswith("Use the template.")
    assert "description" not in loaded
    assert "- template.md" in loaded
    assert run_skill(tool, tmp_path, name="release", file="template.md") == "## Changes\n"


def test_the_skill_tool_refuses_unknown_skills_and_files_outside_the_folder(
    tmp_path: Path,
) -> None:
    write_skill(tmp_path / "skills", "release", "description: Notes.")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    tool = SkillTool(find_skills([tmp_path / "skills"]))

    with pytest.raises(ToolError, match="Skills: release"):
        run_skill(tool, tmp_path, name="deploy")
    with pytest.raises(PermissionError):
        run_skill(tool, tmp_path, name="release", file="../../secret.txt")


def test_loading_a_skill_needs_no_approval_but_counts_as_untrusted(tmp_path: Path) -> None:
    executor = LocalExecutor(tmp_path)
    perms = Permissions(Policy.default(), executor.contains, executor.relative)
    tool = SkillTool([])

    assert perms.check(tool, {"name": "x"}).decision == Decision.ALLOW
    assert perms.observe(tool.name, is_error=False)
    assert perms.tainted
