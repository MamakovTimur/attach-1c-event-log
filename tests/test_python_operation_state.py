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

    def test_changed_source_cannot_resume_previous_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            destination = root / "dst"
            source.mkdir()
            destination.mkdir()
            (source / "1Cv8.lgf").write_bytes(b"dictionary")
            (destination / "1Cv8.lgf").write_bytes(b"receiver")
            name = "20260101000000.lgp"
            (source / name).write_bytes(b"first")
            old_request = engine.operation_request_signature(
                source,
                destination,
                "merge",
                [(name, None)],
            )
            engine.write_operation_state(
                destination,
                {
                    "request": old_request,
                    "phase": "partial",
                    "rollback_file": None,
                    "published_files": [name],
                    "completed_files": [name],
                    "uncertain_files": [],
                    "current_file": None,
                },
            )
            (source / name).write_bytes(b"changed source")
            with self.assertRaisesRegex(ValueError, "изменился во время операции"):
                engine.verify_source_file_unchanged(
                    old_request,
                    name,
                    source / name,
                )
            new_request = engine.operation_request_signature(
                source,
                destination,
                "merge",
                [(name, None)],
            )

            with self.assertRaisesRegex(ValueError, "другими параметрами"):
                engine.recover_operation_state(
                    destination,
                    destination / "1Cv8.lgf",
                    new_request,
                )


if __name__ == "__main__":
    unittest.main()
