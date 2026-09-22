"""User preferences storage for MAX."""

from .database import get_db_connection


class PreferenceManager:
    """Manages persistent key-value user preferences."""

    def set_preference(self, key: str, value: str) -> bool:
        conn = get_db_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO preferences (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key.strip().lower(), value.strip()),
                )
            return True
        except Exception:
            return False

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        conn = get_db_connection()
        cur = conn.execute("SELECT value FROM preferences WHERE key = ?", (key.strip().lower(),))
        row = cur.fetchone()
        if row:
            return row["value"]
        return default

    def list_preferences(self) -> dict[str, str]:
        conn = get_db_connection()
        cur = conn.execute("SELECT key, value FROM preferences")
        return {r["key"]: r["value"] for r in cur.fetchall()}


preference_manager = PreferenceManager()
