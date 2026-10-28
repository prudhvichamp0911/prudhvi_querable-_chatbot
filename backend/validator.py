from backend.schema_discovery import get_schema


ALLOWED_OPERATIONS = {"find", "count", "distinct", "aggregate"}

ALLOWED_FILTER_OPERATORS = {
    "$eq", "$ne", "$gt", "$gte", "$lt", "$lte",
    "$in", "$nin", "$regex", "$options", "$exists",
    "$and", "$or", "$nor", "$not",
}

ALLOWED_PIPELINE_STAGES = {
    "$match", "$group", "$sort", "$limit", "$skip", "$project",
}
# $unwind, $facet and $lookup were dropped in the VeloDB migration:
# the business tables are flat (no arrays to unwind) and the compiler
# emits a single-table SELECT. A query using them is rejected here with
# a clear reason rather than failing later in SQL.

ALLOWED_GROUP_OPERATORS = {
    "$sum", "$avg", "$min", "$max", "$count",
}

ALLOWED_EXPRESSION_OPERATORS = {
    "$add", "$subtract", "$multiply", "$divide",
    "$ifNull", "$cond", "$toDouble", "$toInt",
    "$round", "$abs", "$concat", "$toString", "$arrayElemAt",
}


def get_available_schema():
    try:
        schema = get_schema()
        return schema if isinstance(schema, dict) else {}
    except Exception:
        return {}


def validate_collection(collection_name):
    return (
        isinstance(collection_name, str)
        and collection_name in get_available_schema()
    )


def validate_fields(collection_name, fields):
    schema = get_available_schema()

    if collection_name not in schema or not isinstance(fields, list):
        return False

    available_fields = schema[collection_name]

    return all(
        isinstance(field, str)
        and field != "_id"
        and field.split(".", 1)[0] in available_fields
        for field in fields
    )


def validate_filter_expression(expression, available_fields):
    if not isinstance(expression, dict):
        return False

    for key, value in expression.items():
        if not isinstance(key, str):
            return False

        if key in {"$and", "$or", "$nor"}:
            if not isinstance(value, list) or not value:
                return False

            if not all(
                validate_filter_expression(item, available_fields)
                for item in value
            ):
                return False

        elif key.startswith("$"):
            if key not in ALLOWED_FILTER_OPERATORS:
                return False

            if key == "$not":
                if not isinstance(value, dict):
                    return False

                if not validate_filter_expression(value, available_fields):
                    return False

        else:
            root_field = key.split(".", 1)[0]

            if root_field not in available_fields:
                return False

            if isinstance(value, dict):
                for operator in value:
                    if (
                        not isinstance(operator, str)
                        or operator not in ALLOWED_FILTER_OPERATORS
                    ):
                        return False

                if "$options" in value and "$regex" not in value:
                    return False

                if "$regex" in value and not isinstance(
                    value["$regex"], str
                ):
                    return False

                if "$options" in value and not isinstance(
                    value["$options"], str
                ):
                    return False

                if "$exists" in value and not isinstance(
                    value["$exists"], bool
                ):
                    return False

                for operator in ("$in", "$nin"):
                    if operator in value and not isinstance(
                        value[operator], list
                    ):
                        return False

    return True


def validate_filters(collection_name, filters):
    schema = get_available_schema()

    if collection_name not in schema or not isinstance(filters, dict):
        return False

    return validate_filter_expression(
        filters, set(schema[collection_name])
    )


def validate_operation(operation):
    return (
        isinstance(operation, str)
        and operation in ALLOWED_OPERATIONS
    )


def validate_pipeline_value(value):
    if isinstance(value, list):
        return all(validate_pipeline_value(item) for item in value)

    if not isinstance(value, dict):
        return True

    allowed_operators = (
        ALLOWED_FILTER_OPERATORS
        | ALLOWED_GROUP_OPERATORS
        | ALLOWED_EXPRESSION_OPERATORS
        | ALLOWED_PIPELINE_STAGES
        | {"$literal"}
    )

    for key, nested_value in value.items():
        if not isinstance(key, str):
            return False

        if key.startswith("$") and key not in allowed_operators:
            return False

        if not validate_pipeline_value(nested_value):
            return False

    return True


