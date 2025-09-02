
import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Union

__all__ = [
    "LoggingCfg", 
    "CacheCfg", 
    "RerankCfg", 
    "TimeoutsCfg", 
    "RetrieverCfg", 
    "DebugCfg", 
    "OrchestrationConfig", 
    "load_orchestration_config"
]

# Internal logger for warnings
_logger = logging.getLogger(__name__)


@dataclass
class LoggingCfg:
    """Logging configuration settings."""
    level: int = 20  # INFO level


@dataclass
class CacheCfg:
    """Cache configuration settings for retrieval results."""
    enabled: bool = False
    max_size: int = 256
    ttl: int = 600  # seconds


@dataclass
class RerankCfg:
    """Reranking configuration settings for result refinement."""
    enabled: bool = False
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 12


@dataclass
class TimeoutsCfg:
    """Timeout configuration settings for retrieval operations."""
    per_attempt: float = 10.0  # seconds


@dataclass
class RetrieverCfg:
    """Composite retriever configuration containing cache, reranking, and timeouts."""
    cache: CacheCfg
    reranking: RerankCfg
    timeouts: TimeoutsCfg


@dataclass
class DebugCfg:
    """Debug configuration settings for development and troubleshooting."""
    include_user_ids: bool = False
    include_subquery_details: bool = False


