# MultiCodex

## Команды

```bash
cd /MultiCodex
```

| Команда | Действие |
| --- | --- |
| `make launch ACCOUNT=personal` | Открыть указанный аккаунт |
| `make setup ACCOUNT=client-one` | Первый запуск: общие чаты, отдельные проекты и вход |
| `make sync FROM=personal TO=main` | Перенести проекты и привязки из `FROM` в `TO` |
| `make sync FROM=main TO=personal` | Перенести в обратном направлении |
| `make preview FROM=personal TO=main` | Проверить перенос без записи |
| `make status` | Показать аккаунты и пути |
| `make help` | Показать команды |

Перед `setup` и `sync` закрой все окна ChatGPT через **⌘Q**.

## Новый аккаунт

1. Добавь в `accounts` файла `accounts.json` запись `"client-one": {}`. Поставь запятую после предыдущей записи. Имя может быть любым допустимым: латинские буквы, цифры, дефис, подчёркивание или точка, без `..`.
2. Закрой все окна ChatGPT/Codex через **⌘Q** и выполни из каталога MultiCodex:

   ```bash
   make setup ACCOUNT=client-one
   ```

3. В открывшемся окне войди нужным аккаунтом. История чатов общая, список проектов отдельный.
4. Чтобы перенести проекты из `main`, после входа снова закрой все окна через **⌘Q**, затем выполни:

   ```bash
   make sync FROM=main TO=client-one
   make launch ACCOUNT=client-one
   ```

Для следующих запусков:

```bash
make launch ACCOUNT=client-one
```

## .env

```bash
# Путь к приложению
CHATGPT_APP="/Applications/ChatGPT.app"
# Конфиг аккаунтов; MULTICODEX_PROJECT_DIR задаётся скриптом
ACCOUNTS_FILE="${MULTICODEX_PROJECT_DIR}/accounts.json"
# Базовый каталог данных новых аккаунтов
CODEX_PROFILES_DIR="${HOME}"
# Базовый каталог профилей окон
ELECTRON_PROFILES_DIR="${HOME}/Library/Application Support"
# Общая база основного аккаунта
STATE_DATABASE="${HOME}/.codex/state_5.sqlite"
# Реестр окон лаунчера
REGISTRY_DIR="${HOME}/.codex-multi-account"
# Интерпретатор Python
PYTHON="/usr/bin/python3"
```

## accounts.json

```json
{
  "primary": "main",
  "accounts": {
    "main": {
      "codex_home": "${HOME}/.codex"
    },
    "personal": {
      "codex_home": "${HOME}/.codex-work",
      "ui_dir": "${HOME}/Library/Application Support/Codex-work"
    },
    "client-one": {}
  }
}
```

- `primary` — имя основного аккаунта, открываемого обычным ChatGPT.
- Ключи в `accounts` — имена для `ACCOUNT`, `FROM` и `TO`. Добавляй любое количество записей.
- `codex_home` — каталог данных и входа Codex.
- `ui_dir` — каталог профиля окна дополнительного аккаунта.
