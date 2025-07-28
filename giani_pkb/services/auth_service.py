# Create: giani_pkb/services/auth_service.py

import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
import logging

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.models.database_models import RefreshToken, UserSession
from giani_pkb.utils.auth_utils import AuthUtils

logger = logging.getLogger(__name__)

class AuthService:
    """Enhanced authentication service with session management and token rotation."""

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.auth_utils = AuthUtils()

        # Token settings
        self.ACCESS_TOKEN_LIFETIME = 30 * 60  # 30 minutes
        self.REFRESH_TOKEN_LIFETIME = 7 * 24 * 60 * 60  # 7 days
        self.SESSION_LIFETIME = 30 * 24 * 60 * 60  # 30 days

    def create_session(self, user_id: str, client_type: str = None,
                      user_agent: str = None, ip_address: str = None) -> str:
        """Create a new user session."""
        try:
            with self.db_manager.get_session() as db:
                device_fingerprint = self._generate_device_fingerprint(user_agent, ip_address)
                if device_fingerprint:
                    existing_sessions = db.query(UserSession).filter(
                        UserSession.user_id == user_id,
                        UserSession.device_fingerprint == device_fingerprint,
                        UserSession.is_active == True,
                    ).all()

                    for session in existing_sessions:
                        session.is_active = False
                        session.ended_at = datetime.now(timezone.utc)
                        session.end_reason = 'replaced_by_new_login'

                        db.query(RefreshToken).filter(
                            RefreshToken.session_id == session.session_id,
                            RefreshToken.is_active == True
                        ).update({
                            'is_active': False,
                            'revoked_at': datetime.now(timezone.utc),
                            'revoked_reason': 'session_replaced'
                        })

                session_id = self._generate_session_id()

                session = UserSession(
                    session_id=session_id,
                    user_id=user_id,
                    client_type=client_type,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.SESSION_LIFETIME),
                    device_fingerprint=device_fingerprint
                )

                db.add(session)
                db.flush()

                logger.info(
                    f"Created session {session_id} for user {user_id}, invalidated {len(existing_sessions) if device_fingerprint else 0} previous sessions"
                )
                return session_id

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    def create_tokens(self, user_id: str, email: str, session_id: str,
                     client_type: str = None, user_agent: str = None,
                     ip_address: str = None) -> Dict[str, str]:
        """Create access and refresh tokens for a session."""
        try:
            # Create JWT access token (stateless)
            access_token = self.auth_utils.create_jwt_token(
                user_id=user_id,
                email=email,
                session_id=session_id,
                expires_in=self.ACCESS_TOKEN_LIFETIME
            )

            # Create opaque refresh token (stored in DB)
            refresh_token = self._create_refresh_token(
                user_id=user_id,
                session_id=session_id,
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            return {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'expires_in': self.ACCESS_TOKEN_LIFETIME
            }

        except Exception as e:
            logger.error(f"Failed to create tokens: {e}")
            raise

    def _create_refresh_token(self, user_id: str, session_id: str,
                             client_type: str = None, user_agent: str = None,
                             ip_address: str = None) -> str:
        """Create and store a refresh token."""
        try:
            with self.db_manager.get_session() as db:
                token_id = self._generate_refresh_token()

                refresh_token = RefreshToken(
                    token_id=token_id,
                    user_id=user_id,
                    session_id=session_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.REFRESH_TOKEN_LIFETIME),
                    client_type=client_type,
                    user_agent=user_agent,
                    ip_address=ip_address
                )

                db.add(refresh_token)
                db.flush()

                return token_id

        except Exception as e:
            logger.error(f"Failed to create refresh token: {e}")
            raise

    def refresh_access_token(self, refresh_token: str,
                           ip_address: str = None) -> Optional[Dict[str, str]]:
        """Refresh access token with token rotation."""
        try:
            with self.db_manager.get_session() as db:
                # Validate refresh token
                token_record = db.query(RefreshToken).filter(
                    RefreshToken.token_id == refresh_token,
                    RefreshToken.is_active == True
                ).first()

                if not token_record or not token_record.is_valid():
                    logger.warning(f"Invalid refresh token used: {refresh_token[:10]}...")
                    return None

                # Get user and session info
                user = self.db_manager.get_user_by_id(token_record.user_id)
                if not user or not user.is_active:
                    return None

                session = db.query(UserSession).filter(
                    UserSession.session_id == token_record.session_id,
                    UserSession.is_active == True
                ).first()

                if not session or session.is_expired():
                    logger.warning(f"Expired session for refresh token: {refresh_token[:10]}...")
                    return None

                # Rotate refresh token
                old_token = token_record
                old_token.is_active = False
                old_token.revoked_at = datetime.now(timezone.utc)
                old_token.revoked_reason = 'rotation'

                # Create new tokens
                new_tokens = self.create_tokens(
                    user_id=str(user.id),
                    email=user.email,
                    session_id=session.session_id,
                    client_type=old_token.client_type,
                    user_agent=old_token.user_agent,
                    ip_address=ip_address or old_token.ip_address
                )

                # Update session activity
                session.update_activity()

                db.flush()

                logger.info(f"Rotated refresh token for user {user.id}")
                return new_tokens

        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            return None

    def revoke_refresh_token(self, refresh_token: str, reason: str = 'logout') -> bool:
        """Revoke a specific refresh token."""
        try:
            with self.db_manager.get_session() as db:
                token_record = db.query(RefreshToken).filter(
                    RefreshToken.token_id == refresh_token,
                    RefreshToken.is_active == True
                ).first()

                if token_record:
                    token_record.is_active = False
                    token_record.revoked_at = datetime.now(timezone.utc)
                    token_record.revoked_reason = reason
                    db.flush()
                    return True

                return False

        except Exception as e:
            logger.error(f"Failed to revoke refresh token: {e}")
            return False

    def revoke_session(self, session_id: str, reason: str = 'logout') -> bool:
        """Revoke a session and all its refresh tokens."""
        try:
            with self.db_manager.get_session() as db:
                # End session
                session = db.query(UserSession).filter(
                    UserSession.session_id == session_id,
                    UserSession.is_active == True
                ).first()

                if session:
                    session.is_active = False
                    session.ended_at = datetime.now(timezone.utc)
                    session.end_reason = reason

                    # Revoke all refresh tokens for this session
                    db.query(RefreshToken).filter(
                        RefreshToken.session_id == session_id,
                        RefreshToken.is_active == True
                    ).update({
                        'is_active': False,
                        'revoked_at': datetime.now(timezone.utc),
                        'revoked_reason': reason
                    })

                    db.flush()
                    return True

                return False

        except Exception as e:
            logger.error(f"Failed to revoke session: {e}")
            return False

    def revoke_all_user_sessions(self, user_id: str, reason: str = 'security') -> int:
        """Revoke all sessions for a user (useful for security incidents)."""
        try:
            with self.db_manager.get_session() as db:
                # End all user sessions
                sessions_count = db.query(UserSession).filter(
                    UserSession.user_id == user_id,
                    UserSession.is_active == True
                ).update({
                    'is_active': False,
                    'ended_at': datetime.now(timezone.utc),
                    'end_reason': reason
                })

                # Revoke all user refresh tokens
                db.query(RefreshToken).filter(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_active == True
                ).update({
                    'is_active': False,
                    'revoked_at': datetime.now(timezone.utc),
                    'revoked_reason': reason
                })

                db.flush()
                return sessions_count

        except Exception as e:
            logger.error(f"Failed to revoke all user sessions: {e}")
            return 0

    def cleanup_expired_tokens(self) -> Dict[str, int]:
        """Clean up expired tokens and sessions (run as background task)."""
        try:
            with self.db_manager.get_session() as db:
                now = datetime.now(timezone.utc)

                # Clean expired refresh tokens
                expired_tokens = db.query(RefreshToken).filter(
                    RefreshToken.expires_at < now,
                    RefreshToken.is_active == True
                ).update({
                    'is_active': False,
                    'revoked_at': now,
                    'revoked_reason': 'expired'
                })

                # Clean expired sessions
                expired_sessions = db.query(UserSession).filter(
                    UserSession.expires_at < now,
                    UserSession.is_active == True
                ).update({
                    'is_active': False,
                    'ended_at': now,
                    'end_reason': 'expired'
                })

                db.flush()

                return {
                    'expired_tokens': expired_tokens,
                    'expired_sessions': expired_sessions
                }

        except Exception as e:
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return {'expired_tokens': 0, 'expired_sessions': 0}

    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for a user."""
        try:
            with self.db_manager.get_session() as db:
                sessions = db.query(UserSession).filter(
                    UserSession.user_id == user_id,
                    UserSession.is_active == True
                ).order_by(UserSession.last_activity_at.desc()).all()

                return [
                    {
                        'session_id': s.session_id,
                        'created_at': s.created_at.isoformat(),
                        'last_activity_at': s.last_activity_at.isoformat(),
                        'client_type': s.client_type,
                        'ip_address': s.ip_address,
                        'user_agent': s.user_agent[:100] if s.user_agent else None  # Truncate for display
                    }
                    for s in sessions
                ]

        except Exception as e:
            logger.error(f"Failed to get user sessions: {e}")
            return []

    def _generate_session_id(self) -> str:
        """Generate a secure session ID."""
        return secrets.token_urlsafe(32)

    def _generate_refresh_token(self) -> str:
        """Generate a secure refresh token."""
        return secrets.token_urlsafe(32)

    def _generate_device_fingerprint(self, user_agent: str = None, ip_address: str = None) -> str:
        """Generate a device fingerprint."""
        if not user_agent and not ip_address:
            return None

        # Extract browser info from user agent
        browser_info = ""
        if user_agent:
            if "Chrome" in user_agent:
                browser_info = "chrome"
            elif "Firefox" in user_agent:
                browser_info = "firefox"
            elif "Safari" in user_agent:
                browser_info = "safari"
            elif "Office" in user_agent:
                browser_info = "office_addin"

        # Combine multiple factors
        fingerprint_components = [
            user_agent or "",
            ip_address or "",
            browser_info
        ]

        fingerprint_data = "|".join(fingerprint_components)
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:32]
