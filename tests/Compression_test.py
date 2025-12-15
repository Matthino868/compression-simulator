import os
import json
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def write_config(path: Path, *, api_key="TESTKEY", device_id="DEV-1"):
    cfg = {
        "api_key": api_key,
        "deviceId": device_id,
        "deviceName": "SimMachine",
        "test_duration_seconds": 60,
        "list_of_licenses": [{"code": "LIC-AAA"}, {"code": "LIC-BBB"}],
        "tests": [
            {
                "test_number": 0,
                "status": "OK",
                "test_description": "T0",
                "specimen_code": "001",
                "specimen_description": "Spec0",
                "sample_reception_epoch_time": 1_000_000_000,
                "customer_id": 1,
                "test_status_code": "END",
                "stop_mode_id": 2,
                "list_of_channel_acquired_data": [],
            },
            {
                "test_number": 1,
                "status": "OK",
                "test_description": "T1",
                "specimen_code": "002",
                "specimen_description": "Spec1",
                "sample_reception_epoch_time": 1_000_000_000,
                "customer_id": 1,
                "test_status_code": "PAUSE",
                "stop_mode_id": None,
                "list_of_channel_acquired_data": [],
            },
        ],
    }
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


class JsonRpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an isolated temp folder because main.py reads config.json at import time.
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._old_cwd = os.getcwd()
        os.chdir(cls._tmpdir.name)

        write_config(Path("config.json"))

        # Import main AFTER writing config.json
        import main  # noqa: F401
        cls.main = importlib.reload(main)

        cls.client = TestClient(cls.main.app)
        cls.api_key = cls.main.API_KEY
        cls.device_id = cls.main.config.get("deviceId")

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._old_cwd)
        cls._tmpdir.cleanup()

    def rpc(self, method, params=None, req_id=1):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": req_id,
            "params": params or {},
        }
        r = self.client.post("/jsonrpc", json=payload)
        self.assertEqual(r.status_code, 200)
        return r.json()

    # ---- Verification methods ----
    def test_get_revision(self):
        res = self.rpc("getRevision", {}, 1)
        self.assertIn("result", res)
        self.assertEqual(res["result"], "0.3")

    def test_sqrt_ok(self):
        res = self.rpc("sqrt", {"x": 9}, 2)
        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(res["result"]["y"], 3.0)

    def test_sqrt_negative_error(self):
        res = self.rpc("sqrt", {"x": -1}, 3)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -1)

    # ---- API key gating ----
    def test_invalid_api_key_rejected(self):
        res = self.rpc("getListOfAllMachines", {"api_key": "WRONG"}, 10)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -401)

    # ---- Application methods ----
    def test_get_list_of_all_machines(self):
        res = self.rpc("getListOfAllMachines", {"api_key": self.api_key}, 11)
        self.assertEqual(res["result"]["status"], "OK")
        self.assertIn(self.device_id, res["result"]["list_of_all_device_ids"])

    def test_get_machine_identity_ok(self):
        res = self.rpc(
            "getMachineIdentity",
            {"api_key": self.api_key, "device_id": self.device_id},
            12,
        )
        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(res["result"]["machine_name"], "SimMachine")
        self.assertEqual(res["result"]["machine_type_id"], 256)
        self.assertEqual(res["result"]["list_of_license_codes"], ["LIC-AAA", "LIC-BBB"])

    def test_get_machine_identity_wrong_device(self):
        res = self.rpc(
            "getMachineIdentity",
            {"api_key": self.api_key, "device_id": "NOPE"},
            13,
        )
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -1)

    def test_get_list_of_all_tests(self):
        res = self.rpc(
            "getListOfAllTests",
            {"api_key": self.api_key, "device_id": self.device_id},
            14,
        )
        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(res["result"]["list_of_all_test_numbers"], [0, 1, 2])

    def test_get_test_info_and_status_marks_end_after_duration(self):
        # Set test 0 to RUN and old reception time so it should become END
        self.main.list_of_tests[0]["test_status_code"] = "RUN"
        self.main.list_of_tests[0]["sample_reception_epoch_time"] = 1_000_000_000

        # Now time is far later than + duration (60s)
        with patch.object(self.main.time, "time", return_value=1_000_000_000 + 10_000):
            res = self.rpc(
                "getTestInfoAndStatus",
                {"api_key": self.api_key, "device_id": self.device_id, "test_number": 0},
                20,
            )

        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(res["result"]["test_status_code"], "END")
        # confirm it persisted to in-memory structure
        self.assertEqual(self.main.list_of_tests[0]["test_status_code"], "END")

    def test_get_test_acquired_data_and_results(self):
        # Give test 1 some acquired data
        self.main.list_of_tests[1]["list_of_channel_acquired_data"] = [
            {"stage_name": "S", "sub_stage_index": 1, "channel_type": "Analog", "channel_index": 1, "list_of_data_points": []}
        ]
        res = self.rpc(
            "getTestAcquiredDataAndResults",
            {"api_key": self.api_key, "test_number": 1},
            21,
        )
        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(len(res["result"]["list_of_channel_acquired_data"]), 1)

    def test_clone_and_start_test_success(self):
        # Ensure the last test is not RUN (in our base config it's PAUSE)
        self.assertNotEqual(self.main.list_of_tests[-1]["test_status_code"], "RUN")

        # Make deterministic new test content
        with patch.object(self.main.time, "time", return_value=2_000_000_000), \
             patch.object(self.main.random, "uniform", return_value=75.0):
            res = self.rpc(
                "cloneAndStartTest",
                {
                    "api_key": self.api_key,
                    "device_id": self.device_id,
                    "test_number": 0,
                    "test_description": "Clone",
                    "specimen_code": "999",
                    "specimen_description": "Cloned",
                    "customer_id": 5,
                },
                30,
            )

        self.assertEqual(res["result"]["status"], "OK")
        new_num = res["result"]["new_test_number"]
        self.assertEqual(new_num, 2)  # started with 2 tests: 0,1 -> new is 2
        self.assertEqual(self.main.list_of_tests[new_num]["test_status_code"], "RUN")
        self.assertIn("list_of_channel_acquired_data", self.main.list_of_tests[new_num])

    def test_clone_and_start_test_reject_if_last_is_running(self):
        # Force "last test is RUN" to trigger the guard
        self.main.list_of_tests[-1]["test_status_code"] = "RUN"

        res = self.rpc(
            "cloneAndStartTest",
            {"api_key": self.api_key, "device_id": self.device_id, "test_number": 0},
            31,
        )
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -1)

        # Restore so other tests aren't affected
        self.main.list_of_tests[-1]["test_status_code"] = "PAUSE"

    def test_continue_test_only_from_pause(self):
        # test 1 starts as PAUSE
        with patch.object(self.main.time, "time", return_value=3_000_000_000):
            res = self.rpc(
                "continueTest",
                {"api_key": self.api_key, "device_id": self.device_id, "test_number": 1},
                40,
            )
        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(self.main.list_of_tests[1]["test_status_code"], "RUN")

    def test_stop_test_pauses_when_running_and_within_duration(self):
        # Make test 1 RUN and recent
        self.main.list_of_tests[1]["test_status_code"] = "RUN"
        self.main.list_of_tests[1]["sample_reception_epoch_time"] = 4_000_000_000

        with patch.object(self.main.time, "time", return_value=4_000_000_000 + 10):
            res = self.rpc(
                "stopTest",
                {"api_key": self.api_key, "device_id": self.device_id, "test_number": 1},
                50,
            )

        self.assertEqual(res["result"]["status"], "OK")
        self.assertEqual(self.main.list_of_tests[1]["test_status_code"], "PAUSE")

    def test_stop_test_not_stoppable_after_duration(self):
        self.main.list_of_tests[1]["test_status_code"] = "RUN"
        self.main.list_of_tests[1]["sample_reception_epoch_time"] = 5_000_000_000

        with patch.object(self.main.time, "time", return_value=5_000_000_000 + 10_000):
            res = self.rpc(
                "stopTest",
                {"api_key": self.api_key, "device_id": self.device_id, "test_number": 1},
                51,
            )

        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -1)
        # It also flips to END in your implementation
        self.assertEqual(self.main.list_of_tests[1]["test_status_code"], "END")


if __name__ == "__main__":
    unittest.main()