@dataclass
class OrchestrationConfig:
    """
    Main configuration container for RAG pipeline orchestration.
    
    Attributes:
        logging: Logging configuration
        retriever: Retriever configuration (cache, reranking, timeouts)
        debug: Debug configuration
    """
    logging: LoggingCfg
    retriever: RetrieverCfg
    debug: DebugCfg

    def __post_init__(self) -> None:
        """Validate configuration values and apply corrections with warnings."""
        # Validate cache configuration
        if self.retriever.cache.max_size < 0:
            _logger.warning(f"Invalid cache.max_size ({self.retriever.cache.max_size}), using default 256")
            self.retriever.cache.max_size = 256
            
        if self.retriever.cache.ttl < 0:
            _logger.warning(f"Invalid cache.ttl ({self.retriever.cache.ttl}), using default 600")
            self.retriever.cache.ttl = 600

        # Validate reranking configuration
        if self.retriever.reranking.top_k < 1:
            _logger.warning(f"Invalid reranking.top_k ({self.retriever.reranking.top_k}), using default 12")
            self.retriever.reranking.top_k = 12

        # Validate timeout configuration
        if self.retriever.timeouts.per_attempt <= 0:
            _logger.warning(f"Invalid timeouts.per_attempt ({self.retriever.timeouts.per_attempt}), using default 10.0")
            self.retriever.timeouts.per_attempt = 10.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary representation."""
        return asdict(self)


def _env_bool(name: str, default: bool) -> bool:
    """Parse boolean environment variable with fallback to default."""
    value = os.environ.get(name)
    if value is None:
        return default
    
    value_lower = value.lower().strip()
    if value_lower in ("true", "1", "yes", "on"):
        return True
    elif value_lower in ("false", "0", "no", "off"):
        return False
    else:
        _logger.warning(f"Invalid boolean value for {name}: '{value}', using default {default}")
        return default


def _env_int(name: str, default: int) -> int:
    """Parse integer environment variable with fallback to default."""
    value = os.environ.get(name)
    if value is None:
        return default
    
    try:
        return int(value.strip())
    except ValueError:
        _logger.warning(f"Invalid integer value for {name}: '{value}', using default {default}")
        return default


def _env_float(name: str, default: float) -> float:
    """Parse float environment variable with fallback to default."""
    value = os.environ.get(name)
    if value is None:
        return default
    
    try:
        return float(value.strip())
    except ValueError:
        _logger.warning(f"Invalid float value for {name}: '{value}', using default {default}")
        return default


def _env_str(name: str, default: str) -> str:
    """Get string environment variable with fallback to default."""
    return os.environ.get(name, default).strip()


def _parse_log_level(value: Union[str, int]) -> int:
    """
    Parse log level from string name or numeric value.
    
    Args:
        value: Log level as string (DEBUG, INFO, etc.) or integer (10, 20, etc.)
        
    Returns:
        Integer log level, clamped to valid range
    """
    if isinstance(value, int):
        # Clamp to valid logging levels (NOTSET=0 to CRITICAL=50)
        return max(0, min(50, value))
    
    # Handle string log levels
    level_map = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "WARN": 30,  # Common alias
        "ERROR": 40,
        "CRITICAL": 50,
        "FATAL": 50,  # Common alias
    }
    
    value_upper = str(value).upper().strip()
    if value_upper in level_map:
        return level_map[value_upper]
    
    # Try parsing as numeric string
    try:
        numeric_level = int(value)
        return max(0, min(50, numeric_level))
    except ValueError:
        _logger.warning(f"Invalid log level '{value}', using default INFO (20)")
        return 20


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries, with override taking precedence.
    
    Args:
        base: Base dictionary
        override: Override dictionary to merge on top
        
    Returns:
        New merged dictionary
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    
    return result


def _load_file_config() -> Dict[str, Any]:
    """
    Load configuration from file specified by ORCH_CONFIG_FILE environment variable.
    
    Returns:
        Configuration dictionary, or empty dict if file not found/invalid
    """
    config_file = os.environ.get("ORCH_CONFIG_FILE")
    if not config_file:
        return {}
    
    config_file = config_file.strip()
    if not os.path.isfile(config_file):
        _logger.warning(f"Configuration file not found: {config_file}")
        return {}
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            if config_file.lower().endswith('.json'):
                return json.load(f)
            elif config_file.lower().endswith(('.yaml', '.yml')):
                # Try to import yaml, fall back gracefully if not available
                try:
                    import yaml
                    return yaml.safe_load(f) or {}
                except ImportError:
                    _logger.warning("YAML file specified but pyyaml not available, skipping file config")
                    return {}
            else:
                # Assume JSON for unknown extensions
                return json.load(f)
                
    except (json.JSONDecodeError, Exception) as e:
        _logger.warning(f"Failed to parse configuration file {config_file}: {e}")
        return {}


def load_orchestration_config() -> OrchestrationConfig:
    """
    Load orchestration configuration from defaults, file, and environment variables.
    
    Configuration precedence (lowest to highest):
    1. Hardcoded defaults
    2. Configuration file (if ORCH_CONFIG_FILE is set)
    3. Environment variable overrides
    
    Returns:
        OrchestrationConfig instance with validated settings
    """
    # Start with defaults
    defaults = {
        "logging": {"level": 20},
        "retriever": {
            "cache": {"enabled": False, "max_size": 256, "ttl": 600},
            "reranking": {"enabled": False, "model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "top_k": 12},
            "timeouts": {"per_attempt": 10.0}
        },
        "debug": {"include_user_ids": False, "include_subquery_details": False}
    }
    
    # Merge file configuration if available
    file_config = _load_file_config()
    if file_config:
        defaults = _deep_merge_dict(defaults, file_config)
    
    # Apply environment variable overrides
    # Logging
    if "ORCH_LOG_LEVEL" in os.environ:
        log_level_raw = os.environ["ORCH_LOG_LEVEL"].strip()
        defaults["logging"]["level"] = _parse_log_level(log_level_raw)
    
    # Cache configuration
    if "RETRIEVER_CACHE_ENABLED" in os.environ:
        defaults["retriever"]["cache"]["enabled"] = _env_bool("RETRIEVER_CACHE_ENABLED", False)
    if "RETRIEVER_CACHE_MAX_SIZE" in os.environ:
        defaults["retriever"]["cache"]["max_size"] = _env_int("RETRIEVER_CACHE_MAX_SIZE", 256)
    if "RETRIEVER_CACHE_TTL_SEC" in os.environ:
        defaults["retriever"]["cache"]["ttl"] = _env_int("RETRIEVER_CACHE_TTL_SEC", 600)
    
    # Reranking configuration
    if "RERANK_ENABLED" in os.environ:
        defaults["retriever"]["reranking"]["enabled"] = _env_bool("RERANK_ENABLED", False)
    if "RERANK_MODEL" in os.environ:
        defaults["retriever"]["reranking"]["model"] = _env_str("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    if "RERANK_TOP_K" in os.environ:
        defaults["retriever"]["reranking"]["top_k"] = _env_int("RERANK_TOP_K", 12)
    
    # Timeout configuration
    if "RETRIEVER_PER_ATTEMPT_TIMEOUT" in os.environ:
        defaults["retriever"]["timeouts"]["per_attempt"] = _env_float("RETRIEVER_PER_ATTEMPT_TIMEOUT", 10.0)
    
    # Debug configuration
    if "DEBUG_INCLUDE_USER_IDS" in os.environ:
        defaults["debug"]["include_user_ids"] = _env_bool("DEBUG_INCLUDE_USER_IDS", False)
    if "DEBUG_INCLUDE_SUBQUERY_DETAILS" in os.environ:
        defaults["debug"]["include_subquery_details"] = _env_bool("DEBUG_INCLUDE_SUBQUERY_DETAILS", False)
    
    # Create configuration objects
    logging_cfg = LoggingCfg(level=defaults["logging"]["level"])
    
    cache_cfg = CacheCfg(
        enabled=defaults["retriever"]["cache"]["enabled"],
        max_size=defaults["retriever"]["cache"]["max_size"],
        ttl=defaults["retriever"]["cache"]["ttl"]
    )
    
    rerank_cfg = RerankCfg(
        enabled=defaults["retriever"]["reranking"]["enabled"],
        model=defaults["retriever"]["reranking"]["model"],
        top_k=defaults["retriever"]["reranking"]["top_k"]
    )
    
    timeouts_cfg = TimeoutsCfg(
        per_attempt=defaults["retriever"]["timeouts"]["per_attempt"]
    )
    
    retriever_cfg = RetrieverCfg(
        cache=cache_cfg,
        reranking=rerank_cfg,
        timeouts=timeouts_cfg
    )
    
    debug_cfg = DebugCfg(
        include_user_ids=defaults["debug"]["include_user_ids"],
        include_subquery_details=defaults["debug"]["include_subquery_details"]
    )
    
    return OrchestrationConfig(
        logging=logging_cfg,
        retriever=retriever_cfg,
        debug=debug_cfg
    )

