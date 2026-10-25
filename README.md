# Event-driven Bronze → Queue → Silver (Azure Functions Python v2)

This project is configured for an **existing Flex Consumption** Function App `func-b2s-setowq66u6xfi`.

## How it works

1. A new or replaced blob under `bronze/data/` emits a `Microsoft.Storage.BlobCreated` event.
2. **Event Grid** invokes `BronzeToQueue` (no timer, no container scanning).
3. The function puts a JSON message in Azure Storage Queue `bronze-to-silver`.
4. `QueueToSilver` is triggered by the queued message, extracts PDF to Markdown (or reads text/MD directly), chunks it, and writes chunk `.md`, `.json`, and `_complete.json` to `silver`.

## Required Azure resources

- An Azure Storage account with Blob containers `bronze` and `silver` and queue `bronze-to-silver`.
- A Document Intelligence resource for PDF extraction.
- An existing Function App on Flex Consumption.
- **An Event Grid event subscription on the storage account:** creating the code and publishing it is not enough.

## Function App → Settings → Environment variables

Keep pre-existing Function App host/storage configuration intact. Set:

| Key | Value |
|---|---|
| `DATA_STORAGE_CONNECTION` | Your storage account connection string (same for blob + queue) |
| `DOCUMENT_QUEUE` | `bronze-to-silver` |
| `SILVER_CONTAINER` | `silver` |
| `DOCUMENT_INTELLIGENCE_ENDPOINT` | Your DI endpoint |
| `DOCUMENT_INTELLIGENCE_KEY` | Your DI key |
| `CHUNK_SIZE` | `1500` |
| `CHUNK_OVERLAP` | `200` |

For local development, copy `local.settings.example.json` to `local.settings.json` and replace the placeholders with valid storage and Document Intelligence settings. `AzureWebJobsStorage` and `DATA_STORAGE_CONNECTION` must be valid storage connection strings; the local Functions host needs storage for its host state and triggers. Keep `local.settings.json` out of Git.

With the project virtual environment activated, start the local host with:

```bash
func start --python
```

## Debug `QueueToSilver` locally

This local debug setup runs only the queue-triggered function. It reads the
existing Azure Storage queue using the private settings in
`local.settings.json`; it does not require an Event Grid tunnel. Stop the
deployed Function App while debugging so the Azure host does not compete for
the same queue message.

For the complete reproducible procedure, troubleshooting table, and verified
outputs, see [LOCAL-DEBUG-GUIDE.md](./LOCAL-DEBUG-GUIDE.md).

1. Install the development debugger dependency:

   ```bash
   python3.13 -m venv .venv-debug
   ./.venv-debug/bin/python -m pip install -r requirements-dev.txt
   ```

2. In VS Code, open this project folder and choose `.venv-debug/bin/python` as
   the interpreter for this debug session. Confirm `local.settings.json` has
   valid `AzureWebJobsStorage`,
   `DATA_STORAGE_CONNECTION`, and `DOCUMENT_QUEUE` values. Do not share this
   file; it contains secrets.
3. In Azure Portal, stop `func-b2s-setowq66u6xfi` temporarily. Its queue trigger
   can otherwise consume the test message before the local debugger does.
4. Open `pipeline.py` and set a breakpoint inside `queue_to_silver`, for
   example at the `log.info("PROCESS_STARTED ...")` line.
5. In VS Code, open **Terminal → New Terminal** and run this as Terminal 1:

   ```bash
   env PATH="$PWD/.venv-debug/bin:$PATH" \
     PYTHONPATH="$PWD/.venv-debug/lib/python3.13/site-packages/debugpy/_vendored/pydevd" \
     languageWorkers__python__arguments='-Xfrozen_modules=off -m debugpy --listen 127.0.0.1:9091' \
     func host start --functions QueueToSilver
   ```

   The `PYTHONPATH` entry makes the vendored debugger modules available to the
   Functions worker. Wait for the host to say it is ready; keep this terminal
   running.
6. Open **Run and Debug** in VS Code's left sidebar, select
   **Debug QueueToSilver locally** from the configuration dropdown, then press
   the green Start button (or **F5**) to attach the debugger.
7. Upload a small `.txt` file to `corpordrage` → `bronze` → `data/`, for
   example `data/debug.txt`.
8. In a second terminal at the project root, enqueue that uploaded blob for
   local processing:

   ```bash
   ./.venv-debug/bin/python -m scripts.enqueue_debug_message data/debug.txt
   ```

   This helper reads `local.settings.json`, checks the uploaded blob's ETag,
   and adds a queue message. It does not print credentials. PDF processing is
   refused by default because Document Intelligence may incur charges; only
   pass `--allow-pdf` when that usage is intended.
9. The debugger should stop at the breakpoint. Step through the download,
   extraction, chunking, and Silver upload. After processing, check the
   `silver` container for the outputs.
10. Stop the local host with **Ctrl+C** in Terminal 1 and stop debugging with
    **Shift+F5**. Restart the Azure Function App in
   the Portal when finished.

This procedure debugs `QueueToSilver`; it does not debug the initial
`BronzeToQueue` Event Grid delivery. The storage Event Grid subscription must
be correctly configured for that first stage to run automatically.

### Debugging errors and fixes

- `unrecognized arguments: - Generic.pdf`: quote the entire blob path because
  its name contains spaces:

  ```bash
  ./.venv-debug/bin/python -m scripts.enqueue_debug_message \
    "data/2222_3_1793991_1791793802_Databricks - Generic.pdf" --allow-pdf
  ```

- `BlobNotFound`: the helper only queues a blob that already exists in
  `bronze`. Upload the file first and check the exact case-sensitive path.
