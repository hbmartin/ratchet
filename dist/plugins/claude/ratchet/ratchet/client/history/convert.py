"""Standalone converter script for extracting chat history from various sources.

Usage:
    # Extract all messages (default mode)
    python -m ratchet.client.history.convert cursor --output cursor_messages.jsonl

    # Extract complete sessions with metadata
    python -m ratchet.client.history.convert cursor \
      --output cursor_sessions.jsonl \
      --mode sessions

    # Extract first 10 sessions
    python -m ratchet.client.history.convert cursor \
      --output cursor_sample.jsonl \
      --limit 10

    # Extract specific session
    python -m ratchet.client.history.convert gemini \
      --output gemini_session_msgs.jsonl \
      --session-id abc123

    # Custom path
    python -m ratchet.client.history.convert claude_native \
      --output claude_native.jsonl \
      --base-path ~/custom/claude/path

    # Parquet (requires source-name)
    python -m ratchet.client.history.convert parquet \
      --output parquet.jsonl \
      --base-path path/to/dataset.parquet \
      --source-name test_dataset
"""

import argparse
import sys
from pathlib import Path

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

SOURCE_NAMES = ("cursor", "gemini", "claude", "codex", "ratchet", "opencode", "parquet")


def _source_names() -> str:
    return ", ".join(SOURCE_NAMES)


def _build_source(tool: str, base_path: Path | None, source_name: str | None) -> DataSource:
    if tool == "parquet":
        if not source_name:
            raise ValueError("--source-name required for parquet")
        if not base_path:
            raise ValueError("--base-path required for parquet")
        return ParquetDatasetSource(path=base_path, source_name=source_name)
    if tool == "cursor":
        return CursorSource(base_path=base_path)
    if tool == "gemini":
        return GeminiSource(base_path=base_path)
    if tool == "claude":
        return ClaudeNativeSource(base_path=base_path)
    if tool == "codex":
        return CodexSource(base_path=base_path)
    if tool == "ratchet":
        return RatchetSource(base_path=base_path)
    if tool == "opencode":
        return OpenCodeSource(base_path=base_path)
    raise ValueError(f"Unknown tool: {tool}. Available: {_source_names()}")


def run_converter(
    tool: str,
    output: Path,
    base_path: Path | None,
    session_id: str | None,
    limit: int | None,
    mode: str,
    **kwargs,
):
    """Run converter to export chat history.

    Args:
        tool: Tool name (cursor, gemini, etc.)
        output: Output JSONL file path
        base_path: Override default base path
        session_id: Load specific session only
        limit: Limit to first N sessions
        mode: Export mode (messages|sessions)
        **kwargs: Additional tool-specific args (e.g., source_name for parquet)
    """
    source = _build_source(tool, base_path, kwargs.get("source_name"))

    # Load sessions
    if session_id:
        sessions = [source.load_session(session_id)]
    else:
        sessions = list(source.iter_sessions())
        if limit:
            sessions = sessions[:limit]

    # Export based on mode
    with output.open("w") as f:
        if mode == "messages":
            # Flat message stream (default)
            msg_count = 0
            for session in sessions:
                for msg in session.messages:
                    f.write(msg.model_dump_json() + "\n")
                    msg_count += 1
            print(f"Exported {msg_count} messages from {len(sessions)} sessions")

        elif mode == "sessions":
            # Complete session objects with metadata
            for session in sessions:
                f.write(session.model_dump_json() + "\n")
            print(f"Exported {len(sessions)} complete sessions")

    print(f"Output: {output}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Extract chat history from various sources to JSONL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract messages (default mode)
  python -m ratchet.client.history.convert cursor --output cursor_messages.jsonl

  # Extract complete sessions
  python -m ratchet.client.history.convert cursor \
    --output cursor_sessions.jsonl --mode sessions

  # Limit to 10 sessions
  python -m ratchet.client.history.convert cursor --output out.jsonl --limit 10

  # Specific session
  python -m ratchet.client.history.convert gemini \
    --output gemini_session.jsonl --session-id abc123

  # Custom base path
  python -m ratchet.client.history.convert claude_native \
    --output out.jsonl --base-path ~/custom/path

  # Parquet dataset
  python -m ratchet.client.history.convert parquet \
    --output out.jsonl \
    --base-path dataset.parquet \
    --source-name my_dataset
""",
    )

    parser.add_argument(
        "tool",
        choices=list(SOURCE_NAMES),
        help="Tool name to extract from",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--base-path",
        type=Path,
        help="Override default base path",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Load specific session only",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit to first N sessions",
    )
    parser.add_argument(
        "--mode",
        choices=["messages", "sessions"],
        default="sessions",
        help="Export mode: messages (flat stream) or sessions (with metadata)",
    )
    parser.add_argument(
        "--source-name",
        type=str,
        help="Source identifier for parquet (required for parquet tool)",
    )

    args = parser.parse_args()

    # Validate parquet-specific args
    if args.tool == "parquet":
        if not args.source_name:
            parser.error("--source-name is required for parquet tool")
        if not args.base_path:
            parser.error("--base-path is required for parquet tool")

    try:
        run_converter(
            tool=args.tool,
            output=args.output,
            base_path=args.base_path,
            session_id=args.session_id,
            limit=args.limit,
            mode=args.mode,
            source_name=args.source_name,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
