"""Major group persistence backends for the application."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, cast

import pymysql  # type: ignore[import-untyped]
from pymysql.connections import Connection  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]
from pymysql.err import IntegrityError  # type: ignore[import-untyped]

from alt_web01.student_store import MySQLSettings


class DuplicateMajorGroupError(ValueError):
    """Raised when a major group name or code already exists at a university."""


@dataclass(frozen=True)
class SavedMajorGroup:
    """A major group record together with its university and save time."""

    number: int
    university_number: int
    university_name: str
    name: str
    code: str
    saved_at: dt.datetime


class MajorGroupStore(Protocol):
    """Persistence contract used by the major group view."""

    def list_major_groups(
        self, *, university_number: int
    ) -> list[SavedMajorGroup]:
        """Return all major groups for one university, newest first.

        Args:
            university_number: Saved university identifier.

        Returns:
            list[SavedMajorGroup]: Matching major groups.
        """

    def save_major_group(
        self,
        *,
        university_number: int,
        university_name: str,
        name: str,
        code: str,
    ) -> SavedMajorGroup:
        """Persist and return one major group.

        Args:
            university_number: Parent university identifier.
            university_name: Parent university display name.
            name: Major group name, unique within the university.
            code: Five-digit code, unique within the university.

        Returns:
            SavedMajorGroup: The persisted major group.

        Raises:
            DuplicateMajorGroupError: If the name or code already exists.
        """


@dataclass
class MemoryMajorGroupStore:
    """Process-local fallback used by local development and unit tests."""

    major_groups: list[SavedMajorGroup] = field(default_factory=list)
    next_number: int = 1

    def list_major_groups(
        self, *, university_number: int
    ) -> list[SavedMajorGroup]:
        """Return all groups at one university, newest first.

        Args:
            university_number: Saved university identifier.

        Returns:
            list[SavedMajorGroup]: Matching process-local groups.
        """
        return sorted(
            (
                group
                for group in self.major_groups
                if group.university_number == university_number
            ),
            key=lambda group: (group.saved_at, group.number),
            reverse=True,
        )

    def save_major_group(
        self,
        *,
        university_number: int,
        university_name: str,
        name: str,
        code: str,
    ) -> SavedMajorGroup:
        """Append one university-scoped unique major group.

        Args:
            university_number: Parent university identifier.
            university_name: Parent university display name.
            name: Major group name, unique within the university.
            code: Five-digit code, unique within the university.

        Returns:
            SavedMajorGroup: The appended major group.

        Raises:
            DuplicateMajorGroupError: If the name or code already exists.
        """
        normalized_name = name.casefold()
        if any(
            group.university_number == university_number
            and (group.name.casefold() == normalized_name or group.code == code)
            for group in self.major_groups
        ):
            raise DuplicateMajorGroupError("该高校内专业组名称或代码已存在。")

        major_group = SavedMajorGroup(
            number=self.next_number,
            university_number=university_number,
            university_name=university_name,
            name=name,
            code=code,
            saved_at=dt.datetime.now(),
        )
        self.next_number += 1
        self.major_groups.append(major_group)
        return major_group


class MySQLMajorGroupStore:
    """Major group store backed by a separately managed MySQL container."""

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
        """Create the major group table and university-scoped constraints."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS major_groups (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        university_id BIGINT UNSIGNED NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        code VARCHAR(5) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id),
                        UNIQUE KEY uq_major_groups_university_name
                            (university_id, name),
                        UNIQUE KEY uq_major_groups_university_code
                            (university_id, code),
                        CONSTRAINT fk_major_groups_university
                            FOREIGN KEY (university_id) REFERENCES universities (id)
                            ON DELETE CASCADE
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    "ALTER TABLE major_groups "
                    "MODIFY COLUMN code VARCHAR(5) NOT NULL"
                )
            connection.commit()
        finally:
            connection.close()

    def list_major_groups(
        self, *, university_number: int
    ) -> list[SavedMajorGroup]:
        """Load all major groups for one university from MySQL.

        Args:
            university_number: Saved university identifier.

        Returns:
            list[SavedMajorGroup]: Matching database records.
        """
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT major_groups.id, major_groups.university_id, "
                    "universities.name AS university_name, major_groups.name, "
                    "major_groups.code, major_groups.created_at "
                    "FROM major_groups "
                    "INNER JOIN universities "
                    "ON universities.id = major_groups.university_id "
                    "WHERE major_groups.university_id = %s "
                    "ORDER BY major_groups.created_at DESC, major_groups.id DESC",
                    (university_number,),
                )
                rows = cast(list[dict[str, object]], cursor.fetchall())
        finally:
            connection.close()

        return [
            SavedMajorGroup(
                number=cast(int, row["id"]),
                university_number=cast(int, row["university_id"]),
                university_name=str(row["university_name"]),
                name=str(row["name"]),
                code=str(row["code"]),
                saved_at=cast(dt.datetime, row["created_at"]),
            )
            for row in rows
        ]

    def save_major_group(
        self,
        *,
        university_number: int,
        university_name: str,
        name: str,
        code: str,
    ) -> SavedMajorGroup:
        """Insert one university-scoped unique major group.

        Args:
            university_number: Parent university identifier.
            university_name: Parent university display name.
            name: Major group name, unique within the university.
            code: Five-digit code, unique within the university.

        Returns:
            SavedMajorGroup: The inserted major group.

        Raises:
            DuplicateMajorGroupError: If the name or code already exists.
        """
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO major_groups (university_id, name, code) "
                    "VALUES (%s, %s, %s)",
                    (university_number, name, code),
                )
                major_group_id = cursor.lastrowid
            connection.commit()
        except IntegrityError as error:
            connection.rollback()
            if error.args and error.args[0] == 1062:
                raise DuplicateMajorGroupError(
                    "该高校内专业组名称或代码已存在。"
                ) from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if major_group_id is None:
            raise RuntimeError("MySQL did not return a major group id")
        return SavedMajorGroup(
            number=int(major_group_id),
            university_number=university_number,
            university_name=university_name,
            name=name,
            code=code,
            saved_at=dt.datetime.now(),
        )
