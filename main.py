from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Union, Optional, List
import math
import time
import uvicorn
import random
import json

with open("config.json", "r") as f:
    config = json.load(f)
list_of_tests = config["tests"]
print(f"Loaded {len(list_of_tests)} tests from config.")
app = FastAPI(title="SmartLab Gateway Simulator")

API_KEY = config.get("api_key", "CHANGE-ME-SOON")


# JSON-RPC request format
class JsonRpcRequest(BaseModel):
    jsonrpc: str
    method: str
    id: Union[str, int]
    params: Optional[Dict[str, Any]] = None


# JSON-RPC response helper
def jsonrpc_response(id: Union[str, int], result: Any = None, error: Optional[Dict[str, Any]] = None):
    if error:
        return {"jsonrpc": "2.0", "id": id, "error": error}
    print(f"Response result: {result}")
    return {"jsonrpc": "2.0", "id": id, "result": result}

def check_api_key(params: Dict[str, Any], req_id: Union[str, int]):
    if params.get("api_key") != API_KEY:
        return jsonrpc_response(req_id, error={"code": -1, "message": "Wrong api_key", "data": {
            "class": "Error",
            "jsonAdapterVersion": "0.1",
            "cadmoVersion": "Cadmo v3.2123",
            "stacks": ""
        }})
    return None

