"""Auto-install approved pending Ratchet outputs into host project skills."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ratchet.client.feedback import archive_pending_items
from ratchet.client.pending import (
    PendingSkillInfo,
    PendingStrategyInfo,
    extract_skill_description,
    get_pending_skills,
    get_pending_strategies,
)
from ratchet.client.skill_utils import (
    DEFAULT_VERSION,
    RATCHET_AUTHOR_MARKER,
    get_author,
    parse_frontmatter,
    render_frontmatter,
    sanitize_name,
    skill_frontmatter_value,
    split_frontmatter,
)
from ratchet.client.stats import get_project_folder_name

HOST_SKILL_DIRS = {
    "claude": Path(".claude") / "skills",
    "codex": Path(".agents") / "skills",
}
MANAGED_MARKER = ".ratchet-managed.json"


@dataclass
class AutoInstallResult:
    """Summary of an auto-install attempt."""

    host: str
    project_dir: str
    installed_skills: list[str] = field(default_factory=list)
    installed_strategies: list[str] = field(default_factory=list)
    review_required: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    archived_run_id: str | None = None
    errors: list[str] = field(default_factory=list)


def _target_skill_dirs(project_dir: Path, current_host: str) -> dict[str, Path]:
    targets: dict[str, Path] = {}
    for host, rel_path in HOST_SKILL_DIRS.items():
        host_root = project_dir / rel_path.parts[0]
        if host == current_host or host_root.exists():
            target = project_dir / rel_path
            target.mkdir(parents=True, exist_ok=True)
            targets[host] = target
    return targets


def _approved_skill(skill: PendingSkillInfo) -> bool:
    return skill.safety_gate_status == "approved"


def _approved_strategy(strategy: PendingStrategyInfo) -> bool:
    return strategy.safety_gate_status == "approved"


def _is_ratchet_managed_destination(destination: Path) -> bool:
    marker = destination / MANAGED_MARKER
    if marker.is_file():
        return True

    skill_md = destination / "SKILL.md"
    if not skill_md.is_file():
        return False

    try:
        frontmatter = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except OSError:
        return False
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict) and metadata.get("ratchet_managed") is True:
        return True
    author = str(skill_frontmatter_value(frontmatter, "author", frontmatter.get("author", "")))
    return RATCHET_AUTHOR_MARKER in author


def _prepare_destination(destination: Path) -> None:
    if not destination.exists():
        return
    if not _is_ratchet_managed_destination(destination):
        raise FileExistsError(f"Refusing to overwrite non-Ratchet skill directory: {destination}")
    shutil.rmtree(destination)


def _write_managed_marker(destination: Path, *, kind: str, source_name: str) -> None:
    (destination / MANAGED_MARKER).write_text(
        json.dumps(
            {
                "managed_by": "ratchet",
                "kind": kind,
                "source_name": source_name,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _ensure_top_level_skill_fields(content: str, *, name: str, description: str) -> str:
    frontmatter, body = split_frontmatter(content)
    frontmatter = dict(frontmatter)
    frontmatter.setdefault("name", name)
    frontmatter.setdefault("description", description or f"Ratchet skill {name}")
    frontmatter.setdefault("allowed-tools", "Bash, Read")
    return render_frontmatter(frontmatter) + body


def _install_skill_tree(skill: PendingSkillInfo, target_root: Path) -> None:
    source = Path(skill.path)
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"Pending skill is missing SKILL.md: {source}")

    name = sanitize_name(skill.name)
    destination = target_root / name
    _prepare_destination(destination)
    shutil.copytree(source, destination)

    skill_md = destination / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    description = skill.description or extract_skill_description(content)
    skill_md.write_text(
        _ensure_top_level_skill_fields(content, name=name, description=description),
        encoding="utf-8",
    )
    _write_managed_marker(destination, kind="skill", source_name=skill.name)


def _strategy_skill_content(strategy: PendingStrategyInfo) -> tuple[str, str]:
    raw = Path(strategy.path).read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(raw)
    _fm, body = split_frontmatter(raw)
    name = sanitize_name(f"ratchet-strategy-{strategy.name}")
    title = strategy.description or strategy.name.replace("-", " ").title()
    metadata: dict[str, object] = {
        "author": strategy.author or get_author(),
        "version": strategy.version or DEFAULT_VERSION,
    }
    if strategy.tags:
        metadata["tags"] = strategy.tags
    skill_frontmatter = {
        "name": name,
        "description": f"Apply Ratchet strategy: {title}",
        "allowed-tools": "Read",
        "metadata": metadata,
    }
    if category := strategy.category or frontmatter.get("category"):
        skill_frontmatter["category"] = str(category)
    content = render_frontmatter(skill_frontmatter) + f"# {title}\n\n{body.strip()}\n"
    return name, content


def _install_strategy_skill(strategy: PendingStrategyInfo, target_root: Path) -> str:
    name, content = _strategy_skill_content(strategy)
    destination = target_root / name
    _prepare_destination(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "SKILL.md").write_text(content, encoding="utf-8")
    _write_managed_marker(destination, kind="strategy", source_name=strategy.name)
    return name


def auto_install_approved_pending(project_dir: Path, current_host: str) -> AutoInstallResult:
    """Install approved pending items for the current project and host."""
    current_host = current_host.lower()
    if current_host not in HOST_SKILL_DIRS:
        raise ValueError(f"Unsupported host: {current_host}")

    project_dir = project_dir.resolve()
    targets = _target_skill_dirs(project_dir, current_host)
    result = AutoInstallResult(
        host=current_host,
        project_dir=str(project_dir),
        targets=[str(path) for path in targets.values()],
    )

    skills = get_pending_skills()
    strategies = get_pending_strategies()
    approved_skills = [skill for skill in skills if _approved_skill(skill)]
    approved_strategies = [strategy for strategy in strategies if _approved_strategy(strategy)]
    review_required_skills = [skill for skill in skills if skill not in approved_skills]
    review_required_strategies = [strategy for strategy in strategies if strategy not in approved_strategies]
    result.review_required = [
        *[skill.name for skill in review_required_skills],
        *[strategy.name for strategy in review_required_strategies],
    ]

    installed_skill_infos: list[PendingSkillInfo] = []
    installed_strategy_infos: list[PendingStrategyInfo] = []

    for skill in approved_skills:
        try:
            for target in targets.values():
                _install_skill_tree(skill, target)
            result.installed_skills.append(skill.name)
            installed_skill_infos.append(skill)
        except Exception as exc:
            result.errors.append(f"{skill.name}: {exc}")

    for strategy in approved_strategies:
        try:
            installed_name = ""
            for target in targets.values():
                installed_name = _install_strategy_skill(strategy, target)
            result.installed_strategies.append(installed_name or strategy.name)
            installed_strategy_infos.append(strategy)
        except Exception as exc:
            result.errors.append(f"{strategy.name}: {exc}")

    if installed_skill_infos or installed_strategy_infos:
        run_id = f"auto-install-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        project_id = get_project_folder_name(str(project_dir))
        result.archived_run_id = archive_pending_items(
            run_id=run_id,
            project_id=project_id,
            installed_skills=installed_skill_infos,
            installed_strategies=installed_strategy_infos,
        )

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-install approved Ratchet pending outputs.")
    parser.add_argument("--host", choices=sorted(HOST_SKILL_DIRS), required=True)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = auto_install_approved_pending(Path(args.project_dir), args.host)
    if args.json:
        print(json.dumps(asdict(result), sort_keys=True))
    elif result.errors:
        for error in result.errors:
            print(error, file=sys.stderr)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
