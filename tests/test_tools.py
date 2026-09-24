"""Offline tests for the notion-page-tools handlers.

No network access and no Notion writes: urlopen is replaced with a fake.

Run with:  python ~/.hermes/plugins/notion-page-tools/tests/test_tools.py
"""

import importlib.util
import json
import os
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent / "tools.py"
spec = importlib.util.spec_from_file_location("notion_page_tools_tools", MODULE_PATH)
tools = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tools)


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode()

    def read(self, _limit=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeNotion:
    def __init__(self):
        self.in_trash = False
        self.title = "Pagina di prova"
        self.calls = []

    def page(self):
        return {
            "object": "page",
            "id": "12345678-1234-1234-1234-123456789abc",
            "url": "https://www.notion.so/test",
            "in_trash": self.in_trash,
            "last_edited_time": "2026-08-29T10:00:00.000Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": self.title}],
                }
            },
            "parent": {"type": "workspace", "workspace": True},
        }

    def open(self, request, timeout):
        self.calls.append((request.method, request.full_url, timeout))
        if request.method == "GET":
            return FakeResponse(200, self.page())
        if request.method == "PATCH":
            payload = json.loads(request.data.decode())
            self.in_trash = payload["in_trash"]
            return FakeResponse(200, self.page())
        raise AssertionError(request.method)


class NotionPageToolsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNotion()
        tools._PENDING.clear()
        self.old_key = os.environ.get("NOTION_API_KEY")
        os.environ["NOTION_API_KEY"] = "test-token"
        self.old_urlopen = tools.urlopen
        tools.urlopen = self.fake.open

    def tearDown(self):
        tools.urlopen = self.old_urlopen
        tools._PENDING.clear()
        if self.old_key is None:
            os.environ.pop("NOTION_API_KEY", None)
        else:
            os.environ["NOTION_API_KEY"] = self.old_key

    def test_trash_requires_preview_then_verifies_write(self):
        page_id = "12345678123412341234123456789abc"
        preview = json.loads(tools.trash_page({"page_id": page_id}))
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(preview["page"]["title"], "Pagina di prova")
        token = preview["confirmation_token"]

        result = json.loads(
            tools.trash_page(
                {
                    "page_id": page_id,
                    "confirmation_token": token,
                    "expected_title": "Pagina di prova",
                }
            )
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["page"]["in_trash"])
        self.assertEqual(
            [call[0] for call in self.fake.calls], ["GET", "GET", "PATCH", "GET"]
        )

    def test_restore_uses_a_new_confirmation_token(self):
        self.fake.in_trash = True
        page_id = "12345678-1234-1234-1234-123456789abc"
        preview = json.loads(tools.restore_page({"page_id": page_id}))
        result = json.loads(
            tools.restore_page(
                {
                    "page_id": page_id,
                    "confirmation_token": preview["confirmation_token"],
                }
            )
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["page"]["in_trash"])

    def test_token_is_single_use(self):
        page_id = "12345678-1234-1234-1234-123456789abc"
        preview = json.loads(tools.trash_page({"page_id": page_id}))
        token = preview["confirmation_token"]
        json.loads(tools.trash_page({"page_id": page_id, "confirmation_token": token}))
        replay = json.loads(
            tools.trash_page({"page_id": page_id, "confirmation_token": token})
        )
        self.assertFalse(replay["success"])
        self.assertEqual(replay["stage"], "confirmation")

    def test_token_does_not_transfer_to_another_page(self):
        preview = json.loads(
            tools.trash_page({"page_id": "12345678-1234-1234-1234-123456789abc"})
        )
        stolen = json.loads(
            tools.trash_page(
                {
                    "page_id": "aaaaaaaa-1234-1234-1234-123456789abc",
                    "confirmation_token": preview["confirmation_token"],
                }
            )
        )
        self.assertFalse(stolen["success"])
        self.assertEqual(stolen["stage"], "confirmation")

    def test_invalid_page_id_does_not_call_api(self):
        result = json.loads(tools.trash_page({"page_id": "not-a-page"}))
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "validation")
        self.assertEqual(self.fake.calls, [])

    def test_missing_credential_is_reported_without_leaking(self):
        os.environ.pop("NOTION_API_KEY", None)
        result = json.loads(
            tools.trash_page({"page_id": "12345678-1234-1234-1234-123456789abc"})
        )
        self.assertFalse(result["success"])
        self.assertIn("NOTION_API_KEY", result["error"])


if __name__ == "__main__":
    unittest.main()
