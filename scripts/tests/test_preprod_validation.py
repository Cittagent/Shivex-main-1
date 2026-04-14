from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "preprod_validation.py"
SPEC = importlib.util.spec_from_file_location("preprod_validation", MODULE_PATH)
assert SPEC and SPEC.loader
preprod_validation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preprod_validation
SPEC.loader.exec_module(preprod_validation)


def _config(tmp_path: Path, *, mode: str = "full-validation") -> preprod_validation.RunnerConfig:
    return preprod_validation.RunnerConfig(
        mode=mode,
        stop_on_first_defect=False,
        artifacts_dir=tmp_path / "artifacts",
        cert_python=sys.executable,
        auth_url="http://localhost:8090",
        device_url="http://localhost:8000",
        data_url="http://localhost:8081",
        rule_url="http://localhost:8002",
        reporting_url="http://localhost:8085",
        analytics_url="http://localhost:8003",
        waste_url="http://localhost:8087",
        energy_url="http://localhost:8010",
        ui_url="http://localhost:3000",
        super_admin_email="manash.ray@cittagent.com",
        super_admin_password="Shivex@2706",
        super_admin_full_name="Shivex Super-Admin",
        live_org_admin_email="vedanth.shetty@cittagent.com",
        live_org_admin_password="zaqmlp123",
        seed_password="Validate123!",
        http_timeout=10.0,
        reset_stack=False,
    )


def test_classify_failure_marks_import_errors_as_harness_issue(tmp_path: Path) -> None:
    runner = preprod_validation.PreprodValidationRunner(_config(tmp_path))
    try:
        assert (
            runner._classify_failure(
                "python -m pytest tests/test_example.py",
                "ImportError: cannot import name 'op' from 'alembic'",
            )
            == "validation harness issue"
        )
    finally:
        runner.close()


def test_classify_failure_marks_connectivity_as_environment_issue(tmp_path: Path) -> None:
    runner = preprod_validation.PreprodValidationRunner(_config(tmp_path))
    try:
        assert (
            runner._classify_failure(
                "health-verification",
                "http://localhost:8090/health did not become healthy within 120s (Connection refused)",
            )
            == "environment/data issue"
        )
    finally:
        runner.close()


def test_recommendation_requires_full_run_for_go(tmp_path: Path) -> None:
    quick_runner = preprod_validation.PreprodValidationRunner(_config(tmp_path / "quick", mode="current-live"))
    full_runner = preprod_validation.PreprodValidationRunner(_config(tmp_path / "full", mode="full-validation"))
    try:
        for runner in (quick_runner, full_runner):
            for item_id, item in runner.checklist.items():
                if item_id == "final_go_no_go":
                    continue
                runner.mark_pass(item_id, f"{item.title} passed.")

        quick = quick_runner._recommendation()
        full = full_runner._recommendation()

        assert quick["decision"] == "NO-GO"
        assert "Quick gate does not execute the full release checklist." == quick["reason"]
        assert full["decision"] == "GO"
    finally:
        quick_runner.close()
        full_runner.close()


def test_build_report_includes_required_sections(tmp_path: Path) -> None:
    runner = preprod_validation.PreprodValidationRunner(_config(tmp_path))
    try:
        runner.mark_pass("fresh_reset_sanity", "Fresh reset sanity passed.")
        report = runner.build_report()

        assert set(report) >= {
            "validation_setup",
            "findings",
            "fixes_applied",
            "validation_results",
            "logs_review",
            "production_recommendation",
            "follow_ups",
            "commands",
            "generated_at",
        }
        assert any(item["item_id"] == "fresh_reset_sanity" for item in report["validation_results"])
    finally:
        runner.close()


def test_make_config_maps_full_reset_to_full_validation_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(preprod_validation, "ARTIFACTS_ROOT", tmp_path)
    config = preprod_validation.make_config(argparse.Namespace(mode="full-reset", stop_on_first_defect=True))

    assert config.mode == "full-validation"
    assert config.reset_stack is True
    assert config.stop_on_first_defect is True
