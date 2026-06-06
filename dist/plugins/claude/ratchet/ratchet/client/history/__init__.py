"""Claude Code historical data loading and analysis.

This module provides a unified interface for loading Claude Code
conversation data from multiple sources:

- Claude Code native storage (~/.claude/projects/)
- Ratchet collector storage (~/.local/ratchet/)
- Parquet datasets (ZAI CC-Bench, NLILE, etc.)

Example:
    from ratchet.client.history import create_loader, Session
    from pathlib import Path

    # Create loader with default sources
    loader = create_loader()

    # Or with custom datasets
    loader = create_loader(
        dataset_paths={
            "zai_bench": Path("datasets/zai-cc-bench/train.parquet"),
        }
    )

    # Iterate over all sessions
    for session in loader.iter_all():
        print(f"[{session.metadata.source}] {session.metadata.session_id}")
        print(f"  Messages: {len(session.messages)}")
        print(f"  Tool calls: {session.stats.tool_call_count}")

    # Load specific session
    session = loader.load_from("claude_native", "abc123-...")
"""

from ratchet.client.history.loader import (
    DataLoader,
    create_loader,
    load_session_by_id,
    load_sessions_from_project,
)
from ratchet.client.history.models import (
    HistorySessionMetadata,
    HistorySessionStats,
    Message,
    Session,
    TokenUsage,
    ToolCall,
)
from ratchet.client.history.protocol import DataSource
from ratchet.client.history.sources import (
    ClaudeNativeSource,
    CodexSource,
    CursorSource,
    GeminiSource,
    OpenCodeSource,
    ParquetDatasetSource,
    RatchetSource,
)

__all__ = [
    "ClaudeNativeSource",
    "CodexSource",
    "CursorSource",
    "DataLoader",
    "DataSource",
    "GeminiSource",
    "HistorySessionMetadata",
    "HistorySessionStats",
    "Message",
    "OpenCodeSource",
    "ParquetDatasetSource",
    "RatchetSource",
    "Session",
    "TokenUsage",
    "ToolCall",
    "create_loader",
    "load_session_by_id",
    "load_sessions_from_project",
]
