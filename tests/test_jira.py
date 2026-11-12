"""
tests/test_jira.py — Unit tests for Jira task creation and validation.
"""

from unittest.mock import MagicMock
import pytest
from document_generator import ConfluenceDocumentOrchestrator
from validators import validate_jira_input


def test_validate_jira_input_valid():
    errors = validate_jira_input(
        project_key="KAN",
        summary="Implement Redis session caching",
        issue_type="Task",
        description="Detailed description text",
    )
    assert errors == []


def test_validate_jira_input_invalid_project_key():
    errors = validate_jira_input(
        project_key="invalid_lowercase_key_123456789",
        summary="Implement caching",
        issue_type="Task",
    )
    assert len(errors) > 0
    assert any("Invalid project key" in e for e in errors)


def test_validate_jira_input_empty_summary():
    errors = validate_jira_input(
        project_key="KAN",
        summary="",
        issue_type="Task",
    )
    assert any("summary / title cannot be empty" in e for e in errors)


def test_validate_jira_input_invalid_issue_type():
    errors = validate_jira_input(
        project_key="KAN",
        summary="Valid summary",
        issue_type="SuperTask",
    )
    assert any("Invalid issue type" in e for e in errors)


def test_create_jira_task_mock_flow():
    orch = ConfluenceDocumentOrchestrator()
    orch.mcp.set_mock_pages([])

    result = orch.create_jira_task(
        project_key="KAN",
        summary="Setup CloudWatch Alarm for S3 Purge",
        description="## Tasks\n- [ ] Configure alert threshold",
        issue_type="Task",
        priority="High",
        labels=["devops", "monitoring"],
    )

    assert result["success"] is True
    assert "issue" in result
    issue = result["issue"]
    assert issue["project_key"] == "KAN"
    assert issue["issue_type"] == "Task"
    assert "KAN-" in issue["key"]
    assert "url" in issue

