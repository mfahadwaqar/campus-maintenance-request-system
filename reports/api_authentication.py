from rest_framework.authentication import SessionAuthentication
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiSessionAuthentication(SessionAuthentication):
    def authenticate_header(self, request):
        return "Session"


class ApiSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "reports.api_authentication.ApiSessionAuthentication"
    name = "sessionAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": (
                "Django session cookie. State-changing requests also require a valid "
                "CSRF token in the X-CSRFToken header."
            ),
        }
