import sqlite3


class JobDatabase:

    def __init__(self):
        self.conn = sqlite3.connect("data/jobs.db")
        self.cursor = self.conn.cursor()

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs(
                url TEXT PRIMARY KEY
            )
        """)

        self.conn.commit()

    def exists(self, url):
        self.cursor.execute(
            "SELECT 1 FROM jobs WHERE url=?",
            (url,)
        )
        return self.cursor.fetchone() is not None

    def save(self, url):
        self.cursor.execute(
            "INSERT OR IGNORE INTO jobs(url) VALUES(?)",
            (url,)
        )
        self.conn.commit()