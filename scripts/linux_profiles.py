import fcntl
import os
from pathlib import Path
import re
import subprocess
import tomllib
from contextlib import contextmanager


STATE_FILE = ".codex-global-state.json"
HISTORY_DIRS = ("sessions", "archived_sessions", "attachments", "shell_snapshots",
                "generated_images", "worktrees")


def latest_database(home, family):
    candidates = []
    for path in home.glob(f"{family}_*.sqlite"):
        match = re.fullmatch(rf"{family}_(\d+)\.sqlite", path.name)
        if match and path.is_file():
            candidates.append((int(match[1]), path))
    return max(candidates)[1] if candidates else None


def require_closed(app):
    launcher = app.resolve()
    desktop = {launcher, launcher.with_name("ChatGPT")}
    app_server = launcher.parent / "resources/codex"
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            executable = Path(os.readlink(process / "exe").removesuffix(" (deleted)"))
            if executable in desktop or (
                executable == app_server and b"app-server" in (process / "cmdline").read_bytes().split(b"\0")
            ):
                raise ValueError("Полностью закрой ChatGPT/Codex через Ctrl+Q и повтори команду.")
        except OSError:
            continue


@contextmanager
def history_lock(database):
    lock = database.parent / ".multicodex.lock"
    fd = os.open(lock, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def check_profile(home, ui):
    for path in (home, ui):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"Ожидалась отдельная папка профиля: {path}")
    for name in ("auth.json", "auth.lock", STATE_FILE, "config.toml"):
        path = home / name
        if path.is_symlink() or (path.exists() and (
            not path.is_file() or path.stat().st_nlink != 1
        )):
            raise ValueError(f"Ожидался отдельный файл профиля: {path}")
    config = home / "config.toml"
    if config.is_file():
        with config.open("rb") as stream:
            if "sqlite_home" in tomllib.load(stream):
                raise ValueError(f"У профиля задан отдельный путь SQLite в {config}.")


def connect_history(primary_home, home, ui, database, *, setup):
    history_db = latest_database(primary_home, "thread_history")
    directories = [primary_home / name for name in HISTORY_DIRS]
    index_files = [primary_home / name for name in ("session_index.jsonl", "session_index.jsonl.lock")]
    files = [database, *index_files]
    if history_db is not None:
        files.append(history_db)
    if (primary_home / "history.jsonl").exists():
        files.append(primary_home / "history.jsonl")
    for source, valid in [(path, path.is_dir()) for path in directories] + [
        (path, path.is_file()) for path in files
    ]:
        if source.is_symlink() or (source.exists() and not valid):
            raise ValueError(f"Неожиданный тип файла истории: {source}")
    for path in home.glob("*.sqlite*"):
        if re.fullmatch(r"(state|thread_history)_\d+\.sqlite(?:-wal|-shm)?", path.name):
            if not path.is_symlink() or path.resolve() != primary_home / path.name:
                raise ValueError(f"Найдена отдельная история: {path}")

    missing = []
    for source in directories + files:
        target = home / source.name
        if target.is_symlink() and target.resolve() == source:
            if not source.exists():
                missing.append(source)
            continue
        if target.is_symlink() or target.exists():
            raise ValueError(f"Найдена отдельная история: {target}")
        missing.append(source)
    if not setup:
        return missing

    home.mkdir(mode=0o700, exist_ok=True, parents=True)
    ui.mkdir(mode=0o700, exist_ok=True, parents=True)
    for source in directories:
        source.mkdir(mode=0o700, exist_ok=True)
    for source in index_files:
        if not source.exists():
            source.touch(mode=0o600, exist_ok=False)
    # Linux SQLite resolves database links before opening its WAL and SHM files.
    for source in missing:
        target = home / source.name
        if not target.is_symlink():
            target.symlink_to(source, target_is_directory=source in directories)
    settings = home / STATE_FILE
    if not settings.exists():
        with settings.open("x") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write("{}\n")
    return []


def launch(app, name, account, primary, database, *, setup):
    if not app.is_file() or not os.access(app, os.X_OK):
        raise ValueError(f"Не найден исполняемый файл ChatGPT: {app}")
    home, ui = account["codex_home"], account["ui_dir"]
    check_profile(home, ui)
    if not database.is_file() or database.parent != primary["codex_home"]:
        raise ValueError(f"Не найдена база основного профиля: {database}")
    with history_lock(database):
        if setup:
            require_closed(app)
        if account != primary:
            check_profile(primary["codex_home"], primary["ui_dir"])
            if not setup and not (home.is_dir() and ui.is_dir()):
                raise ValueError(f"Сначала выполни make setup ACCOUNT={name}.")
            if connect_history(primary["codex_home"], home, ui, database, setup=setup):
                raise ValueError(f"Общая история подключена не полностью. Выполни make setup ACCOUNT={name}.")
        env = {
            **os.environ, "CODEX_HOME": str(home),
            "CODEX_SQLITE_HOME": str(home), "CODEX_ELECTRON_USER_DATA_PATH": str(ui),
        }
        log = home / "desktop-launch.log"
        with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600), "ab") as stream:
            process = subprocess.Popen([str(app), f"--user-data-dir={ui}"], env=env,
                                       stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                status = process.wait(timeout=0.7)
            except subprocess.TimeoutExpired:
                print(f"Открывается {name}. Журнал запуска: {log}")
            else:
                if status:
                    raise ValueError(f"ChatGPT завершился с кодом {status}. Журнал: {log}")
                print(f"Команда открытия передана профилю {name}.")
    return 0
