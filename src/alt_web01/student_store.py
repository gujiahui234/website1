"""Student persistence backends for the application."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Mapping, Protocol, cast

import pymysql  # type: ignore[import-untyped]
from class_roster import Student
from pymysql.connections import Connection  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]


class StudentStore(Protocol):
    """Persistence contract used by the student views."""

    def list_students(self) -> list[Student]:
        """Return all saved students in creation order."""

    def save_student(
        self, *, name: str, gender: str, birthday: dt.date
    ) -> Student:
        """Persist and return one student."""


@dataclass
class MemoryStudentStore:
    """Process-local fallback used by local development and unit tests."""

    students: list[Student] = field(default_factory=list)

    def list_students(self) -> list[Student]:
        """Return a snapshot of the process-local roster."""
        return list(self.students)

    def save_student(
        self, *, name: str, gender: str, birthday: dt.date
    ) -> Student:
        """Append one student to process-local memory."""
        student = Student(
            number=len(self.students) + 1,
            name=name,
            gender=gender,
            birthday=birthday,
        )
        self.students.append(student)
        return student


@dataclass(frozen=True)
class MySQLSettings:
    """Non-root MySQL connection settings."""

    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> MySQLSettings:
        """Build validated settings from the Flask configuration."""
        host = str(config.get("MYSQL_HOST", "")).strip()
        database = str(config.get("MYSQL_DATABASE", "")).strip()
        user = str(config.get("MYSQL_USER", "")).strip()
        password = str(config.get("MYSQL_PASSWORD", ""))

        if user.casefold() == "root":
            raise RuntimeError("MYSQL_USER must be a non-root application account")
        if not host or not database or not user or not password:
            raise RuntimeError(
                "MYSQL_HOST, MYSQL_DATABASE, MYSQL_USER and MYSQL_PASSWORD "
                "are required when STUDENT_STORE=mysql"
            )

        try:
            port = int(str(config.get("MYSQL_PORT", 3306)))
        except (TypeError, ValueError) as error:
            raise RuntimeError("MYSQL_PORT must be an integer") from error

        return cls(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )


class MySQLStudentStore:
    """Student store backed by a separately managed MySQL container."""

    def __init__(self, settings: MySQLSettings) -> None:
        self._settings = settings

    def _connect(self) -> Connection:
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
        """Create the student table if it does not exist."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS students (
                        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        name VARCHAR(40) NOT NULL,
                        birthday DATE NOT NULL,
                        gender ENUM('男', '女') NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id)
                    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                    """
                )
            connection.commit()
        finally:
            connection.close()

    def list_students(self) -> list[Student]:
        """Load all students from MySQL in creation order."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, name, birthday, gender FROM students ORDER BY id"
                )
                rows = cast(list[dict[str, object]], cursor.fetchall())
        finally:
            connection.close()

        return [
            Student(
                number=cast(int, row["id"]),
                name=str(row["name"]),
                birthday=cast(dt.date, row["birthday"]),
                gender=str(row["gender"]),
            )
            for row in rows
        ]

    def save_student(
        self, *, name: str, gender: str, birthday: dt.date
    ) -> Student:
        """Insert one student in a transaction and return its database id."""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO students (name, birthday, gender) "
                    "VALUES (%s, %s, %s)",
                    (name, birthday, gender),
                )
                student_id = cursor.lastrowid
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if student_id is None:
            raise RuntimeError("MySQL did not return a student id")
        return Student(
            number=int(student_id),
            name=name,
            gender=gender,
            birthday=birthday,
        )
