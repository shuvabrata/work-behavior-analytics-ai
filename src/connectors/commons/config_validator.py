"""
Configuration validation module.

Validates configuration files for GitHub and Jira integrations,
including regex patterns, source specifications, and other settings.
"""

import re
from typing import Dict, List, Optional, Any
import json
from pathlib import Path


def validate_regex_pattern(pattern: str, pattern_name: str) -> Optional[str]:
    """
    Validate that a string is a valid regex pattern with exactly one capture group.
    
    Args:
        pattern: Regex pattern string to validate
        pattern_name: Name of the pattern for error messages
        
    Returns:
        Error message if invalid, None if valid
    """
    try:
        compiled = re.compile(pattern)
        # Count capture groups
        groups = compiled.groups
        if groups == 0:
            return f"{pattern_name}: Pattern must have at least one capture group () to extract issue key"
        return None
    except re.error as e:
        return f"{pattern_name}: Invalid regex pattern - {str(e)}"
    except Exception as e:
        return f"{pattern_name}: Unexpected error validating pattern - {str(e)}"


def validate_extraction_sources(sources: Any, field_name: str = "extraction_sources") -> Optional[str]:
    """
    Validate extraction_sources field.
    
    Args:
        sources: Value to validate
        field_name: Name of the field for error messages
        
    Returns:
        Error message if invalid, None if valid
    """
    if not isinstance(sources, list):
        return f"{field_name}: Must be a list, got {type(sources).__name__}"
    
    if len(sources) == 0:
        return f"{field_name}: Must contain at least one source"
    
    valid_sources = {"branch", "commit_message"}
    for source in sources:
        if not isinstance(source, str):
            return f"{field_name}: All items must be strings, got {type(source).__name__}"
        if source not in valid_sources:
            return f"{field_name}: Invalid source '{source}'. Must be one of: {', '.join(valid_sources)}"
    
    return None


def validate_repo_config(repo_config: Dict[str, Any], repo_index: int) -> List[str]:
    """
    Validate a single repository configuration.
    
    Args:
        repo_config: Repository configuration dictionary
        repo_index: Index of the repo in the config (for error messages)
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    repo_label = f"repos[{repo_index}]"
    
    # Validate required fields
    if "url" not in repo_config:
        errors.append(f"{repo_label}: Missing required field 'url'")
        return errors  # Can't continue without URL
    
    url = repo_config.get("url")
    if not isinstance(url, str) or not url.strip():
        errors.append(f"{repo_label}: 'url' must be a non-empty string")
    
    # Validate optional branch_name_patterns
    if "branch_name_patterns" in repo_config:
        patterns = repo_config["branch_name_patterns"]
        
        if not isinstance(patterns, list):
            errors.append(f"{repo_label}.branch_name_patterns: Must be a list, got {type(patterns).__name__}")
        else:
            for i, pattern in enumerate(patterns):
                if not isinstance(pattern, str):
                    errors.append(f"{repo_label}.branch_name_patterns[{i}]: Must be a string, got {type(pattern).__name__}")
                else:
                    error = validate_regex_pattern(pattern, f"{repo_label}.branch_name_patterns[{i}]")
                    if error:
                        errors.append(error)
    
    # Validate optional extraction_sources
    if "extraction_sources" in repo_config:
        sources = repo_config["extraction_sources"]
        error = validate_extraction_sources(sources, f"{repo_label}.extraction_sources")
        if error:
            errors.append(error)
    
    return errors


def validate_github_config(config_path: str) -> List[str]:
    """
    Validate GitHub configuration file.
    
    Args:
        config_path: Path to .config.json file
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    # Check file exists
    path = Path(config_path)
    if not path.exists():
        errors.append(f"Configuration file not found: {config_path}")
        return errors
    
    # Load and parse JSON
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON in {config_path}: {str(e)}")
        return errors
    except Exception as e:
        errors.append(f"Error reading {config_path}: {str(e)}")
        return errors
    
    # Validate structure
    if not isinstance(config, dict):
        errors.append(f"Configuration root must be an object, got {type(config).__name__}")
        return errors
    
    if "repos" not in config:
        errors.append("Configuration must have 'repos' field")
        return errors
    
    repos = config["repos"]
    if not isinstance(repos, list):
        errors.append(f"'repos' must be a list, got {type(repos).__name__}")
        return errors
    
    if len(repos) == 0:
        errors.append("'repos' list is empty - must contain at least one repository")
        return errors
    
    # Validate each repository
    for i, repo in enumerate(repos):
        if not isinstance(repo, dict):
            errors.append(f"repos[{i}]: Must be an object, got {type(repo).__name__}")
            continue
        
        repo_errors = validate_repo_config(repo, i)
        errors.extend(repo_errors)
    
    return errors