def validate_pipeline(pipeline):
    if not isinstance(pipeline, list) or not pipeline:
        return False

    schema = get_available_schema()

    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            return False

        stage_name = next(iter(stage))

        if stage_name not in ALLOWED_PIPELINE_STAGES:
            return False

        stage_value = stage[stage_name]

        if stage_name == "$facet":
            if not isinstance(stage_value, dict) or not stage_value:
                return False

            for nested_pipeline in stage_value.values():
                if not validate_pipeline(nested_pipeline):
                    return False

        elif stage_name == "$lookup":
            if not isinstance(stage_value, dict):
                return False

            if set(stage_value) - {"from", "pipeline", "as"}:
                return False

            foreign_collection = stage_value.get("from")
            output_field = stage_value.get("as")
            nested_pipeline = stage_value.get("pipeline")

            if foreign_collection not in schema:
                return False

            if (
                not isinstance(output_field, str)
                or not output_field
                or output_field.startswith("$")
            ):
                return False

            if not validate_pipeline(nested_pipeline):
                return False

        elif stage_name == "$match":
            if not isinstance(stage_value, dict):
                return False

        elif stage_name == "$group":
            if not isinstance(stage_value, dict) or "_id" not in stage_value:
                return False

            for field, expression in stage_value.items():
                if field == "_id":
                    continue

                if not isinstance(expression, dict) or len(expression) != 1:
                    return False

                operator = next(iter(expression))

                if operator not in (
                    ALLOWED_GROUP_OPERATORS
                    | ALLOWED_EXPRESSION_OPERATORS
                    | {"$literal"}
                ):
                    return False

        elif stage_name in {"$addFields", "$project"}:
            if not isinstance(stage_value, dict) or not stage_value:
                return False

        elif stage_name == "$sort":
            if not isinstance(stage_value, dict) or not stage_value:
                return False

            if not all(
                isinstance(direction, int)
                and not isinstance(direction, bool)
                and direction in (-1, 1)
                for direction in stage_value.values()
            ):
                return False

        elif stage_name in {"$limit", "$skip"}:
            if (
                not isinstance(stage_value, int)
                or isinstance(stage_value, bool)
                or stage_value < 0
            ):
                return False

            if stage_name == "$limit" and stage_value == 0:
                return False

        elif stage_name == "$unwind":
            if isinstance(stage_value, str):
                if not stage_value.startswith("$"):
                    return False

            elif isinstance(stage_value, dict):
                path = stage_value.get("path")

                if not isinstance(path, str) or not path.startswith("$"):
                    return False

                allowed_keys = {
                    "path",
                    "includeArrayIndex",
                    "preserveNullAndEmptyArrays",
                }

                if set(stage_value) - allowed_keys:
                    return False

                preserve = stage_value.get("preserveNullAndEmptyArrays")

                if preserve is not None and not isinstance(preserve, bool):
                    return False

            else:
                return False

        if not validate_pipeline_value(stage):
            return False

    return True


def validate_query(query):
    if not isinstance(query, dict):
        return False

    allowed_keys = {
        "collection", "operation", "filters",
        "fields", "field", "pipeline",
    }

    if set(query) - allowed_keys:
        return False

    collection = query.get("collection")
    operation = query.get("operation")

    if not validate_collection(collection):
        return False

    if not validate_operation(operation):
        return False

    filters = query.get("filters", {})
    fields = query.get("fields", [])

    if not validate_filters(collection, filters):
        return False

    if operation == "count":
        return True

    if operation == "distinct":
        field = query.get("field")
        return (
            isinstance(field, str)
            and validate_fields(collection, [field])
        )

    if operation == "find":
        return validate_fields(collection, fields)

    if operation == "aggregate":
        # Aggregation filters must be inside a $match stage.
        if filters:
            return False

        return validate_pipeline(query.get("pipeline", []))

    return False