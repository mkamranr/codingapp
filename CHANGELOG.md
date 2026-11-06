# Changelog

## 1.0.1

**Everything in one project folder, code outside the Docker image**
- The package unpacks to a single folder `codingapp/`, and CodingApp runs from there: settings
  (`.env`), application (`code/`), data (`data/`, previously a Docker volume), backups and the
  runtime image file all stay inside it.
- The image is now only the runtime: `codingapp-runtime:<RUNTIME_VERSION>` (Python + libraries).
  The application is mounted read-only from `code/`.
- One command for every later update, run inside the folder:
  `sudo ./codingapp.sh update <code package | full package>`. It verifies the package, checks it
  against the runtime's libraries, self-tests it offline, backs up, switches, restarts and rolls
  back automatically on failure. `rollback` returns to the previous code.
- The container refuses to start code that needs different Python libraries than its image.
- Upgrading from 1.0.0: `install.sh` takes over the 1.0.0 settings, backs up, and copies the data
  from the Docker volume into `data/`. The old volume is left untouched, so going back is possible.
- Build: `scripts/build-release.sh` (full package) and `--code-only` (code package, ~400 KB).

**LDAP / Active Directory login without a service account**
- If no service account password is stored, users sign in directly as `username@<domain>` (domain
  taken from the search base) or as the new **User sign-in format** (e.g. `CORP\{username}`). They
  are then looked up with their own rights. This works on AD, which blocks anonymous searches.
- Users may also type `CORP\bob` or `bob@corp.local`. All forms map to the same account (`bob`).
- The service account remains supported (unchanged behaviour when its password is set).
- Administration → Directory: new "User sign-in format" field, a "Remove the stored password"
  option and a test-user password box (never stored).
- An empty service password no longer causes "password is mandatory in simple bind".

No database changes.

## 1.0.0

Initial release.
