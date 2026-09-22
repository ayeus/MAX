"""Explicit memory operations for MAX."""

from pydantic import BaseModel
from datetime import datetime, timezone
from .database import get_db_connection


class MemoryItem(BaseModel):
    id: int
    key: str
    content: str
    category: str
    created_at: str
    updated_at: str


class MemoryManager:
    """Manages explicit user memories with database persistence."""

    def remember(self, key: str, content: str, category: str = "general") -> bool:
        """Save or update an explicit memory."""
        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO memories (key, content, category, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        content = excluded.content,
                        category = excluded.category,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key.strip().lower(), content.strip(), category.strip()),
                )
            return True
        except Exception:
            return False

    def forget(self, key: str) -> bool:
        """Remove a memory by key."""
        conn = get_db_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM memories WHERE key = ?", (key.strip().lower(),))
                return cur.rowcount > 0
        except Exception:
            return False

    def get_memory(self, key: str) -> MemoryItem | None:
        """Get a single memory."""
        conn = get_db_connection()
        cur = conn.execute("SELECT * FROM memories WHERE key = ?", (key.strip().lower(),))
        row = cur.fetchone()
        if row:
            return MemoryItem(
                id=row["id"],
                key=row["key"],
                content=row["content"],
                category=row["category"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
        return None

    def list_memories(self, category: str | None = None) -> list[MemoryItem]:
        """List all stored memories."""
        conn = get_db_connection()
        if category:
            cur = conn.execute("SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC", (category,))
        else:
            cur = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC")
        rows = cur.fetchall()
        return [
            MemoryItem(
                id=r["id"],
                key=r["key"],
                content=r["content"],
                category=r["category"],
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def clear_memories(self) -> int:
        """Clear all memories."""
        conn = get_db_connection()
        with conn:
            cur = conn.execute("DELETE FROM memories")
            return cur.rowcount


memory_manager = MemoryManager()
