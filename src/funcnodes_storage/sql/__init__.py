import aiosqlite
from typing import Any, List, Literal, Optional
import json
import funcnodes as fn
from funcnodes_files import validate_path
from pathlib import Path
import re
import asyncio
from dataclasses import dataclass
from .q_builder import (
    SQLQuery,
    NODE_SHELF as q_builder_shelf,
    AbstractConnectionManager,
)

from funcnodes_core.utils.functions import make_sync_if_needed

try:
    import funcnodes_pandas as fnpd
except (ImportError, ModuleNotFoundError):
    fnpd = None


class ManagedSQLiteConnection(AbstractConnectionManager):
    """
    A thread-safe wrapper around aiosqlite.Connection to ensure proper management
    of the connection and prevent simultaneous disruptions.
    """

    def __init__(self, path: Path):
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()  # Protect access to the connection
        self._usage_count = 0  # Track the number of users accessing the connection

    async def connect(self) -> aiosqlite.Connection:
        """
        Opens a connection if it does not exist, or returns the existing connection.
        """
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._path)
            self._usage_count += 1
            return self._conn

    async def release(self):
        """
        Decreases the usage count and closes the connection if no users remain.
        """
        async with self._lock:
            if self._conn:
                self._usage_count -= 1
                if self._usage_count <= 0:
                    await self._conn.close()
                    self._conn = None

    async def close(self):
        """
        Forcefully closes the connection, regardless of usage count.
        """
        async with self._lock:
            if self._conn:
                await self._conn.close()
                self._conn = None
                self._usage_count = 0

    async def get_tables_names(self) -> List[str]:
        """
        Returns a list of table names in the database.
        """
        async with self as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ) as cursor:
                tables = await cursor.fetchall()

        return [t[0] for t in tables]

    async def get_table_columns(self, table: str) -> List[str]:
        """
        Returns a list of column names in the specified table.
        """

        async with self as conn:
            async with conn.execute(f"PRAGMA table_info({table});") as cursor:
                columns = await cursor.fetchall()
        return [c[1] for c in columns]

    async def execute_query(self, query: SQLQuery) -> List[dict]:
        """
        Executes a SQLQuery object and returns the results as a list of dictionaries.
        """
        await self.validate_query(query)
        async with self as conn:
            async with conn.execute(str(query)) as cursor:
                rows = await cursor.fetchall()

        columns = query.columns or await self.get_columns(query.table)
        q = query.build()
        async with self as conn:
            async with conn.execute(q) as cursor:
                rows = await cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    async def get_columns(self, table: str) -> List[str]:
        """
        Returns a list of column names in the specified table.
        """

        async with self as conn:
            async with conn.execute(f"PRAGMA table_info({table});") as cursor:
                columns = await cursor.fetchall()

        return [c[1] for c in columns]
        # return columns


class SQLiteConnectionNode(fn.Node):
    node_id = "storage.sql.connection.async"
    node_name = "Async SQLite Connection"
    description = (
        "Asynchronously connects to a local SQLite database and returns the connection."
    )

    db_path = fn.NodeInput(
        id="db_path",
        type=str,
        required=True,
        description="Path to the SQLite database file",
        does_trigger=False,
    )

    connection = fn.NodeOutput(
        id="connection",
        type=ManagedSQLiteConnection,
        description="The SQLite database connection",
    )

    async def func(self, db_path: str) -> ManagedSQLiteConnection:
        ns = self.nodespace
        if not ns:
            raise ValueError("Node not in a nodespace")

        root = ns.get_property("files_dir")

        if not db_path.endswith(".db"):
            db_path += ".db"

        fullpath = validate_path(Path(db_path), root)
        if not fullpath.exists():
            fullpath.touch()  # Securely create the file

        try:
            self.outputs["connection"].value = ManagedSQLiteConnection(fullpath)
        except aiosqlite.Error as e:
            raise RuntimeError(f"Failed to connect to SQLite database: {e}")


_valid_fb_types_type = Literal["INTEGER", "REAL", "TEXT", "BLOB", "ANY"]
_valid_db_types: List[_valid_fb_types_type] = ["INTEGER", "REAL", "TEXT", "BLOB", "ANY"]


@dataclass
class SQLResult:
    id: int
    timestamp: int
    value: Any


