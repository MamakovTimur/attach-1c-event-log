from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import attach_event_log as engine


class PythonOperationStateTests(unittest.TestCase):
    def test_state_round_trip_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            state: dict[str, object] = {"phase": "prepared", "published_files": []}

            engine.write_operation_state(destination, state)
            loaded = engine.read_operation_state(destination)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["phase"], "prepared")
            self.assertEqual(loaded["schema_version"], engine.OPERATION_STATE_SCHEMA)
            self.assertIn("updated_at_utc", loaded)

            engine.remove_operation_state(destination)
            self.assertIsNone(engine.read_operation_state(destination))

    def test_corrupted_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            engine.operation_state_path(destination).write_text("{broken", "utf-8")

            with self.assertRaisesRegex(ValueError, "Повреждён журнал"):
                engine.read_operation_state(destination)


if __name__ == "__main__":
    unittest.main()
