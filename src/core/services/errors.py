"""Domain failures mapped to HTTP only by Application controllers."""


class ResourceNotFound(Exception):
    pass


class ResourceConflict(Exception):
    pass


class PermissionDenied(Exception):
    pass