@app.post("/jsonrpc")
async def jsonrpc_handler(req: JsonRpcRequest):
    print(f"Received request: {req}")
    method = req.method
    params = req.params or {}
    print(f"Method: {req.method}, Params: {params}")
    try:
        # --- Verification methods ---
        if method == "getRevision":
            return jsonrpc_response(req.id, "0.3")

        elif method == "sqrt":
            x = params.get("x")
            if x is None or x < 0:
                return jsonrpc_response(req.id, error={
                    "code": -1,
                    "message": "Error in doSqrt: sqrt is only applicable to non-negative values"
                })
            return jsonrpc_response(req.id, {"status": "OK", "y": math.sqrt(x)})

        if params.get("api_key") != API_KEY:
            return jsonrpc_response(req.id, error={"code": -401, "message": "Invalid API key"})
        # --- Application methods ---
        elif method == "getListOfAllMachines":
            return jsonrpc_response(req.id, {
                "status": "OK",
                "list_of_all_device_ids": [config.get("deviceId"), "756200G-0E-0028000C", "28XYPP-05-00470034"]
            })

        elif method == "getMachineIdentity":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            return jsonrpc_response(req.id, {
                "status": "OK",
                "machine_name": config.get("deviceName"),
                "machine_type_id": 256, # Compression machine
                "list_of_license_codes": [license.get("code") for license in config.get("list_of_licenses")],
            })

        elif method == "getMachineStatus":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            return jsonrpc_response(req.id, {"status": "OK", "machine_status_id": 2})

        elif method == "getListOfAllTests":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            return jsonrpc_response(req.id, {
                "status": "OK",
                "list_of_all_test_numbers": [test.get("test_number") for test in list_of_tests]
            })

        elif method == "getListOfAllTestsBySpecimenCode":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            specimen_code = params.get("specimen_code")
            matching_tests = [test for test in list_of_tests if test.get("specimen_code") == specimen_code]
            if not matching_tests:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"No tests found for specimen code {specimen_code}"})
            return jsonrpc_response(req.id, {
                "status": "OK",
                "message": "Method not implemented yet",
            })

        elif method == "getTestInfoAndStatus":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})

            if test["test_status_code"] == "RUN" and int(time.time()) - test["sample_reception_epoch_time"] >= config.get("test_duration_seconds"):
                test["test_status_code"] = "END"
                test["stop_mode_id"] = 2
            
            with open("config.json", "w") as f:
                config["tests"] = list_of_tests
                json.dump(config, f, indent=2)

            return jsonrpc_response(req.id, {
                "status": "OK", 
                "test_description": test["test_description"], 
                "specimen_code": test["specimen_code"],
                "specimen_description": test["specimen_description"], 
                "sample_reception_epoch_time": test["sample_reception_epoch_time"],
                "customer_id": test["customer_id"], 
                "test_status_code": test["test_status_code"]
            })

        elif method == "getCustomer":
            return jsonrpc_response(req.id, {
                "status": "OK", "description": "PNN Scavi SRL", "address": "123 Test Street",
                "phone1": "000111222", "phone2": None, "email": "test@example.com",
                "contact1": "John Doe", "contact2": None, "annotation": None
            })

        elif method == "getListOfAllCustomers":
            return jsonrpc_response(req.id, {"status": "OK", "list_of_all_customers": [1, 2, 3, 4]})

        elif method == "getTestAcquisitionSettings":
            if(params.get("device_id") != config.get("deviceId")):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})
            return jsonrpc_response(req.id, {
                "status": "OK", "profile_id": 1, "list_of_stages": "Not implemented yet"
            })

        elif method == "getTestAcquiredDataAndResults":
            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})

            if test["test_status_code"] == "RUN" and int(time.time()) - test["sample_reception_epoch_time"] >= config.get("test_duration_seconds"):
                test["test_status_code"] = "END"
                test["stop_mode_id"] = 2

            with open("config.json", "w") as f:
                config["tests"] = list_of_tests
                json.dump(config, f, indent=2)

            list_of_channel_acquired_data = test.get("list_of_channel_acquired_data", [])
            return jsonrpc_response(req.id, {
                "status": "OK", "list_of_channel_acquired_data": list_of_channel_acquired_data, "stop_mode_id": test.get("stop_mode_id")
            })

        elif method == "cloneAndStartTest":
            if params.get("device_id") != config.get("deviceId"):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})

            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})
            
            new_test_number = len(list_of_tests)
            if list_of_tests[new_test_number - 1]["test_status_code"] == "RUN":
                return jsonrpc_response(req.id, error={"code": -1, "message": "Cannot clone a running test"})

            maxNewton = random.uniform(50, 100)
            print(f"Max Newton for this test: {maxNewton}")
            results_data = []

            for x in range(0, 100_00, 5):
                x = x/100
                y = x if x < maxNewton else -x + (maxNewton * 2)
                results_data.append({"delta_t": x, "value": y})

            new_test = {
                "test_number": new_test_number,
                "status": "OK",
                "test_description": params.get("test_description", "Cloned Test"),
                "specimen_code": params.get("specimen_code", "001"),
                "specimen_description": params.get("specimen_description", "Cloned Specimen"),
                "sample_reception_epoch_time": int(time.time()),
                "customer_id": params.get("customer_id", 1),
                "test_status_code": "RUN",
                "list_of_channel_acquired_data": [{
                    "stage_name": "COMPRESSION_STAGE",
                    "sub_stage_index": 1,
                    "channel_type": "Analog",
                    "channel_index": 1,
                    "list_of_data_points": results_data
                }],
            }
            list_of_tests.append(new_test)

            with open("config.json", "w") as f:
                config["tests"] = list_of_tests
                json.dump(config, f, indent=2)
                
            return jsonrpc_response(req.id, {"status":"OK","new_test_number": new_test_number})

        elif method == "continueTest":
            if params.get("device_id") != config.get("deviceId"):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})
            
            if test["test_status_code"] != "PAUSE":
                return jsonrpc_response(req.id, error={"code": -1, "status": f"TEST NOT IN PAUSE"})
                     
            test["test_status_code"] = "RUN"
            test["sample_reception_epoch_time"] = int(time.time())
            with open("config.json", "w") as f:
                config["tests"] = list_of_tests
                json.dump(config, f, indent=2)
                        
            return jsonrpc_response(req.id, {"status": "OK"})

        elif method == "stopTest":
            if params.get("device_id") != config.get("deviceId"):
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Device ID {params.get('device_id')} not found"})
            test_number = params.get("test_number")
            test = next((t for t in list_of_tests if t["test_number"] == test_number), None)
            if not test:
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} not found"})
            
            if test["test_status_code"] != "RUN":
                return jsonrpc_response(req.id, error={"code": -1, "message": f"Test number {test_number} is not running"})
            
            if int(time.time()) - test["sample_reception_epoch_time"] >= config.get("test_duration_seconds"):
                test["test_status_code"] = "END"
                test["stop_mode_id"] = 2
                return jsonrpc_response(req.id, error={"code": -1, "status": f"TEST NOT STOPPABLE"})

            test["test_status_code"] = "PAUSE"
            with open("config.json", "w") as f:
                config["tests"] = list_of_tests
                json.dump(config, f, indent=2)
                        
            return jsonrpc_response(req.id, {"status": "OK"})

        # --- Unknown method ---
        else:
            return jsonrpc_response(req.id, error={"code": -32601, "message": f"Method {method} not implemented"})

    except Exception as e:
        return jsonrpc_response(req.id, error={"code": -32000, "message": str(e)})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)