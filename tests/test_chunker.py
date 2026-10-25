import unittest
from unittest.mock import Mock, patch

from pipeline import bronze_to_queue, document_name_from_event, split_text


class SplitTextTests(unittest.TestCase):
    def test_short(self):
        self.assertEqual(split_text("abc", 10, 2), ["abc"])

    def test_long_reconstructable(self):
        text = "abcdefghijklmnopqrstuvwxyz" * 10
        chunks = split_text(text, 40, 10)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(x) <= 40 for x in chunks))
        self.assertEqual(chunks[0], text[:40])

    def test_invalid_settings(self):
        with self.assertRaises(ValueError):
            split_text("hello", 3, 3)


class EventGridTests(unittest.TestCase):
    def make_event(self, subject, event_type="Microsoft.Storage.BlobCreated"):
        event = Mock()
        event.subject = subject
        event.event_type = event_type
        return event

    def test_supported_blob_created_event_returns_document_name(self):
        event = self.make_event(
            "/blobServices/default/containers/bronze/blobs/data/sample.TXT"
        )
        self.assertEqual(document_name_from_event(event), "data/sample.TXT")

    def test_ignores_wrong_container_or_prefix(self):
        event = self.make_event(
            "/blobServices/default/containers/silver/blobs/data/sample.txt"
        )
        self.assertIsNone(document_name_from_event(event))

    def test_ignores_unsupported_extension_and_event_type(self):
        unsupported_file = self.make_event(
            "/blobServices/default/containers/bronze/blobs/data/sample.csv"
        )
        deleted_blob = self.make_event(
            "/blobServices/default/containers/bronze/blobs/data/sample.txt",
            "Microsoft.Storage.BlobDeleted",
        )
        self.assertIsNone(document_name_from_event(unsupported_file))
        self.assertIsNone(document_name_from_event(deleted_blob))

    @patch("pipeline.clients")
    def test_blob_created_event_is_queued(self, clients):
        blob_service = Mock()
        blob_service.url = "https://storage.example"
        source = blob_service.get_blob_client.return_value
        source.get_blob_properties.return_value.etag = '"etag-value"'
        source.get_blob_properties.return_value.metadata = {}
        queue = Mock()
        clients.return_value = blob_service, queue
        event = self.make_event(
            "/blobServices/default/containers/bronze/blobs/data/sample.txt"
        )

        bronze_to_queue(event)

        self.assertEqual(queue.send_message.call_count, 1)
        self.assertIn('"blob_name": "data/sample.txt"', queue.send_message.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
