from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Any, Sequence, Literal, Union
from copy import deepcopy
import funcnodes as fn
from funcnodes_core.utils.functions import make_sync_if_needed


class FilterQuery:
    """
    Base class for all query components that can be combined
    to form a WHERE clause in SQL. Subclasses must implement
    the 'build()' method to return a valid SQL string snippet.
    """

    def __and__(self, other: FilterQuery) -> FilterQuery:
        """
        Logical AND operator that combines two FilterQuery objects.
        """
        return AndQuery(self, other)

    def __or__(self, other: FilterQuery) -> FilterQuery:
        """
        Logical OR operator that combines two FilterQuery objects.
        """
        return OrQuery(self, other)

    def __invert__(self) -> FilterQuery:
        """
        Logical NOT operator that negates a FilterQuery object.
        """
        return NotQuery(self)

    def __str__(self):
        """
        Return a string representation of the FilterQuery object.
        """
        return self.build()

    def build(self) -> str:
        """
        Construct and return a SQL expression snippet.
        Must be overridden by subclasses.
        """
        raise NotImplementedError("Subclasses must implement 'build()'.")

    def clone(self) -> FilterQuery:
        """
        Create a deep copy of the FilterQuery object.
        """
        return deepcopy(self)


class ComparisonQuery(FilterQuery):
    """
    A query component representing a basic comparison in a WHERE clause,
    e.g., 'column = value', 'column != value', etc.
    """

    OperatorType = Literal["=", "!=", ">", ">=", "<", "<="]

    def __init__(
        self, column: str, operator: ComparisonQuery.OperatorType, value: Any
    ) -> None:
        self.column = column
        self.operator = operator
        self.value = value

    def interfere_value(self):
        if self.value is None:
            return None
        if isinstance(self.value, str):
            try:
                flv = float(self.value)
                intv = int(self.value)
                if intv == flv:
                    return intv
                return flv
            except ValueError:
                pass

            if self.value.lower() == "true":
                return True
            if self.value.lower() == "false":
                return False

        return self.value

    def build(self) -> str:
        """
        Construct and return a SQL expression snippet for a comparison.
        Automatically wraps string values in quotes.
        """
        v = self.interfere_value()
        value_repr = f"'{v}'" if isinstance(v, str) else str(v)
        return f"{self.column} {self.operator} {value_repr}"


class InQuery(FilterQuery):
    """
    A query component representing a SQL IN clause, e.g.,
    'column IN (val1, val2, ...)'.
    """

    def __init__(self, column: str, values: Sequence[Any]) -> None:
        self.column = column
        self.values = values

    def build(self) -> str:
        """
        Construct and return a SQL snippet for an IN clause.
        Wraps string values in quotes.
        """
        placeholders = ", ".join(
            f"'{v}'" if isinstance(v, str) else str(v) for v in self.values
        )
        return f"{self.column} IN ({placeholders})"


class NotQuery(FilterQuery):
    """
    A query component that negates the result of another FilterQuery,
    e.g., 'NOT (column = value)'.
    """

    def __init__(self, query: FilterQuery) -> None:
        self.query = query

    def build(self) -> str:
        """
        Construct and return a SQL snippet negating another FilterQuery.
        """
        return f"NOT ({self.query.build()})"


class AndQuery(FilterQuery):
    """
    A query component that combines two FilterQuery objects with
    a logical AND, e.g., '(expr1 AND expr2)'.
    """

    def __init__(self, left: FilterQuery, right: FilterQuery) -> None:
        self.left = left
        self.right = right

    def build(self) -> str:
        """
        Construct and return a SQL snippet combining two FilterQuery
        objects with AND.
        """
        return f"({self.left.build()} AND {self.right.build()})"


class OrQuery(FilterQuery):
    """
    A query component that combines two FilterQuery objects with
    a logical OR, e.g., '(expr1 OR expr2)'.
    """

    def __init__(self, left: FilterQuery, right: FilterQuery) -> None:
        self.left = left
        self.right = right

    def build(self) -> str:
        """
        Construct and return a SQL snippet combining two FilterQuery
        objects with OR.
        """
        return f"({self.left.build()} OR {self.right.build()})"


