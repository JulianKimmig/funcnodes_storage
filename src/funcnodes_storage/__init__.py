import funcnodes as fn

from .sql import NODE_SHELF as SQL_NODE_SHELF

NODE_SHELF = fn.Shelf(
    nodes=[],
    name="Funcnodes Storage",
    description="The nodes of Funcnodes Storage package",
    subshelves=[SQL_NODE_SHELF],
)
