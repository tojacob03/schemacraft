import sqlite3
from pathlib import Path

import pytest

CHINOOK = Path(__file__).parent / "fixtures" / "chinook.sqlite"


@pytest.fixture(scope="session")
def chinook_url():
    return f"sqlite:///{CHINOOK}"


@pytest.fixture(scope="session")
def library_url(tmp_path_factory):
    """Small database with the cases Chinook lacks: an unindexed foreign key, a view, many nulls."""
    path = tmp_path_factory.mktemp("db") / "library.sqlite"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE author (id INTEGER PRIMARY KEY, name TEXT NOT NULL, bio TEXT);
        CREATE TABLE book (id INTEGER PRIMARY KEY, author_id INTEGER REFERENCES author(id), title TEXT);
        CREATE TABLE review (id INTEGER PRIMARY KEY, book_id INTEGER REFERENCES book(id), stars INTEGER);
        CREATE INDEX ix_review_book ON review (book_id);
        CREATE VIEW top_books AS SELECT book_id, avg(stars) AS stars FROM review GROUP BY book_id;
    """)
    con.executemany("INSERT INTO author VALUES (?, ?, ?)",
                    [(i, f"a{i}", None if i % 5 else "bio") for i in range(50)])  # bio 80 % null
    con.executemany("INSERT INTO book VALUES (?, ?, ?)", [(i, i % 50, f"b{i}") for i in range(200)])
    con.executemany("INSERT INTO review VALUES (?, ?, ?)", [(i, i % 200, i % 5 + 1) for i in range(1000)])
    con.commit()
    con.close()
    return f"sqlite:///{path}"
