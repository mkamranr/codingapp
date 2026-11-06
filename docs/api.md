# API

Interactive OpenAPI docs: `http://<server>:<port>/api/docs`.

All endpoints except `/api/health` and `/api/auth/login` require the session cookie set by
login. Users can only access their own conversations. `/api/admin/*` requires an admin.

## Health

| Method | Path | |
|---|---|---|
| GET | `/api/health` | status, version, LLM reachability |

## Auth

| Method | Path | Body / result |
|---|---|---|
| POST | `/api/auth/login` | `{"username", "password"}`: sets the session cookie |
| POST | `/api/auth/logout` | clears the cookie |
| GET | `/api/auth/me` | current user (`username`, `display_name`, `is_admin`, ...) |

## Conversations and files

| Method | Path | |
|---|---|---|
| GET | `/api/conversations` | list your chats |
| POST | `/api/conversations` | create a chat |
| GET | `/api/conversations/{cid}` | chat with messages and files |
| PATCH | `/api/conversations/{cid}` | rename |
| DELETE | `/api/conversations/{cid}` | delete |
| POST | `/api/conversations/{cid}/files` | upload (`multipart/form-data`, field `files`, repeatable; zips allowed) |
| DELETE | `/api/conversations/{cid}/files?path=...` | remove one file; without `path`, remove all |
| GET | `/api/conversations/{cid}/file?path=...` | current content of one file |
| POST | `/api/conversations/{cid}/pins` | `{"path", "pinned": true\|false}` |

## Chat (streaming)

`POST /api/conversations/{cid}/messages` with `{"content": "..."}`, or
`{"continue_last": true}` to continue the last answer.

The response is `text/event-stream`:

| Event | Data |
|---|---|
| `start` | `{message_id, user_message_id, ...}` |
| `context` | token budget, files included / left out |
| `reasoning` | `{t}`: thinking text chunk |
| `delta` | `{t}`: answer text chunk |
| `continuing` | `{round}`: automatic continuation started |
| `files` | `{files}`: files produced by this answer |
| `done` | `{finish_reason}` |
| `error` | `{message}` |

## Downloads

| Method | Path | |
|---|---|---|
| GET | `/api/files/{file_id}/download` | one file, with its real name |
| GET | `/api/conversations/{cid}/export.zip?mode=full` | full project with fixes applied |
| GET | `/api/conversations/{cid}/export.zip?mode=changed` | only created or modified files |

Add `&message_id=<id>` to export the state as of one answer.

## Admin

| Method | Path | |
|---|---|---|
| GET / PUT | `/api/admin/ldap` | LDAP settings (the password is never returned; `clear_bind_password` removes it) |
| POST | `/api/admin/ldap/test` | test with the form values plus `test_username` / `test_password` |
| GET | `/api/admin/llm` | model, context, exact-tokenizer flag, thinking mode |
| PUT | `/api/admin/llm/settings` | `{"thinking": "default" \| "on" \| "off"}` |
| GET | `/api/admin/users` | users with source, role, chat count, last sign-in |
