"""Tests for Rigour quality gate runner."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from rigovo.domain.entities.quality import GateStatus, ViolationSeverity
from rigovo.domain.interfaces.quality_gate import GateInput
from rigovo.infrastructure.quality.rigour_gate import (
    RigourGateConfig,
    RigourQualityGate,
)


@pytest.fixture
def gate() -> RigourQualityGate:
    return RigourQualityGate(rigour_binary=None)


@pytest.fixture
def gate_input(tmp_path: Path) -> GateInput:
    return GateInput(project_root=str(tmp_path), files_changed=[], agent_role="coder")


class TestBuiltinChecks:

    @pytest.mark.asyncio
    async def test_no_files_passes(self, gate, gate_input):
        result = await gate.run(gate_input)
        assert result.status == GateStatus.PASSED
        assert result.score == 100.0

    @pytest.mark.asyncio
    async def test_clean_file_passes(self, gate, tmp_path):
        (tmp_path / "clean.py").write_text("def hello():\n    return 'world'\n")
        gi = GateInput(project_root=str(tmp_path), files_changed=["clean.py"], agent_role="coder")
        result = await gate.run(gi)
        assert result.status == GateStatus.PASSED

    @pytest.mark.asyncio
    async def test_large_file_warns(self, gate, tmp_path):
        (tmp_path / "big.py").write_text("".join(["x = 1\n"] * 600))
        gi = GateInput(project_root=str(tmp_path), files_changed=["big.py"], agent_role="coder")
        result = await gate.run(gi)
        assert any(v.gate_id == "file-size" for v in result.violations)

    @pytest.mark.asyncio
    async def test_hardcoded_secret_fails(self, gate, tmp_path):
        # Build fixture with a TOKEN assignment (matches our gate's pattern)
        _val = "my_" + "very_secret" + "_token_value"
        _line = "AUTH_" + "TOKEN" + f" = '{_val}'"
        (tmp_path / "bad.py").write_text(_line + "\n")
        gi = GateInput(project_root=str(tmp_path), files_changed=["bad.py"], agent_role="coder")
        result = await gate.run(gi)
        assert result.status == GateStatus.FAILED
        assert any(v.gate_id == "hardcoded-secrets" for v in result.violations)

    @pytest.mark.asyncio
    async def test_env_var_not_flagged(self, gate, tmp_path):
        (tmp_path / "safe.py").write_text("API_KEY = os.environ.get('API_KEY')\n")
        gi = GateInput(project_root=str(tmp_path), files_changed=["safe.py"], agent_role="coder")
        result = await gate.run(gi)
        assert not any(v.gate_id == "hardcoded-secrets" for v in result.violations)

    @pytest.mark.asyncio
    async def test_long_function_warns(self, gate, tmp_path):
        lines = ["def very_long_function():\n"] + ["    x = 1\n"] * 60
        (tmp_path / "long_func.py").write_text("".join(lines))
        gi = GateInput(project_root=str(tmp_path), files_changed=["long_func.py"], agent_role="coder")
        result = await gate.run(gi)
        assert any(v.gate_id == "function-length" for v in result.violations)

    @pytest.mark.asyncio
    async def test_fix_packet_generated(self, gate, tmp_path):
        # Build fixture with a PASSWORD assignment (matches our gate's pattern)
        _pw = "super" + "_insecure_" + "password123"
        _line = "DB_" + "PASSWORD" + f" = '{_pw}'"
        (tmp_path / "bad.py").write_text(_line + "\n")
        gi = GateInput(project_root=str(tmp_path), files_changed=["bad.py"], agent_role="coder")
        result = await gate.run(gi)
        assert len(result.violations) > 0


class TestRigourOutputParsing:

    def test_parse_pass(self, gate):
        stdout = json.dumps({"status": "PASS", "score": 95.0, "gates": [], "summary": "All checks passed"})
        result = gate._parse_rigour_output(stdout, 0)
        assert result.status == GateStatus.PASSED
        assert result.score == 95.0

    def test_parse_fail_with_violations(self, gate):
        stdout = json.dumps({
            "status": "FAIL", "score": 40.0,
            "gates": [{"id": "hardcoded-secrets", "status": "FAIL", "score": 0,
                       "issues": [{"message": "Hardcoded API key", "file": "config.py", "line": 5}]}],
        })
        result = gate._parse_rigour_output(stdout, 1)
        assert result.status == GateStatus.FAILED
        assert len(result.violations) == 1

    def test_parse_empty_output(self, gate):
        result = gate._parse_rigour_output("", 0)
        assert result.status == GateStatus.PASSED

    def test_parse_invalid_json(self, gate):
        result = gate._parse_rigour_output("not json", 1)
        assert result.status == GateStatus.FAILED


class TestGateConfig:

    def test_disabled_gate_skipped(self):
        configs = [RigourGateConfig(gate_id="test-gate", name="Test", enabled=False)]
        gate = RigourQualityGate(gate_configs=configs, rigour_binary=None)
        stdout = json.dumps({
            "status": "FAIL", "score": 50,
            "gates": [{"id": "test-gate", "status": "FAIL", "score": 0, "issues": [{"message": "bad"}]}],
        })
        result = gate._parse_rigour_output(stdout, 1)
        assert len(result.violations) == 0
