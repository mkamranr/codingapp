# User guide

## Signing in

Open `http://<server>:<port>` and sign in:

- **Company account** (when the administrator has enabled Active Directory/LDAP): use your normal
  Windows user name and password. `bob`, `CORP\bob` and `bob@corp.local` all work and refer to the
  same account.
- **Built-in admin**: the user `admin` with the password set during installation.

Sessions last 12 hours by default. Your chats are private to your account.

## Starting a chat

Click **New chat** in the sidebar. Your chats are listed there; you can rename or delete them.

## Adding code

Use the upload button in the message box, or drag and drop files onto the page:

- single files, several files, or a whole **folder**;
- a **`.zip`** of a project. It is extracted on the server, keeping the folder structure.

Limits (defaults, set by the administrator):

| | |
|---|---|
| upload size | 25 MB per upload |
| extracted size | 200 MB |
| number of files | 5,000 |
| single file | 2 MB |

These files are **skipped automatically**, and the upload summary lists each one with the reason:

- **Folders:** `.git`, `node_modules`, `__pycache__`, `.venv`/`venv`, `dist`, `build`, `out`, `target`, `bin`, `obj`, `.next`, `.idea`, `.vscode`, caches, and similar.
- **Binary files:** images, PDFs, Office documents, archives inside archives, executables, fonts, media, databases and model weights.
- **Unsafe zip entries:** absolute paths, `..`, and symlinks.
- **Files over the size limit.**

The project's files appear in the **file panel**. There you can:
- open a file to read it;
- **pin** a file so it is always sent to the model first;
- remove one file, or clear the whole project.

## Asking questions and getting fixes

Type your request, for example:

- "Explain how authentication works in this project."
- "Find the bug that makes `parse_date` fail for ISO dates and fix it."
- "Add input validation to `api/users.py`."

The answer streams in live. When the model writes or changes files, each file appears as a code
block with its path, plus:

- **Copy**: copies the file content;
- **Download**: saves the file under its real name.

### Downloading the result as a zip

| Download | Contains |
|---|---|
| **Full project** | all files with every fix applied, in the original folder structure |
| **Changed files only** | just the files the assistant created or modified |

Both are available per answer (the state after that answer) and for the whole chat.

### Follow-up questions

The workspace is versioned. After a fix, follow-up questions see the **fixed** files, so you can
keep refining ("now add tests for that function").

### Long answers

If an answer reaches the output limit it continues automatically. If it still stops early,
click **Continue**.

## Large projects

CodingApp uses the model's whole context window. If the project doesn't fit, it picks files in this order:
1. **pinned** files;
2. files **mentioned** in your message (by path or name);
3. files that were **modified** in this chat;
4. files **imported** by the files above;
5. everything else, smallest first.

Files that were left out are marked in the file panel. To focus the model, pin files or name them in your
message.

## Tips

- Name files explicitly when you can: `fix the null check in src/service/order.ts`.
- Ask for complete files when you want to download them directly.
- Start a new chat for an unrelated task; long histories take context space.
- If the top bar shows **LLM offline**, the model server is unreachable. Tell your administrator.
