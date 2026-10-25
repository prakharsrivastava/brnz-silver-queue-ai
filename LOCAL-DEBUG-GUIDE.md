# Local Azure Function debugging: `QueueToSilver`

This guide debugs the queue-triggered Function locally while using the
existing Azure Storage account and queue. It does not expose the local
Functions host to the internet, and does not require a public Event Grid
webhook.

## Flow being debugged

1. A file exists in `corpordrage` → `bronze` → `data/`.
2. A helper reads that blob's current ETag and adds a message to
   `bronze-to-silver`.
3. The local `QueueToSilver` Function reads the message and pauses at a VS
   Code breakpoint.
4. Continuing runs download, extraction, chunking, and Silver output writes.

This procedure does not test the automatic `BronzeToQueue` Event Grid stage.
Storage Event Grid must have a valid subscription to test that first stage.
At the last recorded check, the subscription did not exist.

## One-time setup

Prerequisites: Azure Functions Core Tools v4 (`func`), Python 3.13, VS Code
with the Python and Python Debugger extensions, and this project's private
`local.settings.json`. Never share `local.settings.json`; it contains
credentials.

From the project root:

```sh
python3.13 --version
python3.13 -m venv .venv-debug
./.venv-debug/bin/python -m pip install -r requirements-dev.txt
```

Use `.venv-debug/bin/python` as the VS Code interpreter for this debug
session. The ordinary `.venv` uses Python 3.14 on this machine and failed to
pause in the Functions worker.

Required local settings names are `AzureWebJobsStorage`,
`DATA_STORAGE_CONNECTION`, `DOCUMENT_QUEUE`, and, for PDF processing,
`DOCUMENT_INTELLIGENCE_ENDPOINT` plus `DOCUMENT_INTELLIGENCE_KEY`. Do not
print or paste their values.

## Repeatable debug session

### 1. Stop the remote queue consumer

In Azure Portal, open Function App `func-b2s-setowq66u6xfi` and select
**Stop**. The local and cloud hosts must not compete for the same queue
message. Verify the Portal reports **Stopped** before proceeding.

### 2. Set a breakpoint

Open `pipeline.py`. In `queue_to_silver`, click the gutter next to the
`PROCESS_STARTED` log statement (around line 134) to set a breakpoint.

### 3. Start the local Functions host

Open **Terminal → New Terminal** in VS Code (Terminal 1), ensure it is in the
project root, then run:

```sh
env PATH="$PWD/.venv-debug/bin:$PATH" \
  PYTHONPATH="$PWD/.venv-debug/lib/python3.13/site-packages/debugpy/_vendored/pydevd" \
  languageWorkers__python__arguments='-Xfrozen_modules=off -m debugpy --listen 127.0.0.1:9091' \
  func host start --functions QueueToSilver
```

Keep this terminal open. Wait for output similar to:

```text
Worker process started and initialized.
Host started
Functions:
    QueueToSilver: queueTrigger
```

The `PYTHONPATH` entry makes debugpy's vendored debugger modules importable
inside the Azure Functions Python worker. The listener binds to loopback
(`127.0.0.1`) only.

### 4. Attach VS Code debugger

In VS Code, open **Run and Debug**, choose **Debug QueueToSilver locally**,
and press **F5** (or the green Start button). This uses `.vscode/launch.json`
to attach to `127.0.0.1:9091`. Do this after Terminal 1 says the host is
ready.

### 5. Upload or choose a test file

For a new file, Azure Portal → **Storage accounts** → `corpordrage` →
**Containers** → `bronze` → open `data/` → **Upload**. Use a small `.txt`
file, for example `debug2.txt`.

The Portal upload alone does not trigger the local debugger. It only stores
the blob. The automatic storage Event Grid subscription was absent at the
last check.

### 6. Enqueue for the local Function

Open a second terminal at the project root (Terminal 2). For the example:

```sh
./.venv-debug/bin/python -m scripts.enqueue_debug_message data/debug2.txt
```

