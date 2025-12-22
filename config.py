import sys
import configparser
import os
import zoneinfo

def get_config():
    """
    Reads configuration from config.ini and returns it as a dictionary.
    """
    config = configparser.ConfigParser()
    config.read('config.ini')

    # Basic error handling
    if not config.has_section('Vault'):
        raise Exception("Config file config.ini is missing required sections ([Vault]).")

    # Read values
    vault_path = config.get('Vault', 'path')
    
    # Read regex patterns if available
    regex_patterns = {}
    if config.has_section('Regex'):
        regex_patterns = dict(config.items('Regex'))
    
    # Read timezone if available, defaults to Europe/Stockholm
    timezone_str = 'Europe/Stockholm'
    if config.has_section('Timezone'):
        timezone_str = config.get('Timezone', 'timezone', fallback='Europe/Stockholm')
    
    try:
        timezone = zoneinfo.ZoneInfo(timezone_str)
    except Exception as e:
        print(f"Warning: Invalid timezone '{timezone_str}': {e}. Using Europe/Stockholm", file=sys.stderr)
        timezone = zoneinfo.ZoneInfo('Europe/Stockholm')

    # Expand user path for vault_path and inbox_path
    return {
        'vault_path': os.path.expanduser(vault_path),
        'regex_patterns': regex_patterns,
        'timezone': timezone
    }

# Load configuration on import
try:
    app_config = get_config()
    VAULT_PATH = app_config['vault_path']
    REGEX_PATTERNS = app_config['regex_patterns']
    TIMEZONE = app_config['timezone']
except Exception as e:
    print(f"Error loading configuration: {e}")
    sys.exit(1)

