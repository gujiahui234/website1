"""University persistence backends for the application."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, cast

import pymysql  # type: ignore[import-untyped]
from pymysql.connections import Connection  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]
from pymysql.err import IntegrityError  # type: ignore[import-untyped]

from alt_web01.student_store import MySQLSettings


class DuplicateUniversityError(ValueError):
    """Raised when a university name or code already exists."""


@dataclass(frozen=True)
class SavedUniversity:
    """A university record together with its database save time."""

    number: int
    name: str
    code: str
    type: str
    nature: str
    saved_at: dt.datetime


class UniversityStore(Protocol):
    """Persistence contract used by the university views."""

    def list_universities(self) -> list[SavedUniversity]:
        """Return all saved universities, newest first."""

    def save_university(
        self, *, name: str, code: str, type: str, nature: str
    ) -> SavedUniversity:
        """Persist and return one university.

        Args:
            name: Unique university name.
            code: Unique three-digit university code.
            type: University ownership type.
            nature: University classification.

        Returns:
            SavedUniversity: The persisted university.

        Raises:
            DuplicateUniversityError: If the name or code already exists.
        """


@dataclass
class MemoryUniversityStore:
    """Process-local fallback used by local development and unit tests."""

    universities: list[SavedUniversity] = field(default_factory=list)
    next_number: int = 1

    def list_universities(self) -> list[SavedUniversity]:
        """Return all process-local records, newest first."""
        return sorted(
            self.universities,
            key=lambda university: (university.saved_at, university.number),
            reverse=True,
        )

    def save_university(
        self, *, name: str, code: str, type: str, nature: str
    ) -> SavedUniversity:
        """Append one unique university to process-local memory.

        Args:
            name: Unique university name.
            code: Unique three-digit university code.
            type: University ownership type.
            nature: University classification.

        Returns:
            SavedUniversity: The appended university.

        Raises:
            DuplicateUniversityError: If the name or code already exists.
        """
        normalized_name = name.casefold()
        if any(
            university.name.casefold() == normalized_name
            or university.code == code
            for university in self.universities
        ):
            raise DuplicateUniversityError("高校名称或代码已存在。")

        university = SavedUniversity(
            number=self.next_number,
            name=name,
            code=code,
            type=type,
            nature=nature,
            saved_at=dt.datetime.now(),
        )
        self.next_number += 1
        self.universities.append(university)
        return university


class MySQLUniversityStore:
    """University store backed by a separately managed MySQL container."""

    def __init__(self, settings: MySQLSettings) -> None:
        """Initialize the store with validated MySQL settings.

        Args:
            settings: Non-root MySQL connection settings.
        """
        self._settings = settings

    def _connect(self) -> Connection:
        """Open a transactional MySQL connection.

        Returns:
            Connection: A configured PyMySQL connection.
        """
        return pymysql.connect(
            host=self._settings.host,
            port=self._settings.port,
            user=self._settings.user,
            password=self._settings.password,
            database=self._settings.database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
            connect_timeout=5,
        )

    def ensure_schema(self) -> None:
        """Create the university table and uniqueness constraints."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS universities (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        name VARCHAR(100) NOT NULL,
                        code CHAR(5) NOT NULL,
                        university_type ENUM('民办', '公办') NOT NULL,
                        nature ENUM('985', '211', '一本', '其他') NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        UNIQUE KEY uq_universities_name (name),
                        UNIQUE KEY uq_universities_code (code)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    "ALTER TABLE universities "
                    "MODIFY COLUMN code CHAR(5) NOT NULL"
                )
            connection.commit()
        finally:
            connection.close()

    def list_universities(self) -> list[SavedUniversity]:
        """Load all saved universities from MySQL, newest first."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, name, code, university_type, nature, created_at "
                    "FROM universities "
                    "ORDER BY created_at DESC, id DESC"
                )
                rows = cast(list[dict[str, object]], cursor.fetchall())
        finally:
            connection.close()

        return [
            SavedUniversity(
                number=cast(int, row["id"]),
                name=str(row["name"]),
                code=str(row["code"]),
                type=str(row["university_type"]),
                nature=str(row["nature"]),
                saved_at=cast(dt.datetime, row["created_at"]),
            )
            for row in rows
        ]

    def save_university(
        self, *, name: str, code: str, type: str, nature: str
    ) -> SavedUniversity:
        """Insert one unique university in a transaction.

        Args:
            name: Unique university name.
            code: Unique three-digit university code.
            type: University ownership type.
            nature: University classification.

        Returns:
            SavedUniversity: The inserted university.

        Raises:
            DuplicateUniversityError: If the name or code already exists.
        """
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO universities "
                    "(name, code, university_type, nature) "
                    "VALUES (%s, %s, %s, %s)",
                    (name, code, type, nature),
                )
                university_id = cursor.lastrowid
            connection.commit()
        except IntegrityError as error:
            connection.rollback()
            if error.args and error.args[0] == 1062:
                raise DuplicateUniversityError("高校名称或代码已存在。") from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if university_id is None:
            raise RuntimeError("MySQL did not return a university id")
        return SavedUniversity(
            number=int(university_id),
            name=name,
            code=code,
            type=type,
            nature=nature,
            saved_at=dt.datetime.now(),
        )
