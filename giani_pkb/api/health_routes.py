"""
Health check and system status routes.
"""
from flask import Blueprint
import logging
import os
import psutil
from datetime import datetime

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.response_utils import api_success, api_error
from giani_pkb.utils.config import config

logger = logging.getLogger(__name__)

def create_health_routes() -> Blueprint:
    """Create health check routes blueprint."""
    health = Blueprint('health', __name__, url_prefix='/api/v1/health')

    # Initialize services
    db_manager = DatabaseManager()

    @health.route('/status', methods=['GET'])
    def health_check():
        """Basic health check endpoint."""
        try:
            return api_success({
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'service': 'Giani AI Project Knowledge Base',
                'version': '1.0.0'
            }, "Service is healthy")
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return api_error("Service is unhealthy", 503)

    @health.route('/detailed', methods=['GET'])
    def detailed_health_check():
        """Detailed health check with system information."""
        try:
            # Check database connectivity
            db_status = "healthy"
            db_error = None
            try:
                stats = db_manager.get_database_statistics()
                db_integrity = db_manager.verify_database_integrity()
            except Exception as e:
                db_status = "unhealthy"
                db_error = str(e)
                stats = {}
                db_integrity = False

            # Get system information
            system_info = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': psutil.disk_usage('/').percent,
                'uptime_seconds': (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds()
            }

            # Get environment information
            env_info = {
                'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
                'environment': os.getenv('FLASK_ENV', 'development'),
                'database_url': getattr(config, 'DATABASE_URL', 'sqlite:///./giani_ai.db'),
                'cors_origins': getattr(config, 'CORS_ORIGINS', [])
            }

            # Determine overall health
            overall_status = "healthy"
            if db_status == "unhealthy":
                overall_status = "degraded"

            if system_info['cpu_percent'] > 90 or system_info['memory_percent'] > 90:
                overall_status = "degraded"

            result = {
                'status': overall_status,
                'timestamp': datetime.utcnow().isoformat(),
                'service': 'Giani AI Project Knowledge Base',
                'version': '1.0.0',
                'components': {
                    'database': {
                        'status': db_status,
                        'error': db_error,
                        'statistics': stats,
                        'integrity_check': db_integrity
                    },
                    'system': {
                        'status': 'healthy' if system_info['cpu_percent'] < 90 and system_info['memory_percent'] < 90 else 'degraded',
                        'metrics': system_info
                    }
                },
                'environment': env_info
            }

            status_code = 200 if overall_status == "healthy" else 503
            return api_success(result, f"Service status: {overall_status}", status_code)

        except Exception as e:
            logger.error(f"Detailed health check failed: {e}")
            return api_error("Service health check failed", 503)

    @health.route('/database', methods=['GET'])
    def database_health():
        """Database-specific health check."""
        try:
            # Get database statistics
            stats = db_manager.get_database_statistics()

            # Check database integrity
            integrity_check = db_manager.verify_database_integrity()

            result = {
                'status': 'healthy' if integrity_check else 'degraded',
                'timestamp': datetime.utcnow().isoformat(),
                'statistics': stats,
                'integrity_check': integrity_check,
                'database_url': getattr(config, 'DATABASE_URL', 'sqlite:///./giani_ai.db')
            }

            status_code = 200 if integrity_check else 503
            return api_success(result, "Database health check completed", status_code)

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return api_error("Database health check failed", 503)

    @health.route('/system', methods=['GET'])
    def system_health():
        """System resources health check."""
        try:
            # Get detailed system metrics
            cpu_info = {
                'percent': psutil.cpu_percent(interval=1),
                'count': psutil.cpu_count(),
                'frequency': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
            }

            memory_info = psutil.virtual_memory()._asdict()

            disk_info = {
                'root': psutil.disk_usage('/')._asdict(),
                'current_working_directory': psutil.disk_usage('.')._asdict()
            }

            network_info = {
                'connections': len(psutil.net_connections()),
                'interfaces': list(psutil.net_if_addrs().keys())
            }

            # Determine system health
            system_healthy = (
                cpu_info['percent'] < 90 and
                memory_info['percent'] < 90 and
                disk_info['root']['percent'] < 90
            )

            result = {
                'status': 'healthy' if system_healthy else 'degraded',
                'timestamp': datetime.utcnow().isoformat(),
                'metrics': {
                    'cpu': cpu_info,
                    'memory': memory_info,
                    'disk': disk_info,
                    'network': network_info
                },
                'thresholds': {
                    'cpu_warning': 80,
                    'cpu_critical': 90,
                    'memory_warning': 80,
                    'memory_critical': 90,
                    'disk_warning': 80,
                    'disk_critical': 90
                }
            }

            status_code = 200 if system_healthy else 503
            return api_success(result, "System health check completed", status_code)

        except Exception as e:
            logger.error(f"System health check failed: {e}")
            return api_error("System health check failed", 503)

    @health.route('/services', methods=['GET'])
    def services_health():
        """Check health of external services and dependencies."""
        try:
            services_status = {}

            # Check database service
            try:
                db_manager.get_database_statistics()
                services_status['database'] = {
                    'status': 'healthy',
                    'response_time_ms': 0  # Could be measured
                }
            except Exception as e:
                services_status['database'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }

            # Check configuration service
            try:
                getattr(config, 'DATABASE_URL')
                services_status['configuration'] = {
                    'status': 'healthy'
                }
            except Exception as e:
                services_status['configuration'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }

            # Check file system
            try:
                test_file = '/tmp/health_check_test'
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                services_status['filesystem'] = {
                    'status': 'healthy'
                }
            except Exception as e:
                services_status['filesystem'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }

            # Determine overall services health
            all_healthy = all(
                service['status'] == 'healthy'
                for service in services_status.values()
            )

            result = {
                'status': 'healthy' if all_healthy else 'degraded',
                'timestamp': datetime.utcnow().isoformat(),
                'services': services_status
            }

            status_code = 200 if all_healthy else 503
            return api_success(result, "Services health check completed", status_code)

        except Exception as e:
            logger.error(f"Services health check failed: {e}")
            return api_error("Services health check failed", 503)

    @health.route('/ready', methods=['GET'])
    def readiness_check():
        """Readiness check for Kubernetes/container orchestration."""
        try:
            # Check if the application is ready to serve requests
            ready_checks = {
                'database': False,
                'configuration': False,
                'filesystem': False
            }

            # Database check
            try:
                db_manager.get_database_statistics()
                ready_checks['database'] = True
            except Exception:
                pass

            # Configuration check
            try:
                getattr(config, 'DATABASE_URL')
                ready_checks['configuration'] = True
            except Exception:
                pass

            # Filesystem check
            try:
                test_file = '/tmp/readiness_test'
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                ready_checks['filesystem'] = True
            except Exception:
                pass

            # All checks must pass for readiness
            is_ready = all(ready_checks.values())

            result = {
                'ready': is_ready,
                'timestamp': datetime.utcnow().isoformat(),
                'checks': ready_checks
            }

            status_code = 200 if is_ready else 503
            return api_success(result, "Readiness check completed", status_code)

        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            return api_error("Readiness check failed", 503)

    return health