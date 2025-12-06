import asyncio

import aiosqlite
import pytest
import pytest_asyncio
import pytest_funcnodes as pfn

from funcnodes_core import NodeSpace, run_until_complete
from funcnodes_storage import sql
from funcnodes_storage.sql import q_builder

try:
    import funcnodes_pandas as fnpd
except (ImportError, ModuleNotFoundError):
    fnpd = None


@pytest.fixture
def files_dir(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    return root


@pytest.fixture
def nodespace(files_dir):
    ns = NodeSpace()
    ns.set_property("files_dir", str(files_dir))
    return ns


@pytest_asyncio.fixture
async def sqlite_env(nodespace, files_dir):
    test_db = files_dir / "test.db"
    conn_node = sql.SQLiteConnectionNode()
    nodespace.add_node_instance(conn_node)
    conn_node.inputs["db_path"].value = test_db.name
    await conn_node

    yield nodespace, test_db, conn_node

    if test_db.exists():
        try:
            test_db.unlink()
        except PermissionError:
            async with aiosqlite.connect(test_db) as conn:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                )
                tables = [t[0] for t in await cursor.fetchall()]
                for table in tables:
                    if table != "sqlite_sequence":
                        await conn.execute(f"DROP TABLE {table}")
                await conn.commit()
            test_db.unlink(missing_ok=True)


@pfn.nodetest(sql.SQLiteConnectionNode)
async def test_conn(sqlite_env):
    _, _, conn_node = sqlite_env
    assert isinstance(
        conn_node.outputs["connection"].value, sql.ManagedSQLiteConnection
    )


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint])
async def test_add_int(sqlite_env):
    ns, test_db, conn_node = sqlite_env
    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)

    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["value"].value = 5
    rec_node.inputs["table"].value = "test"

    await run_until_complete(conn_node, rec_node)
    assert rec_node.inputs_ready(), rec_node.ready_state()
    assert rec_node.outputs["record"].value.value == 5

    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        tables = await cursor.fetchall()
        assert ("dp_test_INTEGER",) in tables

        cursor = await conn.execute("SELECT * FROM dp_test_INTEGER")
        rows = await cursor.fetchall()
        assert rows[0][2] == 5


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint, sql.DataRetrieve])
async def test_data_retrevial(sqlite_env):
    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "test"

    await run_until_complete(conn_node, rec_node)
    for i in range(7):
        rec_node.inputs["value"].value = i
        await rec_node
        await asyncio.sleep(0.1)

    retrieval_node = sql.DataRetrieve()
    ns.add_node_instance(retrieval_node)
    retrieval_node.inputs["conn"].connect(conn_node.outputs["connection"])
    retrieval_node.inputs["table"].value = "test"

    await retrieval_node
    assert len(retrieval_node.outputs["results"].value) == 7


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint, sql.DataRetrieve])
async def test_retrieve_dict_roundtrip(sqlite_env):
    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "dict_table"

    payload = {"a": 1, "b": "foo", "c": [1, 2, 3]}
    rec_node.inputs["value"].value = payload

    await run_until_complete(conn_node, rec_node)

    retrieval_node = sql.DataRetrieve()
    ns.add_node_instance(retrieval_node)
    retrieval_node.inputs["conn"].connect(conn_node.outputs["connection"])
    retrieval_node.inputs["table"].value = "dict_table"

    await retrieval_node
    results = retrieval_node.outputs["results"].value
    assert len(results) == 1
    assert results[0].value == payload


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint, sql.DataRetrieve])
async def test_retrieve_string_roundtrip(sqlite_env):
    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "str_table"

    rec_node.inputs["value"].value = "hello world"

    await run_until_complete(conn_node, rec_node)

    retrieval_node = sql.DataRetrieve()
    ns.add_node_instance(retrieval_node)
    retrieval_node.inputs["conn"].connect(conn_node.outputs["connection"])
    retrieval_node.inputs["table"].value = "str_table"

    await retrieval_node
    results = retrieval_node.outputs["results"].value
    assert len(results) == 1
    assert results[0].value == "hello world"


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint, sql.DeleteData])
async def test_delete_data_condition(sqlite_env):
    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "delete_cond"

    await run_until_complete(conn_node, rec_node)
    for i in range(5):
        rec_node.inputs["value"].value = i
        await rec_node

    del_node = sql.DeleteData()
    ns.add_node_instance(del_node)
    del_node.inputs["conn"].connect(conn_node.outputs["connection"])
    del_node.inputs["table"].value = "dp_delete_cond_INTEGER"

    cond_node = q_builder.comparison_filter()
    cond_node.inputs["column"].value = "value"
    cond_node.inputs["operator"].value = ">="
    cond_node.inputs["value"].value = 3

    del_node.inputs["condition"].connect(cond_node.outputs["out"])

    await run_until_complete(cond_node)
    await del_node

    # verify remaining rows are those < 3
    async with aiosqlite.connect(sqlite_env[1]) as conn:
        cursor = await conn.execute(
            "SELECT value FROM dp_delete_cond_INTEGER ORDER BY value"
        )
        remaining = [row[0] for row in await cursor.fetchall()]
        assert remaining == [0, 1, 2]


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint, sql.DataRetrieve, sql.to_csv])
async def test_to_csv(sqlite_env):
    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "test"

    await run_until_complete(conn_node, rec_node)
    for i in range(7):
        rec_node.inputs["value"].value = i
        await rec_node
        await asyncio.sleep(0.1)

    retrieval_node = sql.DataRetrieve()
    ns.add_node_instance(retrieval_node)
    retrieval_node.inputs["conn"].connect(conn_node.outputs["connection"])
    retrieval_node.inputs["table"].value = "test"

    to_csv_node = sql.to_csv()
    ns.add_node_instance(to_csv_node)
    to_csv_node.inputs["results"].connect(retrieval_node.outputs["results"])

    await run_until_complete(retrieval_node, to_csv_node)
    results = retrieval_node.outputs["results"].value
    assert len(results) == 7

    csv_lines = to_csv_node.outputs["out"].value.split("\n")
    assert len(csv_lines) == 8  # 1 header + 7 rows


