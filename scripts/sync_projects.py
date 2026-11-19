#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


STATE_FILE = ".codex-global-state.json"
PROJECT_ID_MAP = "app-server-project-id-by-legacy-project-id-by-host"


def restore_metadata(source, target, source_home, target_home, server_project_ids):
    result = dict(target)
    for key in (
        "local-projects",
        "project-appearances",
        "sidebar-project-thread-orders",
        "thread-project-membership-host-ids",
        "thread-workspace-root-hints",
    ):
        if key in source:
            result[key] = {**target.get(key, {}), **source[key]}

    for key in ("project-order", "electron-saved-workspace-roots", "projectless-thread-ids"):
        if key in source:
            result[key] = list(dict.fromkeys([*source[key], *target.get(key, [])]))

    projects = result.get("local-projects", {})
    assignments = {
        thread_id: assignment
        for thread_id, assignment in source.get("thread-project-assignments", {}).items()
        if assignment.get("projectKind") == "local" and assignment.get("projectId") in projects
    }
    result["thread-project-assignments"] = {
        **target.get("thread-project-assignments", {}),
        **assignments,
    }
    if "projectless-thread-ids" in result:
        result["projectless-thread-ids"] = [
            thread_id for thread_id in result["projectless-thread-ids"]
            if thread_id not in result["thread-project-assignments"]
        ]

    source_map = source.get(PROJECT_ID_MAP, {}).get(f"local:{source_home}", {})
    target_maps = target.get(PROJECT_ID_MAP, {})
    target_host = f"local:{target_home}"
    existing_ids = {
        old_id: new_id for old_id, new_id in source_map.items()
        if old_id in projects and new_id in server_project_ids
    }
    result[PROJECT_ID_MAP] = {
        **target_maps,
        target_host: {**target_maps.get(target_host, {}), **existing_ids},
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Sync local Codex projects between local profiles.")
    parser.add_argument("--source-home", type=Path, required=True, help="Source Codex home.")
    parser.add_argument("--target-home", type=Path, required=True, help="Destination Codex home.")
    parser.add_argument("--database", type=Path, required=True, help="Shared state SQLite database.")
    parser.add_argument("--apply", action="store_true", help="Write the result after both apps have quit.")
    args = parser.parse_args()
    source_home = args.source_home.expanduser().resolve()
    target_home = args.target_home.expanduser().resolve()
    direction = f"{source_home.name} -> {target_home.name}"
    if source_home.resolve() == target_home.resolve():
        parser.error("Источник и назначение должны быть разными профилями.")
    if args.apply:
        processes = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True).splitlines()
        if any(line.strip().endswith(("/Contents/MacOS/ChatGPT", "/Contents/MacOS/Codex")) for line in processes):
            parser.exit(1, "Сначала полностью закрой оба окна ChatGPT/Codex через ⌘Q.\n")

    source_path, path = source_home / STATE_FILE, target_home / STATE_FILE
    if any(state.is_symlink() or not state.is_file() for state in (source_path, path)):
        parser.exit(1, "Ожидались отдельные файлы настроек двух профилей.\n")
    primary_db = args.database.expanduser().resolve()
    if not primary_db.is_file() or any(
        not (profile / primary_db.name).is_file()
        or (profile / primary_db.name).resolve() != primary_db.resolve()
        for profile in (source_home, target_home)
    ):
        parser.exit(1, "Не найдена ожидаемая общая база проектов.\n")

    source = json.loads(source_path.read_bytes())
    if not isinstance(source, dict):
        parser.exit(1, "Некорректный формат настроек источника.\n")
    target_bytes = path.read_bytes()
    target = json.loads(target_bytes)
    if not isinstance(target, dict):
        parser.exit(1, "Некорректный формат настроек назначения.\n")
    with sqlite3.connect(f"{primary_db.as_uri()}?mode=ro", uri=True) as db:
        project_ids = {row[0] for row in db.execute("SELECT id FROM projects")}

    updated = restore_metadata(source, target, source_home, target_home, project_ids)
    print(f"{direction}. Проекты: {len(updated.get('local-projects', {}))}. "
          f"Сохранённые привязки: {len(updated['thread-project-assignments'])}.")
    if not args.apply:
        print("Режим проверки. Файлы не изменены.")
        return
    if updated == target:
        print("Все настройки уже присутствуют.")
        return
    if path.read_bytes() != target_bytes:
        parser.exit(1, "Файл настроек изменился во время проверки. Запусти команду снова.\n")

    backup_dir = Path(tempfile.mkdtemp(prefix="project-sidebar-backup-", dir=target_home))
    backup = backup_dir / STATE_FILE
    shutil.copy2(path, backup)
    tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target_home, delete=False)
    temporary = Path(tmp.name)
    try:
        with tmp:
            json.dump(updated, tmp, ensure_ascii=False, separators=(",", ":"))
            tmp.flush()
            os.fsync(tmp.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Настройки проектов восстановлены. Резервная копия: {backup}")


if __name__ == "__main__":
    main()
