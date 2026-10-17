"""Custom middleware for Shizuha Wiki"""


class OrganizationMiddleware:
    """
    Extract organization context from X-Organization-ID header.
    Sets request.organization_id for use in views.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        org_id = request.META.get('HTTP_X_ORGANIZATION_ID')
        if org_id:
            try:
                request.organization_id = int(org_id)
            except (ValueError, TypeError):
                request.organization_id = None
        else:
            request.organization_id = None
        return self.get_response(request)


class ScriptNameMiddleware:
    """
    Middleware to handle SCRIPT_NAME for reverse proxy setups.
    When running behind nginx with a path prefix like /shizuha-wiki/,
    this ensures URLs are generated correctly.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        script_name = request.META.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            request.META['SCRIPT_NAME'] = script_name
        return self.get_response(request)
