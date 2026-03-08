"""
Custom exceptions for the Teaching Assistant API
"""
from fastapi import HTTPException, status


class BaseAPIException(HTTPException):
    """Base exception for all API errors"""
    
    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str = None,
        headers: dict = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code


class NotFoundException(BaseAPIException):
    """Resource not found"""
    
    def __init__(self, detail: str = None, resource: str = None, identifier: str = None, error_code: str = "NOT_FOUND"):
        if detail is None:
            detail = f"{resource} không tìm thấy" if resource else "Không tìm thấy tài nguyên"
            if identifier:
                detail = f"{resource} '{identifier}' không tìm thấy"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
            error_code=error_code
        )


class UnauthorizedException(BaseAPIException):
    """Unauthorized access"""
    
    def __init__(self, detail: str = "Bạn không có quyền truy cập", error_code: str = "UNAUTHORIZED"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code=error_code
        )


class ForbiddenException(BaseAPIException):
    """Forbidden access - role based"""
    
    def __init__(self, required_role: str, current_role: str = None):
        detail = f"Chỉ {required_role} mới có quyền thực hiện thao tác này"
        if current_role:
            detail += f". Vai trò hiện tại: {current_role}"
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN"
        )


class BadRequestException(BaseAPIException):
    """Bad request - invalid input"""
    
    def __init__(self, detail: str, error_code: str = "BAD_REQUEST"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code=error_code
        )


class ServiceUnavailableException(BaseAPIException):
    """External service unavailable"""
    
    def __init__(self, service: str):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service '{service}' không khả dụng",
            error_code="SERVICE_UNAVAILABLE"
        )


class FileProcessingException(BaseAPIException):
    """Error processing file"""
    
    def __init__(self, filename: str, reason: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Không thể xử lý file '{filename}': {reason}",
            error_code="FILE_PROCESSING_ERROR"
        )


class DatabaseException(BaseAPIException):
    """Database error"""
    
    def __init__(self, operation: str, reason: str = None):
        detail = f"Lỗi database khi {operation}"
        if reason:
            detail += f": {reason}"
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="DATABASE_ERROR"
        )


class AIModelException(BaseAPIException):
    """AI Model error"""
    
    def __init__(self, model: str, reason: str = None):
        detail = f"Lỗi AI model '{model}'"
        if reason:
            detail += f": {reason}"
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="AI_MODEL_ERROR"
        )
