# CodingApp on the air-gapped server

**No internet is used at any point.** You need Linux, Docker ≥ 20.10, and the package file
`codingapp-<version>-offline.tar.gz` (plus its `.sha256`).

**Everything stays in one folder**, the project folder `codingapp/`:

```
codingapp/
  install.sh  codingapp.sh  docker-compose.yml    scripts
  .env                                            settings (created by install.sh)
  code/                                           the application (mounted read-only)
  code.previous/                                  code before the last update (rollback)
  data/                                           database + secret key
  backups/                                        backups
  codingapp-runtime-<n>.tar.gz                    runtime image file (Python + libraries)
  .env.example  MANIFEST.txt  SHA256SUMS  CHANGELOG.md  DEPLOY.md  selftest.py
```

The Docker image is only the runtime. The application is the `code/` folder, so code updates
don't need a new image. Docker itself keeps a copy of the loaded image and the container logs in
its own storage; that is unavoidable, and everything else is in this folder.

---

## 1. First install

Put the package where the project folder should live (e.g. `/home/appadmin`), then:

```bash
sha256sum codingapp-1.0.1-offline.tar.gz     # compare with the .sha256 file
tar -xzf codingapp-1.0.1-offline.tar.gz      # creates the folder ./codingapp
cd codingapp
sudo bash install.sh
```

The installer asks for the admin password, the web port (default 8090), the vLLM URL and the
vLLM API key. It then:

1. checks Docker, the CPU architecture and disk space, and verifies the checksums of all files;
2. loads the runtime image from the folder (`docker load`);
3. self-tests the application in a separate container with no network;
4. writes `.env` with a random `SECRET_KEY`;
5. sets up `data/`, tests the vLLM connection (warning only) and starts CodingApp.

Open `http://<server>:<port>` and sign in as `admin`.

**Without an interactive terminal** (e.g. run from a script), the installer stops after
creating `.env`. Edit `codingapp/.env` (`ADMIN_PASSWORD`, `APP_PORT`, `LLM_BASE_URL`), then run
`sudo bash install.sh` again. You can also prepare `.env` before the first run: `cp .env.example .env`
and edit it.

### Upgrading from version 1.0.0

Version 1.0.0 ran from its own folder (`codingapp-1.0.0`) and kept its data in a Docker volume.
Do the first install above **while 1.0.0 is still running**. The installer then:

- takes over the 1.0.0 settings (`.env`: admin password, secret key, port, vLLM URL);
- backs up the running 1.0.0 data into `codingapp/backups/`;
- stops 1.0.0 and **copies its data** from the Docker volume `codingapp_data` into
  `codingapp/data/`, leaving the volume itself untouched;
- starts the new version on the same port. Users, chats and LDAP settings are all kept.

Going back is possible: the old folder, image and volume are unchanged. Stop the new version
(`sudo ./codingapp.sh stop`), then run `sudo bash install.sh` in `codingapp-1.0.0`.
Once you're happy, remove the leftovers:
`docker image rm codingapp:1.0.0`, `docker volume rm codingapp_data`, and the old folder.

---

## 2. Updates (always from inside the project folder)

Copy the new package anywhere on the server, **do not extract it**, then:

```bash
cd codingapp
sudo ./codingapp.sh update /path/to/codingapp-code-1.0.2.tar.gz      # code-only package
sudo ./codingapp.sh update /path/to/codingapp-1.1.0-offline.tar.gz   # or a full package
```

Both kinds are applied the same way:

1. Verify the checksums. A full package also loads its runtime image.
2. Check the code against the runtime libraries, then self-test it offline. Production is
   untouched until here.
3. Back up the data.
4. Move the current code to `code.previous` and install the new code. A full package also
   updates the scripts and adds new settings to `.env`; existing values are kept.
5. Restart and verify the version. **On failure it rolls back automatically.** Downtime is a few
   seconds.

```bash
sudo ./codingapp.sh rollback   # back to the previous code (run again to go forward)
sudo ./codingapp.sh version    # code version, runtime, settings file, rollback target
```

If a code package needs Python libraries that the runtime image doesn't have, it is refused and
you are asked for the full package of that version. Nothing is changed in that case.

**Quick fix by hand:** edit files under `code/app/`, then `sudo ./codingapp.sh restart`.
Run `cp -a code code.previous` first so `rollback` can undo it. UI changes need a rebuilt
`code/static`, so use a code package for those.

