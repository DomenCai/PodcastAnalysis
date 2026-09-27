"""Read-only SQLite access for the public application (no schema initialization)."""

from __future__ import annotations

import sqlite3
from server.subscriptions import SubscriptionStore


class ReadOnlySubscriptionStore(SubscriptionStore):
    def connect(self) -> sqlite3.Connection:
        # Never create a directory/database or change journal mode from public HTTP.
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def initialize(self) -> None:
        raise RuntimeError("公网数据库连接不可执行初始化或迁移")
