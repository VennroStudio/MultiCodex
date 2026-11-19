#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


PROJECT_DIR = Path(__file__).resolve().parent.parent
HELP = """MultiCodex

  make launch ACCOUNT=name          Открыть аккаунт
  make setup ACCOUNT=name           Первый запуск с общей историей
  make sync FROM=name TO=other       Перенести проекты и привязки
  make preview FROM=name TO=other    Предварительная проверка переноса
  make status                       Показать настроенные аккаунты

Аккаунты задаются в accounts.json, общие пути в .env.
Перед setup и sync полностью закрой все окна ChatGPT через ⌘Q.
"""


def path_value(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Ожидался непустой путь.")
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        raise ValueError(f"Нужен абсолютный путь: {value}")
    return path.resolve()


def load_accounts():
    config_path = path_value(os.environ["ACCOUNTS_FILE"])
    config = json.loads(config_path.read_text())
    if not isinstance(config, dict):
        raise ValueError("accounts.json должен содержать объект.")
    primary = config.get("primary")
    definitions = config.get("accounts")
    if not isinstance(primary, str) or not isinstance(definitions, dict) or primary not in definitions:
        raise ValueError("В accounts.json нужны accounts и primary с именем основного аккаунта.")
    accounts = {}
    homes = set()
    ui_dirs = set()
    for name, definition in definitions.items():
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or ".." in name:
            raise ValueError(f"Недопустимое имя аккаунта: {name}")
        if not isinstance(definition, dict):
            raise ValueError(f"Настройки аккаунта {name} должны быть объектом.")
        codex_home = path_value(definition.get(
            "codex_home", str(path_value(os.environ["CODEX_PROFILES_DIR"]) / f".codex-{name}")
        ))
        ui_dir = path_value(definition.get(
            "ui_dir", str(path_value(os.environ["ELECTRON_PROFILES_DIR"]) / f"Codex-{name}")
        ))
        if codex_home in homes or ui_dir in ui_dirs:
            raise ValueError(f"У аккаунта {name} совпадает каталог с другим аккаунтом.")
        homes.add(codex_home)
        ui_dirs.add(ui_dir)
        accounts[name] = {"codex_home": codex_home, "ui_dir": ui_dir}
    return primary, accounts


def require_closed():
    commands = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True).splitlines()
    if any(command.strip().endswith(("/Contents/MacOS/ChatGPT", "/Contents/MacOS/Codex")) for command in commands):
        raise ValueError("Полностью закрой все окна ChatGPT/Codex через ⌘Q и повтори команду.")


def main():
    parser = argparse.ArgumentParser(description="MultiCodex account launcher")
    parser.add_argument("action", choices=("help", "status", "launch", "setup", "sync", "preview"), nargs="?", default="help")
    parser.add_argument("--account")
    parser.add_argument("--from-account")
    parser.add_argument("--to-account")
    args = parser.parse_args()
    if args.action == "help":
        print(HELP)
        return 0
    primary, accounts = load_accounts()
    selected = [args.account] if args.action in ("launch", "setup") else []
    if args.action in ("sync", "preview"):
        selected = [args.from_account, args.to_account]
    for name in selected:
        if not name or name not in accounts:
            parser.error(f"Укажи имя из accounts.json. Доступны: {', '.join(accounts)}")

    if args.action == "status":
        for name, account in accounts.items():
            state = "настроен" if (account["codex_home"] / ".codex-global-state.json").is_file() else "первый запуск не выполнен"
            label = " (основной)" if name == primary else ""
            print(f"{name}{label}: {account['codex_home']} — {state}")
        return 0

    if args.action in ("sync", "preview"):
        command = [
            sys.executable, str(PROJECT_DIR / "scripts/sync_projects.py"),
            "--source-home", str(accounts[args.from_account]["codex_home"]),
            "--target-home", str(accounts[args.to_account]["codex_home"]),
            "--database", str(path_value(os.environ["STATE_DATABASE"])),
        ]
        if args.action == "sync":
            command.append("--apply")
        return subprocess.call(command)

    app = path_value(os.environ["CHATGPT_APP"])
    if args.account == primary:
        if args.action == "setup":
            require_closed()
        return subprocess.call(["/usr/bin/open", "-a", str(app)])

    account = accounts[args.account]
    if args.action == "setup":
        require_closed()
    elif not account["codex_home"].is_dir() or not account["ui_dir"].is_dir():
        raise ValueError(f"Сначала выполни make setup ACCOUNT={args.account}.")
    command = [
        "/bin/bash", str(PROJECT_DIR / "vendor/codex-multi-account.sh"),
        "--app", str(app), "--account", args.account,
        "--primary-home", str(accounts[primary]["codex_home"]),
        "--secondary-home", str(account["codex_home"]),
        "--profile-dir", str(account["ui_dir"]),
    ]
    if args.action == "setup":
        command.append("--symlink-history")
    env = dict(os.environ)
    env["CODEX_ELECTRON_USER_DATA_PATH"] = str(account["ui_dir"])
    env["CODEX_MULTI_REGISTRY_DIR"] = str(path_value(os.environ["REGISTRY_DIR"]))
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)