class RecordPoint(fn.Node):
    node_id = "storage.sql.record_point"
    node_name = "Record Point"
    description = " records a data point in a SQLite database."

    conn = fn.NodeInput(
        id="conn",
        type=ManagedSQLiteConnection,
        required=True,
        description="The SQLite database connection",
        does_trigger=False,
    )

    value = fn.NodeInput(
        id="value",
        type=Any,
        required=True,
        description="The value to record",
    )

    table = fn.NodeInput(
        id="table",
        type=str,
        required=True,
        description="The table of the data point",
        does_trigger=False,
    )

    db_type = fn.NodeInput(
        id="db_type",
        type=str,
        required=False,
        description="The type of the data point",
        default=None,
        value_options={"options": _valid_db_types},
        does_trigger=False,
    )

    record = fn.NodeOutput(
        id="record",
        type=SQLResult,
        description="The recorded data point",
    )

    async def func(
        self, conn: ManagedSQLiteConnection, value: Any, table: str, db_type: str = None
    ) -> None:
        # Validate the table name
        try:
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
                raise ValueError(
                    f"Invalid table name: {table}, must match ^[A-Za-z_][A-Za-z0-9_]*$"
                )

            # Map the value to its SQLite type and format
            value_type, value = _map_value(value, db_type)
            tablename = f"dp_{table}_{value_type}"
            async with conn as db_conn:  # Ensure connection is managed here
                try:
                    # Create table if it doesn't exist
                    create_table_query = (
                        f"CREATE TABLE IF NOT EXISTS {tablename} ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "timestamp INTEGER NOT NULL, "
                        f"value {value_type} NOT NULL "
                        ") STRICT"
                    )
                    async with db_conn.execute(create_table_query):
                        pass  # Table creation

                    # Insert the data point
                    insert_query = (
                        f"INSERT INTO {tablename} (timestamp, value) "
                        "VALUES (strftime('%s', 'now'), ?)"
                    )
                    async with db_conn.execute(insert_query, (value,)):
                        # Commit the transaction
                        await db_conn.commit()

                    # Retrieve the last inserted row ID
                    async with db_conn.execute("SELECT last_insert_rowid()") as cursor:
                        row = await cursor.fetchone()
                        row_id = row[0]

                    # Get the inserted record for output
                    async with db_conn.execute(
                        f"SELECT id, timestamp, value FROM {tablename} WHERE id = ?",
                        (row_id,),
                    ) as cursor:
                        row = await cursor.fetchone()

                    # Create and set the SQLResult output
                    result = SQLResult(
                        id=row[0],
                        timestamp=row[1],
                        value=json.loads(row[2], cls=fn.JSONDecoder)
                        if value_type == "TEXT"
                        else row[2],
                    )
                    self.outputs["record"].value = result

                except aiosqlite.Error as e:
                    raise RuntimeError(f"Failed to record point: {e}")
        except Exception as e:
            print("Error in RecordPoint: ", e)
            raise


def _map_value(value: Any, db_type: Optional[_valid_fb_types_type]) -> tuple[str, Any]:
    """
    Maps Python types to SQLite types and formats the value for insertion.
    """
    if db_type is None:
        if isinstance(value, int):
            return "INTEGER", int(value)
        elif isinstance(value, float):
            return "REAL", float(value)
        elif isinstance(value, str):
            return "TEXT", value
        elif isinstance(value, bool):
            return "INTEGER", int(bool(value))
        else:
            # Convert other types to JSON
            return "TEXT", json.dumps(value, cls=fn.JSONEncoder)
    else:
        if db_type == "INTEGER":
            return "INTEGER", int(value)
        elif db_type == "REAL":
            return "REAL", float(value)
        elif db_type == "TEXT":
            return "TEXT", json.dumps(value, cls=fn.JSONEncoder)
        elif db_type == "BLOB":
            return "BLOB", value
        elif db_type == "ANY":
            return "ANY", json.loads(json.dumps(value, cls=fn.JSONEncoder))
        else:
            raise ValueError(f"Invalid db_type: {db_type}")


