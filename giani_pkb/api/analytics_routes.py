# Create: giani_pkb/api/analytics_routes.py

"""
API routes for analytics and user activity data.
"""

from flask import Blueprint, request, g
from giani_pkb.services.analytics_service import AnalyticsService
from giani_pkb.utils.response_utils import (
    api_success,
    api_validation_error,
    api_authentication_error,
    api_internal_server_error,
)
from giani_pkb.utils.auth_utils import AuthUtils
from giani_pkb.middleware.analytics_middleware import log_manual_activity
import logging

logger = logging.getLogger(__name__)


def create_analytics_routes():
    """Create and configure the analytics blueprint."""
    analytics = Blueprint("analytics", __name__, url_prefix="/api/v1/analytics")

    # Initialize services
    analytics_service = AnalyticsService()
    auth_utils = AuthUtils()

    def require_auth():
        """Helper function to check authentication."""
        user_id = getattr(g, "user_id", None)
        if not user_id:
            return api_authentication_error("Authentication required")
        return None

    @analytics.route("/user/summary", methods=["GET"])
    def get_user_activity_summary():
        """Get activity summary for the current user."""
        try:
            # Check authentication
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id
            days = request.args.get("days", 30, type=int)

            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            summary = analytics_service.get_user_activity_summary(user_id, days)

            # Log this analytics access
            log_manual_activity(
                activity_type="analytics_access",
                feature_used="user_activity_summary",
                additional_data={"days_requested": days},
            )

            return api_success(summary, f"User activity summary for {days} days")

        except Exception as e:
            logger.error(f"Error getting user activity summary: {e}")
            return api_internal_server_error(
                "Failed to get user activity summary", str(e)
            )

    @analytics.route("/user/activities", methods=["GET"])
    def get_user_activities():
        """Get detailed user activities with pagination."""
        try:
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id
            page = request.args.get("page", 1, type=int)
            per_page = min(request.args.get("per_page", 50, type=int), 100)  # Max 100
            activity_type = request.args.get("activity_type")
            feature_used = request.args.get("feature_used")
            days = request.args.get("days", 30, type=int)

            # Basic validation
            if page < 1:
                return api_validation_error("Page must be >= 1")
            if per_page < 1:
                return api_validation_error("Per page must be >= 1")
            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            # Get activities with filters
            activities = analytics_service.get_user_activities_paginated(
                user_id=user_id,
                page=page,
                per_page=per_page,
                activity_type=activity_type,
                feature_used=feature_used,
                days=days,
            )

            log_manual_activity(
                activity_type="analytics_access",
                feature_used="user_activities_list",
                additional_data={
                    "page": page,
                    "per_page": per_page,
                    "filters": {
                        "activity_type": activity_type,
                        "feature_used": feature_used,
                        "days": days,
                    },
                },
            )

            return api_success(activities, "User activities retrieved successfully")

        except Exception as e:
            logger.error(f"Error getting user activities: {e}")
            return api_internal_server_error("Failed to get user activities", str(e))

    @analytics.route("/system/summary", methods=["GET"])
    def get_system_analytics():
        """Get system-wide analytics (admin only)."""
        try:
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id

            # Check if user is admin/superuser
            user = auth_utils.get_user_by_id(user_id)
            if not user or not user.get("is_superuser", False):
                return api_authentication_error("Admin access required")

            days = request.args.get("days", 7, type=int)

            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            system_analytics = analytics_service.get_system_analytics(days)

            log_manual_activity(
                activity_type="admin_analytics_access",
                feature_used="system_analytics_summary",
                additional_data={"days_requested": days},
            )

            return api_success(system_analytics, f"System analytics for {days} days")

        except Exception as e:
            logger.error(f"Error getting system analytics: {e}")
            return api_internal_server_error("Failed to get system analytics", str(e))

    @analytics.route("/features/usage", methods=["GET"])
    def get_feature_usage():
        """Get feature usage statistics for current user."""
        try:
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id
            days = request.args.get("days", 30, type=int)

            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            feature_usage = analytics_service.get_user_feature_usage(user_id, days)

            log_manual_activity(
                activity_type="analytics_access",
                feature_used="feature_usage_stats",
                additional_data={"days_requested": days},
            )

            return api_success(feature_usage, f"Feature usage for {days} days")

        except Exception as e:
            logger.error(f"Error getting feature usage: {e}")
            return api_internal_server_error("Failed to get feature usage", str(e))

    @analytics.route("/performance/summary", methods=["GET"])
    def get_performance_summary():
        """Get API performance summary for current user."""
        try:
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id
            days = request.args.get("days", 7, type=int)

            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            performance_summary = analytics_service.get_user_performance_summary(
                user_id, days
            )

            log_manual_activity(
                activity_type="analytics_access",
                feature_used="performance_summary",
                additional_data={"days_requested": days},
            )

            return api_success(
                performance_summary, f"Performance summary for {days} days"
            )

        except Exception as e:
            logger.error(f"Error getting performance summary: {e}")
            return api_internal_server_error(
                "Failed to get performance summary", str(e)
            )

    @analytics.route("/export", methods=["POST"])
    def export_user_data():
        """Export user analytics data."""
        try:
            auth_error = require_auth()
            if auth_error:
                return auth_error

            user_id = g.user_id
            data = request.get_json() or {}

            export_format = data.get("format", "json")  # json, csv
            days = data.get("days", 30)
            include_details = data.get("include_details", False)

            if export_format not in ["json", "csv"]:
                return api_validation_error("Format must be 'json' or 'csv'")

            if days < 1 or days > 365:
                return api_validation_error("Days must be between 1 and 365")

            exported_data = analytics_service.export_user_analytics(
                user_id=user_id,
                days=days,
                format=export_format,
                include_details=include_details,
            )

            log_manual_activity(
                activity_type="data_export",
                feature_used="analytics_export",
                additional_data={
                    "format": export_format,
                    "days": days,
                    "include_details": include_details,
                },
            )

            return api_success(exported_data, "Analytics data exported successfully")

        except Exception as e:
            logger.error(f"Error exporting user data: {e}")
            return api_internal_server_error("Failed to export analytics data", str(e))

    @analytics.route("/health", methods=["GET"])
    def analytics_health():
        """Health check for analytics service."""
        try:
            # Basic health check
            health_status = {
                "service": "analytics",
                "status": "healthy",
                "database_connection": "ok",
            }

            # Test database connection
            try:
                analytics_service.get_system_analytics(1)
                health_status["analytics_service"] = "ok"
            except Exception as e:
                health_status["analytics_service"] = f"error: {str(e)}"
                health_status["status"] = "degraded"

            return api_success(health_status, "Analytics service health check")

        except Exception as e:
            logger.error(f"Analytics health check failed: {e}")
            return api_internal_server_error("Analytics health check failed", str(e))

    return analytics
