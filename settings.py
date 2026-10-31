"""Per-server settings, persisted in a small sqlite database.

Only a guild ID and its settings are stored; no message content or user data.
Settings are cached in memory so that checking one on every message costs
nothing, and writes go straight through to disk so they survive restarts.
"""

import os
import sqlite3

DEFAULT_DB_PATH = 'settings.db'


class GuildSettings:
    def __init__(self, path=None):
        self._con = sqlite3.connect(path or os.environ.get('DB_PATH', DEFAULT_DB_PATH))
        self._con.execute(
            'CREATE TABLE IF NOT EXISTS guild_settings ('
            ' guild_id INTEGER PRIMARY KEY,'
            ' delete_original INTEGER NOT NULL DEFAULT 0'
            ')'
        )
        self._con.commit()
        self._delete_original = {
            guild_id: bool(value)
            for guild_id, value in self._con.execute('SELECT guild_id, delete_original FROM guild_settings')
        }

    def get_delete_original(self, guild_id):
        return self._delete_original.get(guild_id, False)

    def set_delete_original(self, guild_id, enabled):
        self._con.execute(
            'INSERT INTO guild_settings (guild_id, delete_original) VALUES (?, ?)'
            ' ON CONFLICT(guild_id) DO UPDATE SET delete_original = excluded.delete_original',
            (guild_id, int(enabled)),
        )
        self._con.commit()
        self._delete_original[guild_id] = bool(enabled)

    def close(self):
        self._con.close()