@pfn.nodetest(
    [sql.SQLiteConnectionNode, sql.RecordPoint, sql.DataRetrieve]
    + ([sql.to_df] if fnpd else [])
)
async def test_to_df(sqlite_env):
    if fnpd is None:
        pytest.skip("funcnodes_pandas not installed")

    ns, _, conn_node = sqlite_env

    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "test"

    await run_until_complete(conn_node, rec_node)
    for i in range(7):
        rec_node.inputs["value"].value = i
        await rec_node
        await asyncio.sleep(0.1)

    retrieval_node = sql.DataRetrieve()
    ns.add_node_instance(retrieval_node)
    retrieval_node.inputs["conn"].connect(conn_node.outputs["connection"])
    retrieval_node.inputs["table"].value = "test"

    to_df_node = sql.to_df()
    ns.add_node_instance(to_df_node)
    to_df_node.inputs["results"].connect(retrieval_node.outputs["results"])

    await run_until_complete(retrieval_node, to_df_node)
    results = retrieval_node.outputs["results"].value
    assert len(results) == 7

    df = to_df_node.outputs["out"].value
    assert len(df) == 7
    assert isinstance(df, fnpd.pd.DataFrame)


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint])
async def test_add_float(sqlite_env):
    ns, _, conn_node = sqlite_env
    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)

    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["value"].value = 4
    rec_node.inputs["table"].value = "test"
    rec_node.inputs["db_type"].value = "REAL"

    await run_until_complete(conn_node, rec_node)

    rec_node.inputs["value"].value = 5.5
    await run_until_complete(rec_node)


@pfn.nodetest([sql.SQLiteConnectionNode, sql.RecordPoint])
async def test_add_dict(sqlite_env):
    ns, test_db, conn_node = sqlite_env
    rec_node = sql.RecordPoint()
    ns.add_node_instance(rec_node)

    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "test"
    await run_until_complete(conn_node, rec_node)

    payload = {
        "a": 1,
        "b": "foo",
        "c": {"d": 0.1},
        "e": [0, 1, 2],
    }
    rec_node.inputs["value"].value = payload

    await run_until_complete(rec_node)
    record = rec_node.outputs["record"].value
    assert record.value == payload

    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        tables = await cursor.fetchall()
        assert any(name.startswith("dp_test_") for (name,) in tables)


@pfn.nodetest(q_builder.SelectTable)
async def test_select_table(sqlite_env):
    ns, test_db, conn_node = sqlite_env

    # ensure table exists so validation passes
    async with aiosqlite.connect(test_db) as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
        await conn.commit()

    node = q_builder.SelectTable()
    ns.add_node_instance(node)

    node.inputs["table"].value = "test"
    node.inputs["conn"].connect(conn_node.outputs["connection"])

    await node
    assert node.outputs["out_query"].value.build() == "SELECT * FROM test"


@pfn.nodetest(q_builder.comparison_filter)
async def test_comparison_filter():
    node = q_builder.comparison_filter()
    node.inputs["column"].value = "name"
    node.inputs["operator"].value = "="
    node.inputs["value"].value = "John"

    await node
    assert node.outputs["out"].value.build() == "name = 'John'"

    node.inputs["value"].value = 5
    node.inputs["operator"].value = ">="

    await node
    assert node.outputs["out"].value.build() == "name >= 5"


