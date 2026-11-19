"""JSON authentication endpoints for the React front end.

The front end runs on its own origin, so it signs in with the Django session
cookie plus a CSRF token:

1. ``GET /accounts/csrf/`` sets the ``csrftoken`` cookie and returns the token
   in the body as well, because the cookie may be HttpOnly in production.
2. ``POST /api/auth/login/`` takes ``{"email", "password"}`` and the
   ``X-CSRFToken`` header, and answers 204 with the ``sessionid`` cookie.
3. ``GET /api/auth/me/`` tells the front end who is signed in and in what role.
4. ``POST /api/auth/logout/`` clears the session.
"""

import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views import View
from django.views.csrf import csrf_failure as default_csrf_failure
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

User = get_user_model()

JSON_PATH_PREFIXES = ("/api/", "/accounts/csrf/")


def csrf_failure(request, reason="", template_name=None):
    """Return JSON for API calls that fail the CSRF check; HTML otherwise."""
    if request.path.startswith(JSON_PATH_PREFIXES):
        return JsonResponse(
            {"detail": f"CSRF Failed: {reason}" if reason else "CSRF Failed."},
            status=403,
        )
    if template_name:
        return default_csrf_failure(request, reason=reason, template_name=template_name)
    return default_csrf_failure(request, reason=reason)


@ensure_csrf_cookie
def csrf_cookie(request):
    """GET /accounts/csrf/: set the CSRF cookie and echo the token."""
    return JsonResponse({"detail": "CSRF cookie set", "csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(View):
    """POST /api/auth/login/: sign in with email and password."""

    http_method_names = ["post", "options"]

    def post(self, request):
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"detail": "Send a JSON body."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"detail": "Send a JSON object."}, status=400)
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        if not email or not password:
            return JsonResponse(
                {"detail": "Email and password are required."}, status=400
            )
        account = User.objects.filter(email__iexact=email).first()
        user = (
            authenticate(request, username=account.get_username(), password=password)
            if account
            else None
        )
        if user is None or not user.is_active:
            return JsonResponse({"detail": "Invalid email or password."}, status=401)
        login(request, user)
        return HttpResponse(status=204)


class CurrentUserSerializer(serializers.ModelSerializer):
    student_id = serializers.CharField(source="username", read_only=True)
    full_name = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()
    unit = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "student_id",
            "full_name",
            "phone",
            "role",
            "role_label",
            "unit",
            "is_staff",
        )
        read_only_fields = fields

    def get_full_name(self, user) -> str:
        return user.name or user.get_full_name() or user.get_username()

    def get_role_label(self, user) -> str:
        return user.get_role_display() if user.role else ""

    def get_unit(self, user):
        if not user.unit_id:
            return None
        return {"id": user.unit_id, "name": user.unit.name}


class CurrentUserAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="auth_me",
        responses={200: CurrentUserSerializer, 401: OpenApiResponse(description="Not signed in.")},
        description=(
            "Return the signed-in account and its role. The front end uses the role "
            "returned here, never a client-side guess, to choose which screens to show. "
            "A user with no workflow role (an administrator) returns role null."
        ),
    )
    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)


class LogoutAPIView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="auth_logout",
        request=None,
        responses={204: None, 401: OpenApiResponse(description="Not signed in.")},
        description="End the session. Requires the X-CSRFToken header.",
    )
    def post(self, request):
        logout(request)
        return Response(status=204)
