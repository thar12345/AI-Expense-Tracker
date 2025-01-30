"""
Performance monitoring middleware for Application Insights.
Tracks request processing times and custom metrics.
"""
import time
import logging
import re
from typing import Callable
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class ApplicationInsightsPerformanceMiddleware(MiddlewareMixin):
    """
    Middleware to track request performance metrics in Application Insights.
    
    Tracks:
    - Request processing time
    - Response status codes  
    - Request methods
    - Endpoint paths
    """

    def __init__(self, get_response: Callable):
        super().__init__(get_response)
        self.get_response = get_response

    def process_request(self, request: HttpRequest) -> None:
        """Mark the start time of request processing."""
        request._performance_start_time = time.time()

    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """Record performance metrics after request processing."""
        if not hasattr(request, '_performance_start_time'):
            return response
            
        # Calculate processing time in milliseconds
        start_time = request._performance_start_time
        processing_time = (time.time() - start_time) * 1000
        
        # Log performance data
        self._log_performance_data(request, response, processing_time)
            
        return response

    def _log_performance_data(
        self, 
        request: HttpRequest, 
        response: HttpResponse, 
        processing_time: float
    ) -> None:
        """Log performance data for debugging and monitoring."""
        endpoint = self._get_endpoint_name(request)
        user_id = getattr(request.user, 'id', 'anonymous')
        
        logger.info(
            f"Request Performance - "
            f"Method: {request.method}, "
            f"Endpoint: {endpoint}, "
            f"Status: {response.status_code}, "
            f"Processing Time: {processing_time:.2f}ms, "
            f"User: {user_id}"
        )

    def _get_endpoint_name(self, request: HttpRequest) -> str:
        """Extract a clean endpoint name from the request path."""
        path = request.path_info
        
        # Simplify common patterns
        if path.startswith('/api/'):
            path = path[5:]  # Remove /api/ prefix
            
        # Replace IDs with placeholders for better grouping
        # Replace numeric IDs
        path = re.sub(r'/\d+/', '/{id}/', path)
        # Replace UUIDs
        uuid_pattern = (
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
            r'[0-9a-f]{4}-[0-9a-f]{12}/'
        )
        path = re.sub(
            uuid_pattern,
            '/{uuid}/',
            path,
            flags=re.IGNORECASE
        )
        
        return path or '/'


class RequestResponseLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log detailed request and response information.
    Useful for debugging and audit trails.
    """

    def __init__(self, get_response: Callable):
        super().__init__(get_response)
        self.get_response = get_response

    def process_request(self, request: HttpRequest) -> None:
        """Log incoming request details."""
        # Store request start time for performance tracking
        request._request_start_time = time.time()
        
        # Log request details (excluding sensitive data)
        user_id = getattr(request.user, 'id', 'anonymous')
        client_ip = self._get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:100]
        
        logger.info(
            f"Incoming Request - "
            f"Method: {request.method}, "
            f"Path: {request.path}, "
            f"User: {user_id}, "
            f"IP: {client_ip}, "
            f"User-Agent: {user_agent}"
        )

    def process_response(
        self, request: HttpRequest, response: HttpResponse
    ) -> HttpResponse:
        """Log response details and total request time."""
        if hasattr(request, '_request_start_time'):
            total_time = (time.time() - request._request_start_time) * 1000
            content_type = response.get('Content-Type', 'unknown')
            content_size = len(response.content)
            
            logger.info(
                f"Response - "
                f"Status: {response.status_code}, "
                f"Total Time: {total_time:.2f}ms, "
                f"Content-Type: {content_type}, "
                f"Size: {content_size} bytes"
            )
            
        return response

    def _get_client_ip(self, request: HttpRequest) -> str:
        """Extract client IP address from request headers."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')
