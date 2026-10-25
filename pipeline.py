"""Bronze -> Azure Storage Queue -> Silver (Python v2 Azure Functions)."""
import hashlib
import io
import json
import logging
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

import azure.functions as func
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient

bp = func.Blueprint()
log = logging.getLogger("bronze_to_silver")


def setting(name, default=None):
    value = os.getenv(name, default)
    if value is None or value == "":
        raise ValueError(f"Missing app setting: {name}")
    return value


def clients():
    connection = setting("DATA_STORAGE_CONNECTION")
    return BlobServiceClient.from_connection_string(connection), QueueClient.from_connection_string(
        connection, queue_name=setting("DOCUMENT_QUEUE", "bronze-to-silver")
    )


def blob_url(blob_service, container, name):
    return f"{blob_service.url}/{container}/{quote(name, safe='/')}"


def document_name_from_event(event: func.EventGridEvent) -> str | None:
    if event.event_type != "Microsoft.Storage.BlobCreated":
        return None
    prefix = "/blobServices/default/containers/bronze/blobs/"
    if not event.subject.startswith(prefix):
        return None
    document_name = event.subject[len(prefix):]
    if not document_name.startswith("data/") or not document_name.lower().endswith((".pdf", ".txt", ".md")):
        return None
    return document_name


@bp.function_name(name="BronzeToQueue")
@bp.event_grid_trigger(arg_name="event")
def bronze_to_queue(event: func.EventGridEvent) -> None:
    """Event Grid trigger: enqueue supported files created under bronze/data/."""
    try:
        document_name = document_name_from_event(event)
        if document_name is None:
            log.info("IGNORED_EVENT subject=%s event_type=%s", event.subject, event.event_type)
            return

        blob_service, queue = clients()
        source = blob_service.get_blob_client("bronze", document_name)
        props = source.get_blob_properties()
        etag = str(props.etag)
        message = {
            "document_id": PurePosixPath(document_name).stem,
            "document_url": blob_url(blob_service, "bronze", document_name),
            "container": "bronze",
            "blob_name": document_name,
            "etag": etag,
            "metadata": props.metadata or {},
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        queue.send_message(json.dumps(message))
        log.info("QUEUED blob=%s etag=%s", document_name, etag)
    except ResourceNotFoundError:
        # A create event can arrive after the blob has already been deleted.
        log.warning("SOURCE_NOT_FOUND subject=%s", event.subject)
    except Exception:
        log.error("ENQUEUE_FAILED traceback=%s", traceback.format_exc())
        raise


def extract_markdown(raw: bytes, extension: str) -> str:
    if extension in (".txt", ".md"):
        return raw.decode("utf-8-sig")
    if extension != ".pdf":
        raise ValueError(f"Unsupported file type: {extension}")
    di = DocumentIntelligenceClient(
        endpoint=setting("DOCUMENT_INTELLIGENCE_ENDPOINT"),
        credential=AzureKeyCredential(setting("DOCUMENT_INTELLIGENCE_KEY")),
    )
    poller = di.begin_analyze_document(
        "prebuilt-layout", body=io.BytesIO(raw),
        output_content_format=DocumentContentFormat.MARKDOWN,
    )
    return poller.result().content or ""


def split_text(text: str, chunk_size=1500, overlap=200):
    """Basic character chunker for demonstration; not semantic/token-aware."""
    if chunk_size <= overlap or overlap < 0:
        raise ValueError("CHUNK_SIZE must exceed CHUNK_OVERLAP >= 0")
    output = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start + chunk_size // 2, end)
            if split_at > start:
                end = split_at + 1
        output.append(text[start:end])
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return output


@bp.function_name(name="QueueToSilver")
@bp.queue_trigger(arg_name="queue_message", queue_name="%DOCUMENT_QUEUE%", connection="DATA_STORAGE_CONNECTION")
def queue_to_silver(queue_message: func.QueueMessage) -> None:
    """Process queue messages, output versioned markdown chunks + JSON metadata."""
    document_name = "unknown"
    try:
        message = json.loads(queue_message.get_body().decode("utf-8"))
        document_name = message["blob_name"]
        source_container = message["container"]
        source_etag = message["etag"]
        log.info("PROCESS_STARTED blob=%s message_id=%s", document_name, queue_message.id)
        blob_service, _ = clients()
        source = blob_service.get_blob_client(source_container, document_name)
        props = source.get_blob_properties()
        if str(props.etag) != source_etag:
            # The newer blob creation event queues the replacement version separately.
            log.warning("STALE_MESSAGE blob=%s expected=%s actual=%s", document_name, source_etag, props.etag)
            return
        raw = source.download_blob(etag=source_etag, match_condition=MatchConditions.IfNotModified).readall()
        log.info("BLOB_DOWNLOADED blob=%s bytes=%d", document_name, len(raw))
        markdown = extract_markdown(raw, PurePosixPath(document_name).suffix.lower())
        if not markdown.strip():
            raise ValueError("Document extraction returned empty content")
        chunks = split_text(markdown, int(setting("CHUNK_SIZE", "1500")), int(setting("CHUNK_OVERLAP", "200")))
        silver = blob_service.get_container_client(setting("SILVER_CONTAINER", "silver"))
        safe_id = re.sub(r"[^a-zA-Z0-9._-]", "_", message["document_id"])
        source_id = hashlib.sha256(f"{source_container}/{document_name}".encode()).hexdigest()[:12]
        version = hashlib.sha256(source_etag.encode()).hexdigest()[:12]
        prefix = f"{safe_id}-{source_id}/{version}"
        log.info("EXTRACTED blob=%s chunks=%d prefix=%s", document_name, len(chunks), prefix)
        for i, chunk in enumerate(chunks, start=1):
            base = f"{prefix}/chunk_{i:04d}"
            metadata = {
                "document_id": message["document_id"],
                "source_url": message["document_url"],
                "source_blob": document_name,
                "source_etag": source_etag,
                "chunk_index": i,
                "chunk_count": len(chunks),
                "source_metadata": message.get("metadata", {}),
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
            silver.upload_blob(name=base + ".md", data=chunk.encode("utf-8"), overwrite=True)
            silver.upload_blob(name=base + ".json", data=json.dumps(metadata, indent=2).encode("utf-8"), overwrite=True)
        silver.upload_blob(
            name=f"{prefix}/_complete.json",
            data=json.dumps({"source_etag": source_etag, "chunk_count": len(chunks), "completed_at": datetime.now(timezone.utc).isoformat()}),
            overwrite=True,
        )
        log.info("PROCESS_DONE blob=%s chunks=%d", document_name, len(chunks))
    except Exception:
        log.error("PROCESS_FAILED blob=%s traceback=%s", document_name, traceback.format_exc())
        raise  # important: triggers queue retry / poison queue
