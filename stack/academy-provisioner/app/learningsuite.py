from __future__ import annotations

from typing import Any

import requests

from .models import EligibleUser


class ProvisioningError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RequestsLearningSuiteClient:
    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session: requests.Session | Any | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.session = session or requests.Session()
        self.headers = {"X-API-KEY": api_key}
        self.timeout_seconds = timeout_seconds

    def resolve_course_id(self, course_name: str) -> str:
        response = self.session.get(
            f"{self.api_base_url}/courses/published",
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        courses = self._json(response, "courses_lookup_failed")
        if not isinstance(courses, list):
            raise ProvisioningError("courses_response_invalid")
        matches = [
            course
            for course in courses
            if isinstance(course, dict)
            and (course.get("name") or course.get("title")) == course_name
        ]
        if not matches:
            raise ProvisioningError("course_name_not_found")
        if len(matches) != 1:
            raise ProvisioningError("course_name_ambiguous")
        course_id = str(matches[0].get("id") or "").strip()
        if not course_id:
            raise ProvisioningError("course_id_missing")
        return course_id

    def find_or_create_member(self, user: EligibleUser) -> str:
        response = self.session.get(
            f"{self.api_base_url}/members/by-email",
            params={"email": user.email},
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 200:
            return self._member_id(self._json(response, "member_lookup_failed"))
        if response.status_code != 404:
            self._json(response, "member_lookup_failed")

        response = self.session.post(
            f"{self.api_base_url}/members",
            json={
                "email": user.email,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "ignoreIfAlreadyExists": True,
                "disableLoginEmail": True,
                "locale": "de",
            },
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        return self._member_id(self._json(response, "member_create_failed"))

    def has_course_access(self, member_id: str, course_id: str) -> bool:
        response = self.session.get(
            f"{self.api_base_url}/members/{member_id}/courses",
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        courses = self._json(response, "course_access_lookup_failed")
        if not isinstance(courses, list):
            raise ProvisioningError("course_access_response_invalid")
        return any(self._course_id(course) == course_id for course in courses)

    def grant_course_access(self, member_id: str, course_id: str) -> None:
        response = self.session.put(
            f"{self.api_base_url}/members/{member_id}/courses",
            json={
                "courseIds": [course_id],
                "disableAccessNotificationEmail": False,
                "sendLoginLinkInCourseEmail": True,
            },
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        self._json(response, "course_access_grant_failed")

    @staticmethod
    def _course_id(course: object) -> str:
        if not isinstance(course, dict):
            return ""
        nested_course = course.get("course")
        nested_id = nested_course.get("id") if isinstance(nested_course, dict) else ""
        return str(course.get("id") or course.get("courseId") or nested_id or "")

    @staticmethod
    def _member_id(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ProvisioningError("member_response_invalid")
        member_id = str(payload.get("id") or "").strip()
        if not member_id:
            raise ProvisioningError("member_id_missing")
        return member_id

    @staticmethod
    def _json(response: Any, error_code: str) -> object:
        if not 200 <= int(response.status_code) < 300:
            raise ProvisioningError(error_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ProvisioningError(f"{error_code}_invalid_json") from exc