---

## 3. Settings: `codingapp/.env`

Edit, then `sudo ./codingapp.sh restart`.

| Setting | Meaning |
|---|---|
| `APP_PORT`, `APP_BIND` | web port and bind address (default `8090`, `0.0.0.0`) |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | built-in admin (always works, even if LDAP is misconfigured) |
| `SECRET_KEY` | generated at install. **Never change it**: it signs sessions and encrypts the stored LDAP password |
| `LLM_BASE_URL` | vLLM on this host: `http://host.docker.internal:8000/v1`; elsewhere: `http://10.x.x.x:8000/v1` |
| `LLM_API_KEY` | the vLLM `--api-key` (anything if vLLM has none) |
| `LLM_MAX_OUTPUT_TOKENS` | about ¼ of the model context (8192 for 32K, 32768 for 128K+) |
| `RUNTIME_VERSION` | managed by install/update; don't edit |

- The context window is read from vLLM automatically. Start vLLM with a large `--max-model-len`
  and `--enable-prefix-caching`.
- `sudo ./codingapp.sh check-llm` tests the vLLM connection.

**In the web UI** (admin → gear icon → Administration):
- **Directory (LDAP)**: server (`ldaps://dc.corp.local:636`), search base, optional allowed/admin
  groups. The service account is optional: without one, users sign in directly as
  `username@<domain from the search base>` (or the **User sign-in format**, e.g. `CORP\{username}`).
  Test with a real user and their password, then **Enable** and **Save**.
  - For an internal CA, copy `ca.pem` into `codingapp/data/` and set the CA path to `/data/ca.pem`.
- **LLM → Thinking mode**: On / Off / Model default.

---

## 4. Day-to-day (from inside `codingapp/`)

```bash
sudo ./codingapp.sh status            # versions, settings file, container state, health
sudo ./codingapp.sh logs              # follow the logs (Ctrl+C to stop)
sudo ./codingapp.sh restart           # apply changes made in .env or code/
sudo ./codingapp.sh stop | start
sudo ./codingapp.sh backup            # -> backups/codingapp-backup-<date>.tar.gz (safe while running)
sudo ./codingapp.sh restore <file>    # restore a backup (asks for confirmation)
sudo ./codingapp.sh uninstall         # remove container + images; the folder is kept
sudo ./codingapp.sh uninstall --purge # also delete data/ (asks for confirmation)
```

The app restarts automatically after a reboot. Logs are rotated (5 × 20 MB).
**Moving the project folder:** run `sudo ./codingapp.sh stop`, move the folder, then
`sudo ./codingapp.sh start` from its new location.

## HTTPS

CodingApp serves plain HTTP. Behind a reverse proxy:
- set `COOKIE_SECURE=true` (and optionally `APP_BIND=127.0.0.1`), then restart;
- disable response buffering and use a long read timeout, e.g. for nginx:
  `proxy_buffering off; proxy_read_timeout 1800s;`;
- allow 26 MB uploads: `client_max_body_size 26m;`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Port … is already in use" | the message shows which process holds the port. Set another `APP_PORT` in `codingapp/.env` and run `sudo bash install.sh` again |
| "architecture doesn't match" | rebuild the package for this CPU (see BUILD.md) |
| "Cannot talk to the Docker daemon" | use `sudo`, or add the user to the `docker` group |
| `unknown flag --platform` / `host-gateway` errors | Docker is older than 20.10: upgrade Docker |
| Log: "needs different Python libraries" | use the full package of that version |
| Log: "No application code in /code" | `codingapp/code` is missing or unreadable. On SELinux hosts keep the `:z` in docker-compose.yml |
| Top bar shows **LLM offline** | `sudo ./codingapp.sh check-llm`; fix `LLM_BASE_URL` / `LLM_API_KEY`; restart |
| `host.docker.internal` unreachable | vLLM must listen on `0.0.0.0`; allow Docker's bridge (e.g. `172.17.0.0/16`) in the host firewall |
| Answers appear all at once | the reverse proxy buffers; see HTTPS |
| Forgot the admin password | edit `ADMIN_PASSWORD` in `.env`, then restart |

**Isolation:** CodingApp uses only its folder, its container `codingapp`, its images
`codingapp-runtime:*` and its port. It never touches vLLM or other containers.