@pfn.nodetest([q_builder.and_filter, q_builder.comparison_filter])
async def test_and_filter():
    node = q_builder.and_filter()
    filter1 = q_builder.comparison_filter()
    filter2 = q_builder.comparison_filter()

    node.inputs["left"].connect(filter1.outputs["out"])
    node.inputs["right"].connect(filter2.outputs["out"])

    filter1.inputs["column"].value = "name"
    filter1.inputs["operator"].value = "="
    filter1.inputs["value"].value = "John"

    filter2.inputs["column"].value = "age"
    filter2.inputs["operator"].value = ">"
    filter2.inputs["value"].value = 10

    await run_until_complete(filter1, filter2, node)
    assert node.outputs["out"].value.build() == "(name = 'John' AND age > 10)"


@pfn.nodetest([q_builder.or_filter, q_builder.comparison_filter])
async def test_or_filter():
    node = q_builder.or_filter()
    filter1 = q_builder.comparison_filter()
    filter2 = q_builder.comparison_filter()

    node.inputs["left"].connect(filter1.outputs["out"])
    node.inputs["right"].connect(filter2.outputs["out"])

    filter1.inputs["column"].value = "name"
    filter1.inputs["operator"].value = "="
    filter1.inputs["value"].value = "John"

    filter2.inputs["column"].value = "age"
    filter2.inputs["operator"].value = ">"
    filter2.inputs["value"].value = 10

    await run_until_complete(filter1, filter2, node)
    assert node.outputs["out"].value.build() == "(name = 'John' OR age > 10)"


@pfn.nodetest([q_builder.not_filter, q_builder.comparison_filter])
async def test_not_filter():
    node = q_builder.not_filter()
    filter1 = q_builder.comparison_filter()

    filter1.inputs["column"].value = "name"
    filter1.inputs["operator"].value = "="
    filter1.inputs["value"].value = "John"

    node.inputs["query"].connect(filter1.outputs["out"])

    await run_until_complete(filter1, node)
    assert node.outputs["out"].value.build() == "NOT (name = 'John')"


@pfn.nodetest(q_builder.in_filter)
async def test_in_filter():
    node = q_builder.in_filter()
    node.inputs["column"].value = "name"
    node.inputs["values"].value = ["John", "Doe"]

    await node
    assert node.outputs["out"].value.build() == "name IN ('John', 'Doe')"


@pfn.nodetest(q_builder.get_tables)
async def test_get_tables(sqlite_env):
    _, test_db, conn_node = sqlite_env
    async with aiosqlite.connect(test_db) as conn:
        await conn.execute("CREATE TABLE test (name TEXT)")
        await conn.commit()

    node = q_builder.get_tables()
    node.inputs["conn"].connect(conn_node.outputs["connection"])

    await node
    assert node.outputs["out"].value == ["test"]


@pfn.nodetest(q_builder.GetColumns)
async def test_get_columns(sqlite_env):
    _, test_db, conn_node = sqlite_env
    async with aiosqlite.connect(test_db) as conn:
        await conn.execute("CREATE TABLE test (name TEXT, age INT)")
        await conn.commit()

    node = q_builder.GetColumns()
    node.inputs["conn"].connect(conn_node.outputs["connection"])
    node.inputs["table"].value = "test"

    await node
    assert node.outputs["columns"].value == ["name", "age"]


@pfn.nodetest(sql.DeleteData)
async def test_delete_data(sqlite_env):
    _, test_db, conn_node = sqlite_env

    # create table via RecordPoint
    rec_node = sql.RecordPoint()
    rec_node.inputs["conn"].connect(conn_node.outputs["connection"])
    rec_node.inputs["table"].value = "to_delete"
    rec_node.inputs["value"].value = 1
    await run_until_complete(rec_node)

    # ensure table exists
    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dp_to_delete_INTEGER'"
        )
        assert await cursor.fetchone() is not None

    node = sql.DeleteData()
    node.inputs["conn"].connect(conn_node.outputs["connection"])
    node.inputs["table"].value = "dp_to_delete_INTEGER"

    await node

    async with aiosqlite.connect(test_db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dp_to_delete_INTEGER'"
        )
        assert await cursor.fetchone() is None


@pfn.nodetest([q_builder.execute_query, q_builder.SelectTable])
async def test_execute_query(sqlite_env):
    _, test_db, conn_node = sqlite_env
    async with aiosqlite.connect(test_db) as conn:
        await conn.execute(
            "CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INT)"
        )
        await conn.commit()
        await conn.execute("INSERT INTO test (name, age) VALUES ('John', 25)")
        await conn.commit()

    node = q_builder.execute_query()
    node.inputs["conn"].connect(conn_node.outputs["connection"])
    node.inputs["query"].value = q_builder.SQLQuery(
        table="test", columns=["name", "age"]
    )

    await node
    assert node.outputs["out"].value == [{"age": 25, "name": "John"}]
