
import json

from langchain_core.tools import tool

from backend.validator import validate_query
from backend.database_tool import run_database_query


@tool
def query_velodb(query: str) -> str:
    """
    Execute a validated, read-only VeloDB query.
    The query must be provided as JSON using the query contract.
    """
    try:
        query_data = json.loads(query)
    except json.JSONDecodeError as error:
        print("[DEBUG] Invalid JSON query:", repr(error))
        return "invalid query format"

    print("[DEBUG] Query received by query_velodb:")
    print(json.dumps(query_data, indent=2, default=str))

    # Diagnose validation failures without bypassing validation.
    try:
        is_valid = validate_query(query_data)
    except Exception as error:
        print("[DEBUG] Validator raised an exception:", repr(error))
        return f"query validation failed: {error}"

    if not is_valid:
        print("[DEBUG] QUERY VALIDATION FAILED")
        print("[DEBUG] Collection:", query_data.get("collection"))
        print("[DEBUG] Operation:", query_data.get("operation"))
        print("[DEBUG] Filters:", query_data.get("filters"))
        print("[DEBUG] Fields:", query_data.get("fields"))

        return (
            "query validation failed: the contract did not pass validation. "
            "Check that the table and every column exist in the schema, that "
            "the operation is one of find/count/distinct/aggregate, and that "
            "aggregate uses a pipeline instead of the filters property."
        )

    try:
        result = run_database_query(query_data)
        print("[DEBUG] Database query executed successfully.")
        return json.dumps(result, default=str)
    except Exception as error:
        # The real reason goes back to the model: its repair attempt is only
        # as good as the error it is shown. Under MongoDB this was a fixed
        # string, so the model was effectively repairing blind.
        print("[DEBUG] Database execution failed:", repr(error))
        return f"database execution failed: {error}"


# The tool was called query_mongodb before the VeloDB migration. The alias
# keeps any older import working.
query_mongodb = query_velodb
