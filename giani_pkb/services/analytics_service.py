# Updated: giani_pkb/services/analytics_service.py

import uuid
import time
import json
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.models.database_models import UserActivityLog, User
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for tracking and analyzing user activities."""

    def __init__(self):
        self.db_manager = DatabaseManager()

    def log_activity(
        self,
        user_id: str,
        activity_type: str,
        endpoint: Optional[str] = None,
        http_method: Optional[str] = None,
        status_code: Optional[int] = None,
        response_time_ms: Optional[float] = None,
        user_agent: Optional[str] = None,
        client_type: Optional[str] = None,
        ip_address: Optional[str] = None,
        project_id: Optional[int] = None,
        feature_used: Optional[str] = None,
        session_id: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log user activity to database.

        Args:
            user_id: User UUID
            activity_type: Type of activity ('login', 'logout', 'api_call')
            endpoint: API endpoint if applicable
            http_method: HTTP method (GET, POST, etc.)
            status_code: HTTP response status code
            response_time_ms: Response time in milliseconds
            user_agent: User agent string
            client_type: 'web' or 'addin'
            ip_address: User IP address
            project_id: Project ID if relevant
            feature_used: Feature name (e.g., 'ppt_title_generation')
            session_id: Session identifier
            additional_data: Any additional context data

        Returns:
            bool: True if logged successfully
        """
        try:
            print('======= inside log_activity ======')
            with self.db_manager.get_session() as db:
                activity_log = UserActivityLog(
                    user_id=user_id,
                    session_id=session_id,
                    activity_type=activity_type,
                    endpoint=endpoint,
                    http_method=http_method,
                    user_agent=user_agent,
                    client_type=client_type,
                    ip_address=ip_address,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    project_id=project_id,
                    feature_used=feature_used,
                    additional_data=additional_data,
                )

                db.add(activity_log)
                db.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to log user activity: {e}")
            return False

    def get_user_activity_summary(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Get activity summary for a user."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Basic activity counts
                total_activities = (
                    db.query(UserActivityLog)
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.timestamp >= start_date,
                    )
                    .count()
                )

                # Login sessions
                login_count = (
                    db.query(UserActivityLog)
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.activity_type == "login",
                        UserActivityLog.timestamp >= start_date,
                    )
                    .count()
                )

                # Most used features
                feature_usage = (
                    db.query(
                        UserActivityLog.feature_used,
                        func.count(UserActivityLog.id).label("count"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.feature_used.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(UserActivityLog.feature_used)
                    .order_by(desc("count"))
                    .limit(10)
                    .all()
                )

                # Client type usage
                client_usage = (
                    db.query(
                        UserActivityLog.client_type,
                        func.count(UserActivityLog.id).label("count"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.client_type.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(UserActivityLog.client_type)
                    .all()
                )

                # Average response time
                avg_response_time = (
                    db.query(func.avg(UserActivityLog.response_time_ms))
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.response_time_ms.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .scalar()
                )

                return {
                    "user_id": user_id,
                    "period_days": days,
                    "total_activities": total_activities,
                    "login_sessions": login_count,
                    "avg_response_time_ms": (
                        round(avg_response_time, 2) if avg_response_time else None
                    ),
                    "top_features": [
                        {"feature": f[0], "usage_count": f[1]} for f in feature_usage
                    ],
                    "client_usage": [
                        {"client_type": c[0], "count": c[1]} for c in client_usage
                    ],
                }

        except Exception as e:
            logger.error(f"Failed to get user activity summary: {e}")
            return {}

    def get_user_activities_paginated(
        self,
        user_id: str,
        page: int = 1,
        per_page: int = 50,
        activity_type: Optional[str] = None,
        feature_used: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get paginated user activities with optional filters."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Build base query
                query = db.query(UserActivityLog).filter(
                    UserActivityLog.user_id == user_id,
                    UserActivityLog.timestamp >= start_date,
                )

                # Apply filters
                if activity_type:
                    query = query.filter(UserActivityLog.activity_type == activity_type)
                if feature_used:
                    query = query.filter(UserActivityLog.feature_used == feature_used)

                # Get total count
                total_count = query.count()

                # Apply pagination and ordering
                activities = (
                    query.order_by(desc(UserActivityLog.timestamp))
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )

                # Calculate pagination info
                total_pages = (total_count + per_page - 1) // per_page
                has_next = page < total_pages
                has_prev = page > 1

                return {
                    "activities": [activity.to_dict() for activity in activities],
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total_items": total_count,
                        "total_pages": total_pages,
                        "has_next": has_next,
                        "has_prev": has_prev,
                    },
                    "filters": {
                        "activity_type": activity_type,
                        "feature_used": feature_used,
                        "days": days,
                    },
                }

        except Exception as e:
            logger.error(f"Failed to get paginated user activities: {e}")
            return {"activities": [], "pagination": {}, "filters": {}}

    def get_user_feature_usage(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Get detailed feature usage statistics for a user."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Feature usage with timestamps
                feature_usage = (
                    db.query(
                        UserActivityLog.feature_used,
                        func.count(UserActivityLog.id).label("usage_count"),
                        func.min(UserActivityLog.timestamp).label("first_used"),
                        func.max(UserActivityLog.timestamp).label("last_used"),
                        func.avg(UserActivityLog.response_time_ms).label(
                            "avg_response_time"
                        ),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.feature_used.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(UserActivityLog.feature_used)
                    .order_by(desc("usage_count"))
                    .all()
                )

                # Daily feature usage trend
                daily_usage = (
                    db.query(
                        func.date(UserActivityLog.timestamp).label("date"),
                        UserActivityLog.feature_used,
                        func.count(UserActivityLog.id).label("count"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.feature_used.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(
                        func.date(UserActivityLog.timestamp),
                        UserActivityLog.feature_used,
                    )
                    .order_by("date")
                    .all()
                )

                # Format daily usage for easier consumption
                daily_trend = {}
                for date, feature, count in daily_usage:
                    date_str = date.isoformat()
                    if date_str not in daily_trend:
                        daily_trend[date_str] = {}
                    daily_trend[date_str][feature] = count

                return {
                    "user_id": user_id,
                    "period_days": days,
                    "feature_summary": [
                        {
                            "feature": f[0],
                            "usage_count": f[1],
                            "first_used": f[2].isoformat() if f[2] else None,
                            "last_used": f[3].isoformat() if f[3] else None,
                            "avg_response_time_ms": round(f[4], 2) if f[4] else None,
                        }
                        for f in feature_usage
                    ],
                    "daily_trend": daily_trend,
                }

        except Exception as e:
            logger.error(f"Failed to get user feature usage: {e}")
            return {}

    def get_user_performance_summary(
        self, user_id: str, days: int = 7
    ) -> Dict[str, Any]:
        """Get API performance summary for a user."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Overall performance stats
                perf_stats = (
                    db.query(
                        func.count(UserActivityLog.id).label("total_requests"),
                        func.avg(UserActivityLog.response_time_ms).label(
                            "avg_response_time"
                        ),
                        func.min(UserActivityLog.response_time_ms).label(
                            "min_response_time"
                        ),
                        func.max(UserActivityLog.response_time_ms).label(
                            "max_response_time"
                        ),
                        func.percentile_cont(0.5)
                        .within_group(UserActivityLog.response_time_ms)
                        .label("median_response_time"),
                        func.percentile_cont(0.95)
                        .within_group(UserActivityLog.response_time_ms)
                        .label("p95_response_time"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.response_time_ms.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .first()
                )

                # Error rate
                error_stats = (
                    db.query(
                        func.count(UserActivityLog.id).label("total_requests"),
                        func.sum(
                            func.case((UserActivityLog.status_code >= 400, 1), else_=0)
                        ).label("error_count"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.status_code.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .first()
                )

                # Performance by endpoint
                endpoint_performance = (
                    db.query(
                        UserActivityLog.endpoint,
                        func.count(UserActivityLog.id).label("request_count"),
                        func.avg(UserActivityLog.response_time_ms).label(
                            "avg_response_time"
                        ),
                        func.sum(
                            func.case((UserActivityLog.status_code >= 400, 1), else_=0)
                        ).label("error_count"),
                    )
                    .filter(
                        UserActivityLog.user_id == user_id,
                        UserActivityLog.endpoint.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(UserActivityLog.endpoint)
                    .order_by(desc("request_count"))
                    .limit(10)
                    .all()
                )

                # Calculate error rate
                error_rate = 0
                if error_stats and error_stats.total_requests > 0:
                    error_rate = (
                        error_stats.error_count / error_stats.total_requests
                    ) * 100

                return {
                    "user_id": user_id,
                    "period_days": days,
                    "overall_performance": {
                        "total_requests": (
                            perf_stats.total_requests if perf_stats else 0
                        ),
                        "avg_response_time_ms": (
                            round(perf_stats.avg_response_time, 2)
                            if perf_stats and perf_stats.avg_response_time
                            else None
                        ),
                        "min_response_time_ms": (
                            round(perf_stats.min_response_time, 2)
                            if perf_stats and perf_stats.min_response_time
                            else None
                        ),
                        "max_response_time_ms": (
                            round(perf_stats.max_response_time, 2)
                            if perf_stats and perf_stats.max_response_time
                            else None
                        ),
                        "median_response_time_ms": (
                            round(perf_stats.median_response_time, 2)
                            if perf_stats and perf_stats.median_response_time
                            else None
                        ),
                        "p95_response_time_ms": (
                            round(perf_stats.p95_response_time, 2)
                            if perf_stats and perf_stats.p95_response_time
                            else None
                        ),
                        "error_rate_percent": round(error_rate, 2),
                    },
                    "endpoint_performance": [
                        {
                            "endpoint": ep[0],
                            "request_count": ep[1],
                            "avg_response_time_ms": round(ep[2], 2) if ep[2] else None,
                            "error_count": ep[3],
                            "error_rate_percent": (
                                round((ep[3] / ep[1]) * 100, 2) if ep[1] > 0 else 0
                            ),
                        }
                        for ep in endpoint_performance
                    ],
                }

        except Exception as e:
            logger.error(f"Failed to get user performance summary: {e}")
            return {}

    def export_user_analytics(
        self,
        user_id: str,
        days: int = 30,
        format: str = "json",
        include_details: bool = False,
    ) -> Dict[str, Any]:
        """Export user analytics data in specified format."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Get summary data
                summary = self.get_user_activity_summary(user_id, days)
                feature_usage = self.get_user_feature_usage(user_id, days)
                performance = self.get_user_performance_summary(user_id, days)

                export_data = {
                    "export_info": {
                        "user_id": user_id,
                        "export_date": datetime.utcnow().isoformat(),
                        "period_days": days,
                        "format": format,
                        "include_details": include_details,
                    },
                    "summary": summary,
                    "feature_usage": feature_usage,
                    "performance": performance,
                }

                # Include detailed activities if requested
                if include_details:
                    activities = self.get_user_activities_paginated(
                        user_id=user_id,
                        page=1,
                        per_page=10000,  # Large number to get all records
                        days=days,
                    )
                    export_data["detailed_activities"] = activities["activities"]

                # Format based on requested format
                if format == "json":
                    return {
                        "format": "json",
                        "data": export_data,
                        "download_ready": True,
                    }

                elif format == "csv":
                    # Convert to CSV format
                    csv_data = self._convert_to_csv(export_data, include_details)
                    return {
                        "format": "csv",
                        "data": csv_data,
                        "download_ready": True,
                    }

                else:
                    raise ValueError(f"Unsupported format: {format}")

        except Exception as e:
            logger.error(f"Failed to export user analytics: {e}")
            return {"error": str(e), "download_ready": False}

    def _convert_to_csv(self, data: Dict[str, Any], include_details: bool) -> str:
        """Convert analytics data to CSV format."""
        output = io.StringIO()

        # Summary CSV
        writer = csv.writer(output)
        writer.writerow(["User Analytics Export"])
        writer.writerow([f"Export Date: {data['export_info']['export_date']}"])
        writer.writerow([f"Period: {data['export_info']['period_days']} days"])
        writer.writerow([])

        # Summary statistics
        writer.writerow(["Summary Statistics"])
        summary = data.get("summary", {})
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Activities", summary.get("total_activities", 0)])
        writer.writerow(["Login Sessions", summary.get("login_sessions", 0)])
        writer.writerow(
            ["Avg Response Time (ms)", summary.get("avg_response_time_ms", "N/A")]
        )
        writer.writerow([])

        # Feature usage
        writer.writerow(["Feature Usage"])
        writer.writerow(["Feature", "Usage Count"])
        for feature in summary.get("top_features", []):
            writer.writerow([feature["feature"], feature["usage_count"]])
        writer.writerow([])

        # Client usage
        writer.writerow(["Client Usage"])
        writer.writerow(["Client Type", "Count"])
        for client in summary.get("client_usage", []):
            writer.writerow([client["client_type"], client["count"]])
        writer.writerow([])

        # Detailed activities if requested
        if include_details and "detailed_activities" in data:
            writer.writerow(["Detailed Activities"])
            writer.writerow(
                [
                    "Timestamp",
                    "Activity Type",
                    "Endpoint",
                    "Feature Used",
                    "Status Code",
                    "Response Time (ms)",
                    "Client Type",
                ]
            )
            for activity in data["detailed_activities"]:
                writer.writerow(
                    [
                        activity.get("timestamp", ""),
                        activity.get("activity_type", ""),
                        activity.get("endpoint", ""),
                        activity.get("feature_used", ""),
                        activity.get("status_code", ""),
                        activity.get("response_time_ms", ""),
                        activity.get("client_type", ""),
                    ]
                )

        return output.getvalue()

    def get_system_analytics(self, days: int = 7) -> Dict[str, Any]:
        """Get system-wide analytics."""
        try:
            with self.db_manager.get_session() as db:
                start_date = datetime.utcnow() - timedelta(days=days)

                # Active users
                active_users = (
                    db.query(UserActivityLog.user_id)
                    .filter(UserActivityLog.timestamp >= start_date)
                    .distinct()
                    .count()
                )

                # Total API calls
                total_api_calls = (
                    db.query(UserActivityLog)
                    .filter(
                        UserActivityLog.activity_type == "api_call",
                        UserActivityLog.timestamp >= start_date,
                    )
                    .count()
                )

                # Most popular endpoints
                popular_endpoints = (
                    db.query(
                        UserActivityLog.endpoint,
                        func.count(UserActivityLog.id).label("count"),
                    )
                    .filter(
                        UserActivityLog.endpoint.isnot(None),
                        UserActivityLog.timestamp >= start_date,
                    )
                    .group_by(UserActivityLog.endpoint)
                    .order_by(desc("count"))
                    .limit(10)
                    .all()
                )

                # Daily activity trend
                daily_activity = (
                    db.query(
                        func.date(UserActivityLog.timestamp).label("date"),
                        func.count(UserActivityLog.id).label("count"),
                    )
                    .filter(UserActivityLog.timestamp >= start_date)
                    .group_by(func.date(UserActivityLog.timestamp))
                    .order_by("date")
                    .all()
                )

                # System performance
                system_performance = (
                    db.query(
                        func.avg(UserActivityLog.response_time_ms).label(
                            "avg_response_time"
                        ),
                        func.percentile_cont(0.95)
                        .within_group(UserActivityLog.response_time_ms)
                        .label("p95_response_time"),
                        func.sum(
                            func.case((UserActivityLog.status_code >= 400, 1), else_=0)
                        ).label("error_count"),
                        func.count(UserActivityLog.id).label("total_requests"),
                    )
                    .filter(
                        UserActivityLog.timestamp >= start_date,
                        UserActivityLog.response_time_ms.isnot(None),
                    )
                    .first()
                )

                # Calculate system error rate
                error_rate = 0
                if system_performance and system_performance.total_requests > 0:
                    error_rate = (
                        system_performance.error_count
                        / system_performance.total_requests
                    ) * 100

                return {
                    "period_days": days,
                    "active_users": active_users,
                    "total_api_calls": total_api_calls,
                    "system_performance": {
                        "avg_response_time_ms": (
                            round(system_performance.avg_response_time, 2)
                            if system_performance
                            and system_performance.avg_response_time
                            else None
                        ),
                        "p95_response_time_ms": (
                            round(system_performance.p95_response_time, 2)
                            if system_performance
                            and system_performance.p95_response_time
                            else None
                        ),
                        "error_rate_percent": round(error_rate, 2),
                        "total_requests": (
                            system_performance.total_requests
                            if system_performance
                            else 0
                        ),
                    },
                    "popular_endpoints": [
                        {"endpoint": e[0], "count": e[1]} for e in popular_endpoints
                    ],
                    "daily_activity": [
                        {"date": d[0].isoformat(), "count": d[1]}
                        for d in daily_activity
                    ],
                }

        except Exception as e:
            logger.error(f"Failed to get system analytics: {e}")
            return {}


# Utility functions for easy access
def log_user_login(
    user_id: str,
    client_type: str = None,
    user_agent: str = None,
    ip_address: str = None,
):
    """Quick function to log user login."""
    service = AnalyticsService()
    return service.log_activity(
        user_id=user_id,
        activity_type="login",
        client_type=client_type,
        user_agent=user_agent,
        ip_address=ip_address,
        session_id=str(uuid.uuid4()),
    )


def log_user_logout(user_id: str, session_id: str = None):
    """Quick function to log user logout."""
    service = AnalyticsService()
    return service.log_activity(
        user_id=user_id, activity_type="logout", session_id=session_id
    )


def log_api_call(
    user_id: str,
    endpoint: str,
    method: str,
    status_code: int,
    response_time_ms: float = None,
    feature_used: str = None,
    client_type: str = None,
    project_id: int = None,
):
    """Quick function to log API calls."""
    service = AnalyticsService()
    return service.log_activity(
        user_id=user_id,
        activity_type="api_call",
        endpoint=endpoint,
        http_method=method,
        status_code=status_code,
        response_time_ms=response_time_ms,
        feature_used=feature_used,
        client_type=client_type,
        project_id=project_id,
    )
