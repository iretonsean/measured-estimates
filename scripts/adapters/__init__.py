"""Agent adapters (REQ-30). v0.1.0 ships Claude Code only; see CONTRIBUTING.md to add another agent."""
from __future__ import annotations


def get(name: str = 'claude-code'):
    if name == 'claude-code':
        from .claude_code import ClaudeCode
        return ClaudeCode()
    raise ValueError(f'unknown agent: {name}')