@dataclass
class JoinClause:
    """
    Represents a JOIN clause in a SQL statement, including the type of join,
    the table to join, and the ON condition that defines how to match rows.

    Example:
    JoinClause("INNER", "orders", "users.id = orders.userid")
    This would generate the SQL snippet:
    INNER JOIN orders ON users.id = orders.userid
    which would be used to join the 'orders' table to the 'users' table, resulting
    in only rows that have matching values in the 'users' and 'orders' tables.

    JoinClause("LEFT", "orders", "users.id = orders.userid")
    This would generate the SQL snippet:
    LEFT JOIN orders ON users.id = orders.userid
    which would perform a LEFT JOIN on the 'orders' table, resulting in all
    rows from the 'users' table and only matching rows from the 'orders' table.

    JoinClause("RIGHT", "orders", "users.id = orders.userid")
    This would generate the SQL snippet:
    RIGHT JOIN orders ON users.id = orders.userid
    which would perform a RIGHT JOIN on the 'orders' table, resulting in all
    rows from the 'orders' table and only matching rows from the 'users' table.


    """

    join_type: str  # e.g., "INNER", "LEFT", "RIGHT", etc.
    table: str
    on_clause: str  # e.g., "users.id = orders.user_id"

    def build(self) -> str:
        """
        Construct and return the JOIN portion of a SQL statement.
        """
        return f"{self.join_type} JOIN {self.table} ON {self.on_clause}"


