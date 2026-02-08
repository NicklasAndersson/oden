"""Tests for the responses CRUD functions in config_db."""

import tempfile
import unittest
from pathlib import Path

from oden.config_db import (
    create_response,
    delete_response,
    get_all_responses,
    get_response_by_id,
    get_response_by_keyword,
    init_db,
    save_response,
)


class TestResponsesCRUD(unittest.TestCase):
    """Test CRUD operations for the responses table."""

    def setUp(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            self.db_path = Path(tmp.name)
        # Remove the file so init_db creates it fresh
        self.db_path.unlink(missing_ok=True)
        init_db(self.db_path)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_init_db_seeds_default_responses(self):
        """init_db should seed two default responses (help/hjälp and ok)."""
        responses = get_all_responses(self.db_path)
        self.assertEqual(len(responses), 2)
        keywords_sets = [set(r["keywords"]) for r in responses]
        self.assertIn({"help", "hjälp"}, keywords_sets)
        self.assertIn({"ok"}, keywords_sets)

    def test_get_response_by_keyword_hit(self):
        """Lookup by keyword should return the body text."""
        body = get_response_by_keyword(self.db_path, "help")
        self.assertIsNotNone(body)
        self.assertIn("Stund", body)

    def test_get_response_by_keyword_alias(self):
        """Both 'help' and 'hjälp' should return the same body."""
        body_help = get_response_by_keyword(self.db_path, "help")
        body_hjalp = get_response_by_keyword(self.db_path, "hjälp")
        self.assertEqual(body_help, body_hjalp)

    def test_get_response_by_keyword_case_insensitive(self):
        """Keyword lookup should be case-insensitive."""
        body = get_response_by_keyword(self.db_path, "HELP")
        self.assertIsNotNone(body)
        self.assertIn("Stund", body)

    def test_get_response_by_keyword_miss(self):
        """Lookup for a non-existent keyword should return None."""
        body = get_response_by_keyword(self.db_path, "nonexistent")
        self.assertIsNone(body)

    def test_get_response_by_keyword_nonexistent_db(self):
        """Lookup on a non-existent database should return None."""
        body = get_response_by_keyword(Path("/tmp/does_not_exist_12345.db"), "help")
        self.assertIsNone(body)

    def test_create_response(self):
        """Creating a new response should return a valid id."""
        new_id = create_response(self.db_path, ["test", "Test2"], "Test body")
        self.assertIsNotNone(new_id)
        self.assertIsInstance(new_id, int)

        # Verify it's retrievable
        resp = get_response_by_id(self.db_path, new_id)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["keywords"], ["test", "test2"])  # normalized to lowercase
        self.assertEqual(resp["body"], "Test body")

    def test_create_response_normalizes_keywords(self):
        """Keywords should be normalized to lowercase on create."""
        new_id = create_response(self.db_path, ["FOO", " Bar ", "baz"], "Body")
        resp = get_response_by_id(self.db_path, new_id)
        self.assertEqual(resp["keywords"], ["foo", "bar", "baz"])

    def test_create_response_empty_keywords_returns_none(self):
        """Creating with empty keywords should return None."""
        result = create_response(self.db_path, [], "Body")
        self.assertIsNone(result)

    def test_save_response(self):
        """Updating an existing response should change its keywords and body."""
        new_id = create_response(self.db_path, ["old"], "Old body")
        success = save_response(self.db_path, new_id, ["new", "NEW2"], "New body")
        self.assertTrue(success)

        resp = get_response_by_id(self.db_path, new_id)
        self.assertEqual(resp["keywords"], ["new", "new2"])
        self.assertEqual(resp["body"], "New body")

    def test_save_response_nonexistent_id(self):
        """Saving to a non-existent id should return False."""
        success = save_response(self.db_path, 99999, ["kw"], "Body")
        self.assertFalse(success)

    def test_delete_response(self):
        """Deleting a response should remove it from the database."""
        new_id = create_response(self.db_path, ["todelete"], "Delete me")
        success = delete_response(self.db_path, new_id)
        self.assertTrue(success)

        # Verify it's gone
        resp = get_response_by_id(self.db_path, new_id)
        self.assertIsNone(resp)
        body = get_response_by_keyword(self.db_path, "todelete")
        self.assertIsNone(body)

    def test_delete_response_nonexistent_id(self):
        """Deleting a non-existent id should return False."""
        success = delete_response(self.db_path, 99999)
        self.assertFalse(success)

    def test_get_all_responses_includes_new(self):
        """get_all_responses should include newly created responses."""
        initial_count = len(get_all_responses(self.db_path))
        create_response(self.db_path, ["extra"], "Extra body")
        responses = get_all_responses(self.db_path)
        self.assertEqual(len(responses), initial_count + 1)

    def test_get_response_by_id_miss(self):
        """Getting a non-existent id should return None."""
        resp = get_response_by_id(self.db_path, 99999)
        self.assertIsNone(resp)

    def test_json_each_query_with_multiple_keywords(self):
        """Each keyword in a multi-keyword response should match independently."""
        create_response(self.db_path, ["alpha", "beta", "gamma"], "Multi")
        body_a = get_response_by_keyword(self.db_path, "alpha")
        body_b = get_response_by_keyword(self.db_path, "beta")
        body_g = get_response_by_keyword(self.db_path, "gamma")
        self.assertEqual(body_a, "Multi")
        self.assertEqual(body_b, "Multi")
        self.assertEqual(body_g, "Multi")


class TestSchemaVersion(unittest.TestCase):
    """Test that schema migration bumps version to 2."""

    def test_schema_version_is_2(self):
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        db_path.unlink(missing_ok=True)
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = cursor.fetchone()
        conn.close()
        db_path.unlink(missing_ok=True)

        self.assertEqual(row[0], "2")

    def test_responses_table_exists(self):
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        db_path.unlink(missing_ok=True)
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='responses'")
        row = cursor.fetchone()
        conn.close()
        db_path.unlink(missing_ok=True)

        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