- `ModuleNotFoundError: No module named '_pydevd_bundle'`: run the host with
  the Python 3.13 debug environment and the `PYTHONPATH` shown above. Python
  3.14 in the original `.venv` did not work reliably for pausing this
  Functions worker at a breakpoint.
- Message disappears without a local breakpoint: confirm the Azure Function
  App is stopped, the local debugger is attached, and the breakpoint is in
  executable code. A queue message is consumed on processing; the local
  Function terminal can show `PROCESS_STARTED`, `BLOB_DOWNLOADED`,
  `EXTRACTED`, and `PROCESS_DONE`.
- Local host fails during startup: check that `local.settings.json` has valid
  `AzureWebJobsStorage`, `DATA_STORAGE_CONNECTION`, and `DOCUMENT_QUEUE`
  values. Do not paste these settings into chat or documentation.

## Install and publish

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
az login
az account set --subscription 'Azure subscription 1'
func azure functionapp publish func-b2s-setowq66u6xfi
```

Azure Functions Core Tools v4 and Azure CLI must be installed.

## IMPORTANT: configure Event Grid AFTER publishing

In **Azure Portal**:

1. Open the **storage account** configured by `DATA_STORAGE_CONNECTION`.
2. Open **Events → + Event Subscription**.
3. Name it `bronze-data-created` and select **Event Types: Blob Created** ONLY.
4. Set **Endpoint Type: Azure Function**; select subscription, resource group, Function App **`func-b2s-setowq66u6xfi`**, and function **`BronzeToQueue`**.
5. In **Filters**, specify **Subject begins with**:
   `/blobServices/default/containers/bronze/blobs/data/`
6. Create the subscription. The event is matched based on the Azure Storage event subject. Avoid subscribing to Silver output blobs.

This can also be configured from the storage account's `bronze` container Events page when available; keep the subject filter scoped to `data/`.

## Smoke test

1. Upload `data/example.txt` to blob container `bronze` using Azure Portal or Storage Explorer. Put some text inside.
2. Check Function App monitoring logs for `QUEUED blob=data/example.txt ...` and `PROCESS_DONE ...`.
3. Check `silver/` for a document+version directory containing `chunk_0001.md`, `chunk_0001.json`, `_complete.json`.
4. To test replacement, upload a file to the *same name* with different content. A new ETag and version folder should appear (old event can be skipped as stale).

Event Grid is at-least-once delivery; duplicate events or messages may happen, and the queue trigger may retry. The outputs are overwritten by deterministic version paths, but repeated extraction can incur costs. For production, introduce a durable per-blob-version processing claim and reconciliation/dead-letter recovery.

## Caveats

- `@bp.blob_trigger(source="EventGrid")` is **required** on Flex Consumption. A regular polling blob trigger isn't supported.
- The trigger path is explicitly `bronze/data/{name}`. If you change storage container/prefix, update the decorator AND redeploy, then update the Event Grid subject filter.
- Messages are plain JSON; `host.json` sets queue `messageEncoding` to `none` to match.
- The code uses shared-key connection strings; if your storage account disallows shared-key access, identity-based configuration and clients are needed.
- To use Event Grid locally you must arrange event delivery to a publicly accessible local endpoint/tunnel; deploying and testing in Azure is easiest. `func start` alone does not simulate Event Grid arrival events.
- PDF analysis is chargeable and size/time constraints depend on Azure services. `txt` is the simplest first test.
- Newly created files trigger the event; existing files from before Event Grid subscription aren't automatically replayed.

इस pipeline में तीन Azure SDK clients अलग-अलग काम के लिए इस्तेमाल हुए हैं: Blob Storage, Queue Storage, और Document Intelligence। मुख्य उपयोग pipeline.py में हैं।

BlobServiceClient — Blob Storage से files पढ़ना/लिखना
इसे connection string से बनाया जाता है:


फिर code में ये methods/properties इस्तेमाल होते हैं:

get_blob_client(container, name) — किसी एक blob का client पाना। उदाहरण: bronze container में source file का client।
get_container_client(container) — किसी container ka client पाना। उदाहरण: silver container में processed files लिखने के लिए।
url — storage account का URL, जिससे source blob का URL बनाया जाता है।
Blob client पर get_blob_properties() — blob की properties, जैसे ETag और metadata पाना।
Blob client पर download_blob(...).readall() — blob का पूरा content पढ़ना।
Container client पर upload_blob(...) — chunk और metadata files को upload करना।
QueueClient — Queue में processing message डालना
इसे connection string और queue name से बनाया जाता है:


send_message(...) — Queue में document की जानकारी वाला JSON message डालना। इससे आगे document processing शुरू हो सकती है।
Queue trigger के अंदर queue_message.get_body() और queue_message.id भी दिखते हैं। ये Azure Functions के QueueMessage object के methods/properties हैं—QueueClient ke nahi. get_body() message का content पढ़ता है और id log में message की पहचान के लिए इस्तेमाल होता है।

DocumentIntelligenceClient — PDF से content निकालना
Client को endpoint और credential से बनाया जाता है:


begin_analyze_document("prebuilt-layout", ...) — PDF को Azure Document Intelligence में analyze करने के लिए भेजता है। यहाँ "prebuilt-layout" document का layout समझने और content निकालने वाला model है।
इससे मिला poller.result() — analysis पूरा होने तक result प्राप्त करता है; code फिर उसका .content Markdown के रूप में लेता है।
Dummy flow: मान लें bronze container में report.pdf आया। Pipeline queue में उसका message डालती है; अगला function message पढ़कर Blob Storage से PDF download करता है; DocumentIntelligenceClient से PDF का text/Markdown निकालता है; फिर text को chunks में बाँटकर Blob Storage के silver container में .md और .json files upload करता है।