class SQLQuery:
    """
    Represents a full SQL SELECT query with optional clauses (WHERE, JOIN,
    GROUP BY, ORDER BY, LIMIT, OFFSET).
    """

    # joins: Optional[List[JoinClause]] = None
    def __init__(
        self,
        table: Optional[str] = None,
        columns: Optional[List[str]] = None,
        filter: Optional[FilterQuery] = None,
        group_by: Optional[str] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> None:
        self.table = table
        self.columns = columns
        self.filter = filter
        self.group_by = group_by
        self.order_by = order_by
        self.limit = limit
        self.offset = offset

    def clone(self) -> "SQLQuery":
        return deepcopy(self)

    def build(self) -> str:
        """
        Construct the full SQL SELECT query string.

        Returns:
            A SQL statement as a string.
        """
        # Handle the columns to select
        columns_str = ", ".join(self.columns) if self.columns else "*"
        tablestr = ("FROM " + self.table) if self.table else ""
        query = f"SELECT {columns_str} {tablestr}"

        # Append any JOIN clauses
        # if self.joins:
        #     for join_clause in self.joins:
        #         query += f" {join_clause.build()}"

        # WHERE clause
        if self.filter:
            query += f" WHERE {self.filter.build()}"

        # GROUP BY clause
        if self.group_by:
            query += f" GROUP BY {self.group_by}"

        # ORDER BY clause
        if self.order_by:
            query += f" ORDER BY {self.order_by}"

        # LIMIT clause
        if self.limit is not None:
            query += f" LIMIT {self.limit}"

        # OFFSET clause
        if self.offset is not None:
            query += f" OFFSET {self.offset}"

        return query.strip()

    def __str__(self):
        return self.build()


class AbstractConnectionManager:
    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.release()

    async def connect(self):
        raise NotImplementedError("Subclasses must implement 'connect()'.")

    async def release(self):
        raise NotImplementedError("Subclasses must implement 'release()'.")

    async def execute_query(self, query: SQLQuery) -> List[dict]:
        raise NotImplementedError("Subclasses must implement 'execute_query()'.")

    async def get_tables_names(self) -> List[str]:
        raise NotImplementedError("Subclasses must implement 'get_table_names()'.")

    async def get_columns(self, table: str) -> List[str]:
        raise NotImplementedError("Subclasses must implement 'get_columns()'.")

    async def validate_query(self, query: SQLQuery) -> None:
        if query.table is None:
            raise ValueError("No table specified in query.")
        if query.table not in await self.get_tables_names():
            raise ValueError(f"Table '{query.table}' not found in database.")


class SelectTable(fn.Node):
    node_id = "storage.sql.select_table"
    node_name = "Select Table"
    description = "Selects a table from the database."

    conn = fn.NodeInput(
        id="conn",
        type=AbstractConnectionManager,
        required=False,
        description="Connection to the database.",
    )

    table = fn.NodeInput(
        id="table",
        type=str,
        required=True,
        description="The table to select.",
    )

    in_query = fn.NodeInput(
        id="in_query",
        type=SQLQuery,
        required=False,
        default=None,
        description="The query to execute.",
    )

    out_query = fn.NodeOutput(
        id="out_query",
        type=SQLQuery,
        description="The generated query.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_input("conn").on(
            "after_set_value", make_sync_if_needed(self._update_keys)
        )

    async def _update_keys(self, *args, **kwargs):
        try:
            conn: AbstractConnectionManager = self.get_input("conn").value
        except KeyError:
            return

        try:
            options = await conn.get_tables_names()
        except Exception:
            options = None
        self.get_input("table").value_options = {"options": options}

    async def func(
        self,
        conn: AbstractConnectionManager,
        table: str,
        in_query: Optional[SQLQuery] = None,
    ) -> None:
        if in_query and isinstance(in_query, SQLQuery):
            query = in_query.clone()
        else:
            query = SQLQuery()

        if in_query:
            if isinstance(in_query, FilterQuery):
                query.filter = in_query
            else:
                raise ValueError(f"Invalid query type {type(in_query)}")

        query.table = table
        if conn is not None:
            conn.validate_query(query)

        self.outputs["out_query"].value = query


class GetColumns(fn.Node):
    node_id = "storage.sql.get_columns"
    node_name = "Get Table Columns"
    description = "Gets the columns of a table from the database."

    conn = fn.NodeInput(
        id="conn",
        type=AbstractConnectionManager,
        required=False,
        description="Connection to the database.",
    )

    table = fn.NodeInput(
        id="table",
        type=str,
        required=True,
        description="The table to select.",
    )

    columns = fn.NodeOutput(
        id="columns",
        type=List[str],
        description="List of column names.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_input("conn").on(
            "after_set_value", make_sync_if_needed(self._update_keys)
        )

    async def _update_keys(self, *args, **kwargs):
        try:
            conn: AbstractConnectionManager = self.get_input("conn").value
        except KeyError:
            return

        try:
            options = await conn.get_tables_names()
        except Exception:
            options = None

        self.get_input("table").value_options = {"options": options}

    async def func(
        self,
        conn: AbstractConnectionManager,
        table: str,
    ) -> None:
        self.outputs["columns"].value = await conn.get_columns(table)


@fn.NodeDecorator(
    id="storage.sql.filter.and",
    name="AND Filter",
)
def and_filter(left: FilterQuery, right: FilterQuery) -> FilterQuery:
    return left & right


@fn.NodeDecorator(
    id="storage.sql.filter.or",
    name="OR Filter",
)
def or_filter(left: FilterQuery, right: FilterQuery) -> FilterQuery:
    return left | right


@fn.NodeDecorator(
    id="storage.sql.filter.not",
    name="NOT Filter",
)
def not_filter(query: FilterQuery) -> FilterQuery:
    return ~query


@fn.NodeDecorator(
    id="storage.sql.filter.comparison",
    name="Comparison Filter",
)
def comparison_filter(
    column: str, operator: ComparisonQuery.OperatorType, value: Union[str, Any]
) -> FilterQuery:
    return ComparisonQuery(column, operator, value)


@fn.NodeDecorator(
    id="storage.sql.filter.in",
    name="IN Filter",
)
def in_filter(column: str, values: Sequence[Any]) -> FilterQuery:
    return InQuery(column, values)


@fn.NodeDecorator(
    id="storage.sql.execute",
    name="Execute Query",
)
async def execute_query(conn: AbstractConnectionManager, query: SQLQuery) -> List[dict]:
    return await conn.execute_query(query)


@fn.NodeDecorator(
    id="storage.sql.get_tables",
    name="Get Tables",
)
def get_tables(conn: AbstractConnectionManager) -> List[str]:
    return conn.get_tables_names()


NODE_SHELF = fn.Shelf(
    nodes=[
        SelectTable,
        and_filter,
        or_filter,
        not_filter,
        comparison_filter,
        in_filter,
        execute_query,
        GetColumns,
        get_tables,
    ],
    name="Query Builder Nodes",
    description="Nodes for building and executing SQL queries.",
    subshelves=[],
)
