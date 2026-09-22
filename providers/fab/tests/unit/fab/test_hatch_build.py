# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_HATCH_BUILD_PATH = Path(__file__).resolve().parents[3] / "hatch_build.py"


def _load_hatch_build():
    # hatchling is a build-system dependency, not a test dependency.
    for name in (
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.config",
        "hatchling.builders.plugin",
        "hatchling.builders.plugin.interface",
        "hatchling.plugin",
        "hatchling.plugin.manager",
    ):
        sys.modules.setdefault(name, mock.MagicMock())
    spec = importlib.util.spec_from_file_location("fab_hatch_build", _HATCH_BUILD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {_HATCH_BUILD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hatch_build = _load_hatch_build()


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (0, "Assets compiled successfully\n", ""),
        (1, "Compile FAB provider assets Failed\n- files were modified by this hook\n", ""),
        (1, "", "files were modified by this hook\n"),
    ],
)
@mock.patch.object(hatch_build, "run")
def test_run_prek_compile_accepts_success_and_rewrites(mock_run, returncode, stdout, stderr):
    mock_run.return_value = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    hatch_build.run_prek_compile(["prek", "run", "compile-fab-assets"], cwd=".")
    mock_run.assert_called_once_with(
        ["prek", "run", "compile-fab-assets"], cwd=".", check=False, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (1, "Compile FAB provider assets Failed\npnpm: command not found\n"),
        (2, "prek: hook not found\n"),
    ],
)
@mock.patch.object(hatch_build, "run")
def test_run_prek_compile_raises_for_real_failures(mock_run, returncode, output):
    mock_run.return_value = SimpleNamespace(returncode=returncode, stdout=output, stderr="")
    with pytest.raises(RuntimeError, match="failed with exit status"):
        hatch_build.run_prek_compile(["prek", "run", "compile-fab-assets"], cwd=".")
