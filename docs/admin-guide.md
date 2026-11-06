# Admin guide

Administrators open **Administration** from the gear icon in the top bar. It has three tabs:
**Directory**, **LLM** and **Users**.

Who is an administrator:
- the built-in admin (`ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`), which always works, even if LDAP is misconfigured;
- LDAP users in the **Administrators group** (optional).

## Directory (LDAP / Active Directory)

### Fields

| Field | Example | Notes |
|---|---|---|
| Server URL | `ldaps://dc01.corp.local:636` or `ldap://dc01.corp.local:389` | |
| StartTLS | off | upgrades `ldap://` to TLS |
| Verify certificate / CA path | `/data/ca.pem` | For an internal CA, copy `ca.pem` into `codingapp/data/` |
| Service account (bind DN or UPN) | `svc-codingapp@corp.local` | **optional**; see below |
| Service account password | | stored encrypted with `SECRET_KEY` |
| User sign-in format | `CORP\{username}` or `{username}@corp.local` | used only without a service account; blank = `username@<domain from search base>` |
| Search base | `DC=corp,DC=local` | |
| User filter | `(&(objectClass=user)(sAMAccountName={username}))` | |
| Display name / email attribute | `displayName` / `mail` | |
| Allowed group DN | `CN=CodingApp Users,OU=Groups,DC=corp,DC=local` | optional; only members may sign in |
| Administrators group DN | `CN=CodingApp Admins,OU=Groups,DC=corp,DC=local` | optional; members become admins |

### Sign-in modes

1. **With a service account.** CodingApp binds as the service account, searches for the user,
   then verifies the user's password with a second bind.
2. **Without a service account** (recommended when you don't have one). The user binds directly
   with their own credentials as `username@<domain>` or the **User sign-in format**. CodingApp then
   searches for their entry using the user's own rights. This works on Active Directory, which
   blocks anonymous searches.
3. **Anonymous search.** Used only if no sign-in name can be derived and the directory allows
   anonymous reads (rare on AD).

An empty password never signs anyone in.

To switch from a service account to direct sign-in, tick **Remove the stored password** and save.

### Testing

1. Enter a real **test user** and that user's **password**. The test password is never stored.
2. Click **Test**. Each step is shown: connect, bind, user found, groups.
3. When the test passes, tick **Enable** and click **Save**.

If the test reports *"a successful bind must be completed"*, the directory blocks anonymous searches.
Either enter the test user's password (direct sign-in) or configure a service account.

LDAP users are created in CodingApp on their first sign-in. Their admin rights are re-evaluated
at every sign-in.

## LLM

Shows the connection to the model server:
- the URL, the model, the context window (`max_model_len`) and the max output tokens;
- whether exact token counting (`/tokenize`) is available.

**Thinking mode** applies immediately to all users:

| Setting | Effect |
|---|---|
| Model default | don't send anything; the model's chat template decides |
| On | `chat_template_kwargs.enable_thinking = true`, so the model reasons first (slower, often better for hard bugs) |
| Off | `enable_thinking = false`, so answers come faster |

The URL, API key and token limits are set in `.env` (see [configuration.md](configuration.md)).
On the server, `sudo ./codingapp.sh check-llm` tests the connection.

### vLLM recommendations

- Start vLLM with a large `--max-model-len`. CodingApp uses the full window.
- Use `--enable-prefix-caching`. Follow-up questions reuse the project prefix and answer much faster.
- Set `LLM_MAX_OUTPUT_TOKENS` to about ¼ of the context.

## Users

Lists every account with the following details:
- source (Local / Directory) and role;
- number of chats and last sign-in.

## Operations

Day-to-day commands (`status`, `logs`, `backup`, `restore`, `update`, `rollback`) are in
[DEPLOY.md](../DEPLOY.md#4-day-to-day-from-inside-codingapp).

**Forgot the admin password:** edit `ADMIN_PASSWORD` in `codingapp/.env`, then run
`sudo ./codingapp.sh restart`.
