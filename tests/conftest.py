import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def set_funcnodes_config_dir(tmp_path_factory):
    cfg_dir = tmp_path_factory.mktemp("funcnodes_cfg")
    os.environ["FUNCNODES_CONFIG_DIR"] = str(cfg_dir)
    return cfg_dir
