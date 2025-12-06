from unittest import IsolatedAsyncioTestCase
from funcnodes_storage import sql
from funcnodes_storage.sql import q_builder
from funcnodes_core import NodeSpace, config, run_until_complete
import os
from pathlib import Path
import aiosqlite
import asyncio

try:
    import funcnodes_pandas as fnpd
except (ImportError, ModuleNotFoundError):
    fnpd = None


config.IN_NODE_TEST = True
config.set_in_test()


class TestSql(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = NodeSpace()
        root = Path(os.path.join(os.path.dirname(__file__), "files"))
        if not root.exists():
            root.mkdir()
        self.ns.set_property("files_dir", str(root))
        # clear files directory
        self.test_db = root / "test.db"

        if self.test_db.exists():
            # remove the test database
            try:
                self.test_db.unlink()
            except PermissionError:
                # connnect to the database and delete all tables
                async with aiosqlite.connect(self.test_db) as conn:
                    all_tables = await conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                    all_tables = [t[0] for t in await all_tables.fetchall()]
                    for table in all_tables:
                        if table != "sqlite_sequence":
                            await conn.execute(f"DROP TABLE {table}")

    async def asyncTearDown(self):
        if self.test_db.exists():
            # remove the test database
            try:
                self.test_db.unlink()
            except PermissionError:
                # connnect to the database and delete all tables
                async with aiosqlite.connect(self.test_db) as conn:
                    all_tables = await conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                    all_tables = [t[0] for t in await all_tables.fetchall()]
                    for table in all_tables:
                        if table != "sqlite_sequence":
                            await conn.execute(f"DROP TABLE {table}")

    async def test_conn(self):
        node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(node)
        node.inputs["db_path"].value = self.test_db.name

        await node

        self.assertIsInstance(
            node.outputs["connection"].value, sql.ManagedSQLiteConnection
        )

    async def test_add_int(self):
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name

        await con_node
        rec_node = sql.RecordPoint()

        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["value"].value = 5
        rec_node.inputs["table"].value = "test"

        await run_until_complete(con_node, rec_node)
        self.assertEqual(rec_node.inputs_ready(), True, rec_node.ready_state())

        self.assertEqual(rec_node.outputs["record"].value.value, 5)

        async with aiosqlite.connect(self.test_db) as conn:
            # list all tables
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
            tables = await cursor.fetchall()
            self.assertIn(("dp_test_INTEGER",), tables)

            cursor = await conn.execute("SELECT * FROM dp_test_INTEGER")
            res = await cursor.fetchall()
            self.assertEqual(res[0][2], 5)

    async def test_data_retrevial(self):
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name
        self.assertEqual(con_node.inputs_ready(), True, con_node.ready_state())
        await con_node

        rec_node = sql.RecordPoint()
        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["table"].value = "test"
        await run_until_complete(con_node, rec_node)
        for i in range(7):
            rec_node.inputs["value"].value = i
            await rec_node
            await asyncio.sleep(0.1)

        retrieval_node = sql.DataRetrieve()
        retrieval_node.inputs["conn"].connect(con_node.outputs["connection"])
        retrieval_node.inputs["table"].value = "test"
        await retrieval_node
        res = retrieval_node.outputs["results"].value
        self.assertEqual(len(res), 7)

    async def test_to_df(self):
        if fnpd is None:
            return
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name
        self.assertEqual(con_node.inputs_ready(), True, con_node.ready_state())
        await con_node

        rec_node = sql.RecordPoint()
        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["table"].value = "test"

        await run_until_complete(con_node, rec_node)
        for i in range(7):
            rec_node.inputs["value"].value = i
            await rec_node
            await asyncio.sleep(0.1)

        retrieval_node = sql.DataRetrieve()
        retrieval_node.inputs["conn"].connect(con_node.outputs["connection"])
        retrieval_node.inputs["table"].value = "test"

        to_df_node = sql.to_df()
        to_df_node.inputs["results"].connect(retrieval_node.outputs["results"])

        await run_until_complete(retrieval_node, to_df_node)
        res = retrieval_node.outputs["results"].value
        self.assertEqual(len(res), 7)
        df = to_df_node.outputs["out"].value
        self.assertEqual(len(df), 7)
        self.assertIsInstance(df, fnpd.pd.DataFrame)

    async def test_to_csv(self):
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name
        self.assertEqual(con_node.inputs_ready(), True, con_node.ready_state())
        await con_node

        rec_node = sql.RecordPoint()
        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["table"].value = "test"

        await run_until_complete(con_node, rec_node)
        for i in range(7):
            rec_node.inputs["value"].value = i
            await rec_node
            await asyncio.sleep(0.1)

        retrieval_node = sql.DataRetrieve()
        retrieval_node.inputs["conn"].connect(con_node.outputs["connection"])
        retrieval_node.inputs["table"].value = "test"

        to_csv_node = sql.to_csv()
        to_csv_node.inputs["results"].connect(retrieval_node.outputs["results"])

        await run_until_complete(retrieval_node, to_csv_node)
        res = retrieval_node.outputs["results"].value
        self.assertEqual(len(res), 7)
        csvs = to_csv_node.outputs["out"].value
        lines = csvs.split("\n")
        self.assertEqual(len(lines), 8, lines)  # 7 data lines and 1 header line

    async def test_add_float(self):
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name

        rec_node = sql.RecordPoint()

        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["value"].value = 4
        rec_node.inputs["table"].value = "test"
        rec_node.inputs["db_type"].value = "REAL"
        await run_until_complete(con_node, rec_node)

        rec_node.inputs["value"].value = 5.5
        await run_until_complete(rec_node)

    async def test_add_dict(self):
        con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(con_node)
        con_node.inputs["db_path"].value = self.test_db.name

        rec_node = sql.RecordPoint()

        rec_node.inputs["conn"].connect(con_node.outputs["connection"])
        rec_node.inputs["value"].value = 4
        rec_node.inputs["table"].value = "test"
        rec_node.inputs["db_type"].value = "REAL"
        await run_until_complete(con_node, rec_node)

        d = {
            "a": 1,
            "b": "foo",
            "c": {"d": 0.1},
            "e": [0, 1, 2],
        }
        rec_node.inputs["value"].value = d

        await run_until_complete(rec_node)

        out = rec_node.outputs["record"].value

        self.assertEqual(out, d)


class TestSqlBuilder(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = NodeSpace()
        root = Path(os.path.join(os.path.dirname(__file__), "files"))
        if not root.exists():
            root.mkdir()
        self.ns.set_property("files_dir", str(root))
        # clear files directory
        self.test_db = root / "test.db"
        self.con_node = sql.SQLiteConnectionNode()
        self.ns.add_node_instance(self.con_node)
        self.con_node.inputs["db_path"].value = self.test_db.name
        await self.con_node
        self.connection = self.con_node.outputs["connection"].value
        self.assertIsInstance(self.connection, sql.ManagedSQLiteConnection)

    async def asyncTearDown(self):
        if self.test_db.exists():
            # remove the test database
            try:
                self.test_db.unlink()
            except PermissionError:
                # connnect to the database and delete all tables
                async with aiosqlite.connect(self.test_db) as conn:
                    all_tables = await conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                    all_tables = [t[0] for t in await all_tables.fetchall()]
                    for table in all_tables:
                        if table != "sqlite_sequence":
                            await conn.execute(f"DROP TABLE {table}")

    async def test_SelectTable(self):
        node = q_builder.SelectTable()
        node.inputs["table"].value = "test"
        node.inputs["conn"].connect(self.con_node.outputs["connection"])
        await node
        res = node.outputs["out_query"].value

        self.assertEqual(res.build(), "SELECT * FROM test")

    async def test_comparison_filter(self):
        node = q_builder.comparison_filter()
        node.inputs["column"].value = "name"
        node.inputs["operator"].value = "="
        node.inputs["value"].value = "John"

        await node
        res = node.outputs["out"].value
        self.assertEqual(res.build(), "name = 'John'")

        node.inputs["value"].value = 5
        node.inputs["operator"].value = ">="

        await node
        res = node.outputs["out"].value
        self.assertEqual(res.build(), "name >= 5")

    async def test_and_filter(self):
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
        res = node.outputs["out"].value
        self.assertEqual(res.build(), "(name = 'John' AND age > 10)")

    async def test_or_filter(self):
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
        res = node.outputs["out"].value
        self.assertEqual(res.build(), "(name = 'John' OR age > 10)")

    async def test_not_filter(self):
        node = q_builder.not_filter()
        filter1 = q_builder.comparison_filter()
        filter1.inputs["column"].value = "name"
        filter1.inputs["operator"].value = "="
        filter1.inputs["value"].value = "John"

        node.inputs["query"].connect(filter1.outputs["out"])

        await run_until_complete(filter1, node)

        res = node.outputs["out"].value
        self.assertEqual(res.build(), "NOT (name = 'John')")

    async def test_in_filter(self):
        node = q_builder.in_filter()
        node.inputs["column"].value = "name"
        node.inputs["values"].value = ["John", "Doe"]

        await node
        res = node.outputs["out"].value
        self.assertEqual(res.build(), "name IN ('John', 'Doe')")

    async def test_get_tables(self):
        # add a table to the database
        async with aiosqlite.connect(self.test_db) as conn:
            await conn.execute("CREATE TABLE test (name TEXT)")
            await conn.commit()
        node = q_builder.get_tables()
        node.inputs["conn"].connect(self.con_node.outputs["connection"])
        await node
        res = node.outputs["out"].value
        self.assertEqual(res, ["test"])

    async def test_get_columns(self):
        # add a table to the database
        async with aiosqlite.connect(self.test_db) as conn:
            await conn.execute("CREATE TABLE test (name TEXT, age INT)")
            await conn.commit()
        node = q_builder.GetColumns()
        node.inputs["conn"].connect(self.con_node.outputs["connection"])
        node.inputs["table"].value = "test"
        await node
        res = node.outputs["columns"].value
        self.assertEqual(res, ["name", "age"])

    async def test_execute_query(self):
        async with aiosqlite.connect(self.test_db) as conn:
            await conn.execute(
                "CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INT)"
            )
            await conn.commit()
            await conn.execute("INSERT INTO test (name, age) VALUES ('John', 25)")
            await conn.commit()
        node = q_builder.execute_query()
        node.inputs["conn"].connect(self.con_node.outputs["connection"])
        node.inputs["query"].value = q_builder.SQLQuery(
            table="test", columns=["name", "age"]
        )

        await node
        res = node.outputs["out"].value
        self.assertEqual(res, [{"age": 25, "name": "John"}])
