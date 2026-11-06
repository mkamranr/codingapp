# Configuration reference

On the server all settings are in **`codingapp/.env`**. Apply changes with
`sudo ./codingapp.sh restart`. Write values without quotes. Empty values fall back to the default.

## Web server

| Setting | Default | Meaning |
|---|---|---|
| `APP_PORT` | `8090` | host port of the web UI |
| `APP_BIND` | `0.0.0.0` | bind address; `127.0.0.1` when behind a local reverse proxy |
| `COOKIE_SECURE` | `false` | `true` when users reach the app over HTTPS |
| `SESSION_HOURS` | `12` | session lifetime |

## Built-in administrator

| Setting | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | |
| `ADMIN_PASSWORD` | (set at install) | the installer refuses `change-me` |
| `SECRET_KEY` | (generated at install) | signs sessions and encrypts the stored LDAP password. **Never change it**: if it changes, the stored LDAP password can't be decrypted and everyone is signed out |

## LLM (OpenAI-compatible, e.g. vLLM)

| Setting | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:8000/v1` | vLLM on the same host; otherwise `http://<ip>:8000/v1` |
| `LLM_API_KEY` | `EMPTY` | vLLM `--api-key` |
| `LLM_MODEL` | (empty) | empty = first model reported by `/v1/models` |
| `LLM_CONTEXT_TOKENS` | `0` | `0` = auto-detect `max_model_len`; a number overrides it |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | tokens reserved for each answer. Rule of thumb: ¼ of the context |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_ENABLE_THINKING` | (empty) | initial thinking mode (`true` / `false` / empty); admins change it in the UI |
| `LLM_AUTO_CONTINUE` | `3` | automatic continuations when an answer hits the output limit |
| `LLM_REQUEST_TIMEOUT` | `1800` | seconds to wait for one answer |

## Uploads

| Setting | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | `25` | size of one upload (files or zip) |
| `MAX_EXTRACTED_MB` | `200` | total size after extracting archives |
| `MAX_FILES` | `5000` | files per upload |
| `MAX_FILE_KB` | `2048` | larger files are skipped |

If a reverse proxy is in front, allow slightly more than `MAX_UPLOAD_MB` (e.g. nginx
`client_max_body_size 26m;`).

## Managed automatically

| Setting | Meaning |
|---|---|
| `RUNTIME_VERSION` | which runtime image `codingapp-runtime:<n>` runs; set by install/update |

Inside the container these are fixed: `DATA_DIR=/data`, `CODE_DIR=/code`,
`STATIC_DIR=/code/static`. The application version is read from `code/VERSION`.

## Settings in the web UI

LDAP / Active Directory and the thinking mode are stored in the database and edited under
**Administration**. See the [admin guide](admin-guide.md).