Use the exact path below the `bronze` container. For a filename with spaces,
quote the full argument:

```sh
./.venv-debug/bin/python -m scripts.enqueue_debug_message \
  "data/example file.txt"
```

The helper refuses PDF by default. PDF analysis may incur Document
Intelligence charges. If you knowingly want to process a PDF:

```sh
./.venv-debug/bin/python -m scripts.enqueue_debug_message \
  "data/2222_3_1793991_1791793802_Databricks - Generic.pdf" --allow-pdf
```

Only use `--allow-pdf` when accepting potential usage charges.

### 7. Inspect and step through

The debugger should pause at `PROCESS_STARTED`. Hover variables or use the
**Variables** pane to inspect `document_name`, `message`, `source_container`,
and `source_etag`. Press **F10** (Step Over) to move through the function.
Useful stages in the terminal are:

```text
PROCESS_STARTED
BLOB_DOWNLOADED
EXTRACTED
PROCESS_DONE
```

Successful output in the `silver` container includes `chunk_0001.md`,
`chunk_0001.json`, and `_complete.json` in a versioned folder.

### 8. Clean up and resume Azure processing

1. Press **Ctrl+C** in Terminal 1 to stop the local Functions host.
2. In VS Code, press **Shift+F5** to stop the attached debugger.
3. In Azure Portal, select **Start** on `func-b2s-setowq66u6xfi`.

Do not leave the Azure Function App stopped unintentionally.

## Errors seen and fixes

| Error / symptom | Cause | Fix |
|---|---|---|
| `unrecognized arguments: - Generic.pdf` | Shell split a filename containing spaces into multiple arguments. | Put quotes around the entire `data/...pdf` argument. |
| `BlobNotFound` / `The specified blob does not exist` | The queue helper was given a path not currently present in `bronze`. | Upload first; check the exact case-sensitive blob path, then enqueue. |
| Message was queued, but no breakpoint appeared | The debugger was not attached, or cloud Function consumed the queue message. | Stop the Azure Function App; start local host; attach debugger; only then enqueue. |
| `ModuleNotFoundError: No module named '_pydevd_bundle'` | debugpy's vendored modules were not on the worker import path; Python 3.14 also failed to pause reliably in this setup. | Use `.venv-debug` (Python 3.13) and the `PYTHONPATH` shown in the host command. |
| `func host start` uses the wrong Python/dependencies | The project environment was not first on `PATH`. | Start with the exact `env PATH="$PWD/.venv-debug/bin:$PATH" ...` command. |
| `F5` cannot attach | Host is not listening yet, wrong debug configuration, or wrong port. | Wait for host readiness; select **Debug QueueToSilver locally**, which attaches to `127.0.0.1:9091`. |
| Local host cannot connect to Storage | Missing/invalid private local settings or network/auth issue. | Check setting names and Azure Storage access locally; never paste credential values into documentation or chat. |

## Verified run from 2026-10-25

- Core Tools loaded `QueueToSilver` and printed `Host started`.
- Python 3.14 debugger attempt failed with `_pydevd_bundle` missing.
- Python 3.13 plus the documented `PYTHONPATH` allowed debugpy to attach.
- The breakpoint at `pipeline.py` line 134 was verified and paused with reason
  `breakpoint`; locals showed the expected TXT blob name, queue message,
  `bronze` source container, and ETag.
- A 61-byte TXT file ran through `PROCESS_STARTED`, `BLOB_DOWNLOADED`,
  `EXTRACTED chunks=1`, and `PROCESS_DONE chunks=1`; the Silver chunk and
  completion marker were verified.
- The PDF was also re-uploaded and processed after explicit `--allow-pdf`;
  this can incur Document Intelligence charges.
- Local host/debugger were stopped after testing, and the remote Function App
  was started and verified as `Running`.

Existing unit tests were rerun after the debugger setup: 7 tests passed.