class DataRetrieve(fn.Node):
    node_id = "storage.sql.retrieve_data"
    node_name = "Retrieve Data"
    description = "Retrieves data from a SQLite database table."

    conn = fn.NodeInput(
        id="conn",
        type=ManagedSQLiteConnection,
        required=True,
        description="The SQLite database connection",
    )

    table = fn.NodeInput(
        id="table",
        type=str,
        required=True,
        description="The tablename of the data point (table name prefix).",
    )

    limit = fn.NodeInput(
        id="limit",
        type=Optional[int],
        required=False,
        default=None,
        description="The maximum number of rows to retrieve. Newer rows are retrieved first.",
    )

    results = fn.NodeOutput(
        id="results",
        type=List[SQLResult],
        description="The retrieved data as a list of rows.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_input("conn").on(
            "after_set_value", make_sync_if_needed(self._update_keys)
        )

    async def _update_keys(self, *args, **kwargs):
        try:
            conn = self.get_input("conn").value
        except KeyError:
            return

        try:
            async with conn as db_conn:
                async with db_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ) as cursor:
                    tables = await cursor.fetchall()
                table_names = [t[0] for t in tables if t[0].startswith("dp_")]
                table_names = [t.split("_", 1)[1] for t in table_names]
                table_names, postfix = zip(*[t.rsplit("_", 1) for t in table_names])
                options = table_names
        except Exception:
            options = None

        self.get_input("table").value_options = {"options": options}

    async def func(
        self,
        conn: ManagedSQLiteConnection,
        table: str,
        limit: Optional[int] = None,
    ) -> List[dict]:
        # Validate the table name
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
            raise ValueError(
                f"Invalid table name: {table}, must match ^[A-Za-z_][A-Za-z0-9_]*$"
            )

        all_tables = await conn.get_tables_names()
        value_type = None
        if table not in all_tables:
            for t in all_tables:
                if t.startswith(f"dp_{table}_"):
                    _value_type = t.rsplit("_", 1)[1]
                    if _value_type in _valid_db_types:
                        table = t
                        value_type = _value_type
                        break

        if table not in all_tables:
            raise ValueError(f"Table {table} does not exist.")

        query = f"SELECT id, timestamp, value FROM {table}"

        # Add a LIMIT clause
        query += " ORDER BY timestamp DESC"
        if limit:
            query += f" LIMIT {limit}"

        async with conn as db_conn:
            try:
                # Execute the query
                async with db_conn.execute(query) as cursor:
                    rows = await cursor.fetchall()

                # Format the rows into a list of dictionaries
                result = [
                    SQLResult(
                        id=row[0],
                        timestamp=row[1],
                        value=_map_value(row[2], value_type)[1]
                        if value_type
                        else row[2],
                    )
                    for row in rows
                ]
                # order the results by timestamp
                result.sort(key=lambda x: x.timestamp)
                self.outputs["results"].value = result
                return result
            except aiosqlite.Error as e:
                raise RuntimeError(f"Failed to retrieve data: {e}")


class DeleteData(fn.Node):
    node_id = "storage.sql.delete_data"
    node_name = "Delete Data"
    description = "Deletes rows or entire tables from the database."

    conn = fn.NodeInput(
        id="conn",
        type=ManagedSQLiteConnection,
        required=True,
        description="The SQLite database connection",
    )

    table = fn.NodeInput(
        id="table",
        type=str,
        required=True,
        description="The table to delete from.",
    )

    async def func(
        self, conn: ManagedSQLiteConnection, table: str, condition: Optional[str] = None
    ) -> None:
        async with conn as db_conn:
            try:
                # if condition:
                #     query = f"DELETE FROM {table} WHERE {condition}"
                # else:
                #
                query = f"DROP TABLE IF EXISTS {table}"
                await db_conn.execute(query)
                await db_conn.commit()
            except aiosqlite.Error as e:
                raise RuntimeError(f"Failed to delete data: {e}")


@fn.NodeDecorator(
    node_id="storage.sql.to_csv",
    node_name="To CSV",
    description="Converts a list of SQLResult objects to a CSV file.",
)
def to_csv(results: List[SQLResult]) -> str:
    """
    Converts a list of SQLResult objects to a CSV file.
    """
    csv = "id,timestamp,value"
    for row in results:
        escaped_value = json.dumps(row.value, cls=fn.JSONEncoder)
        csv += f"\n{row.id},{row.timestamp},{escaped_value}"
    return csv


if fnpd:

    @fn.NodeDecorator(
        node_id="storage.sql.to_df",
        node_name="To DataFrame",
        description="Converts a list of SQLResult objects to a pandas DataFrame.",
    )
    def to_df(results: List[SQLResult]) -> fnpd.pd.DataFrame:
        """
        Converts a list of SQLResult objects to a pandas DataFrame.
        with the id as the index.
        """
        data = {
            "timestamp": [row.timestamp for row in results],
            "value": [row.value for row in results],
        }
        return fnpd.pd.DataFrame(data, index=[row.id for row in results])


NODE_SHELF = fn.Shelf(
    nodes=[SQLiteConnectionNode, RecordPoint, DataRetrieve, to_csv]
    + ([to_df] if fnpd else []),
    name="SQL Storage",
    description="Nodes for interacting with SQLite databases.",
    subshelves=[q_builder_shelf],
)
