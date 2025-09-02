import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import threading
import random

logger = logging.getLogger(__name__)

class QueryExecutionError(Exception):
    pass

class QueryExecutor:
    def __init__(self, max_workers: int = 10, timeout: int = 30, max_retries: int = 3, error_rate: float = 0.05):
        self.max_workers = max_workers
        self.timeout = timeout
        self.max_retries = max_retries
        self.error_rate = error_rate
        self._lock = threading.Lock()

    def execute_subqueries(self, subqueries: List[Dict[str, Any]],
                          parallel: bool = False) -> Dict[str, Any]:
        if not subqueries:
            logger.warning("No subqueries provided for execution")
            return {
                "results": [],
                "summary": {
                    "success": 0,
                    "failure": 0,
                    "total": 0
                }
            }

        if not isinstance(subqueries, list):
            raise QueryExecutionError("Subqueries must be provided as a list")

        logger.info(f"Starting execution of {len(subqueries)} subqueries (parallel={parallel})")

        if parallel and len(subqueries) > 1:
            results = self._execute_parallel(subqueries)
        else:
            results = self._execute_sequential(subqueries)

        if not self._validate_execution_results(results):
            raise QueryExecutionError("Execution results failed schema validation")

        summary = self._generate_summary(results)
        self._log_execution_summary(summary)

        return {
            "results": results,
            "summary": summary
        }

    def _execute_sequential(self, subqueries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for subquery in subqueries:
            result = self._execute_single_subquery(subquery)
            results.append(result)
        return results

    def _execute_parallel(self, subqueries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = [None] * len(subqueries)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {
                executor.submit(self._execute_single_subquery, subquery): idx
                for idx, subquery in enumerate(subqueries)
            }

            try:
                for future in as_completed(future_to_index, timeout=self.timeout):
                    idx = future_to_index[future]
                    try:
                        with self._lock:
                            results[idx] = future.result()
                    except Exception as e:
                        logger.error(f"Parallel execution failed for subquery at index {idx}: {e}")
                        with self._lock:
                            results[idx] = self._create_error_result(
                                subqueries[idx],
                                f"Parallel execution error: {str(e)}"
                            )
            except TimeoutError:
                logger.error(f"Parallel execution timed out after {self.timeout}s")
                for future, idx in future_to_index.items():
                    if not future.done():
                        with self._lock:
                            if results[idx] is None:
                                results[idx] = self._create_error_result(
                                    subqueries[idx],
                                    f"Execution timed out after {self.timeout}s"
                                )

        return results

    def _execute_single_subquery(self, subquery: Dict[str, Any]) -> Dict[str, Any]:
        subquery_id = subquery.get("subquery_id", f"unknown_{id(subquery)}")
        plan_id = subquery.get("plan_id", "unknown")
        intent = subquery.get("intent", "unknown")
        action = subquery.get("action", "unknown")
        parameters = subquery.get("parameters", {})

        result = {
            "subquery_id": subquery_id,
            "plan_id": plan_id,
            "intent": intent,
            "status": "failure",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {},
            "error": None
        }

        logger.info(f"Executing subquery {subquery_id} with action '{action}'")

        for attempt in range(self.max_retries):
            try:
                start_time = time.perf_counter()

                execution_data = self._simulate_execution(action, parameters)
                execution_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

                result.update({
                    "status": "success",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": {
                        **execution_data,
                        "execution_metadata": {
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "duration_ms": execution_duration_ms,
                            "simulated": True,
                            "attempt": attempt + 1
                        }
                    }
                })

                logger.info(f"Successfully executed subquery {subquery_id} in {execution_duration_ms}ms (attempt {attempt + 1})")
                return result

            except Exception as e:
                error_message = str(e)

                if attempt == self.max_retries - 1:
                    result.update({
                        "status": "failure",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "error": f"Failed after {self.max_retries} attempts: {error_message}"
                    })
                    logger.error(f"Failed to execute subquery {subquery_id} after {self.max_retries} attempts: {error_message}")
                    return result
                else:
                    logger.warning(f"Attempt {attempt + 1} failed for subquery {subquery_id}: {error_message}. Retrying...")
                    base_delay = 0.1 * (2 ** attempt)
                    jitter = random.uniform(0, 0.05)
                    time.sleep(base_delay + jitter)

        return result

    def _simulate_execution(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        time.sleep(0.01)

        if random.random() < self.error_rate:
            raise Exception("Simulated transient error")

        return {
            "executed_action": action,
            "input_parameters": parameters,
            "result_count": len(parameters.get("query", "")) if "query" in parameters else 1
        }

    def _create_error_result(self, subquery: Dict[str, Any], error_message: str) -> Dict[str, Any]:
        return {
            "subquery_id": subquery.get("subquery_id", f"unknown_{id(subquery)}"),
            "plan_id": subquery.get("plan_id", "unknown"),
            "intent": subquery.get("intent", "unknown"),
            "status": "failure",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {},
            "error": error_message
        }

    def _validate_execution_results(self, results: List[Dict[str, Any]]) -> bool:
        if not results:
            return True

        required_fields = {"subquery_id": str, "plan_id": str, "intent": str,
                          "status": str, "timestamp": str, "data": dict}
        valid_statuses = {"success", "failure"}
        validation_errors = []

        for i, result in enumerate(results):
            if not isinstance(result, dict):
                validation_errors.append(f"Result {i} is not a dictionary")
                continue

            for field, expected_type in required_fields.items():
                if field not in result:
                    validation_errors.append(f"Result {i} missing required field '{field}'")
                elif not isinstance(result[field], expected_type):
                    validation_errors.append(f"Result {i} field '{field}' has wrong type")

            if result.get("status") not in valid_statuses:
                validation_errors.append(f"Result {i} has invalid status: {result.get('status')}")

            try:
                datetime.fromisoformat(result.get("timestamp", "").replace("Z", ""))
            except (ValueError, AttributeError):
                validation_errors.append(f"Result {i} has invalid timestamp format")

            if result.get("status") == "failure" and not result.get("error"):
                validation_errors.append(f"Result {i} has failure status but no error message")

        if validation_errors:
            error_msg = "Validation failed:\n" + "\n".join(validation_errors)
            logger.error(error_msg)
            raise QueryExecutionError(error_msg)

        return True

    def _generate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, int]:
        success_count = sum(1 for r in results if r["status"] == "success")
        failure_count = len(results) - success_count

        return {
            "success": success_count,
            "failure": failure_count,
            "total": len(results)
        }

    def _log_execution_summary(self, summary: Dict[str, int]) -> None:
        success_count = summary["success"]
        failure_count = summary["failure"]
        total_count = summary["total"]

        if failure_count == 0:
            logger.info(f"Successfully executed all {total_count} subqueries")
        elif success_count == 0:
            logger.warning(f"All {total_count} subqueries failed")
        else:
            logger.info(f"Executed {total_count} subqueries: {success_count} succeeded, {failure_count} failed")


def execute_subqueries(subqueries: List[Dict[str, Any]],
                      parallel: bool = False,
                      max_workers: int = 10,
                      timeout: int = 30,
                      max_retries: int = 3,
                      error_rate: float = 0.05) -> Dict[str, Any]:
    executor = QueryExecutor(max_workers=max_workers, timeout=timeout,
                           max_retries=max_retries, error_rate=error_rate)
    return executor.execute_subqueries(subqueries, parallel=parallel)


def validate_execution_results(results: List[Dict[str, Any]]) -> bool:
    executor = QueryExecutor()
    try:
        return executor._validate_execution_results(results)
    except QueryExecutionError:
        return False