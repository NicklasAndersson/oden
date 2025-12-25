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
    if not all(config.has_section(s) for s in ['Vault', 'Signal']):
        raise Exception("Config file config.ini is missing required sections ([Vault], [Signal]).")

    # Read values
    vault_path = config.get('Vault', 'path')
    signal_number = config.get('Signal', 'number')
    signal_cli_path = config.get('Signal', 'signal_cli_path', fallback=None)
    unmanaged_signal_cli = config.getboolean('Signal', 'unmanaged_signal_cli', fallback=False)
    signal_cli_host = config.get('Signal', 'host', fallback='127.0.0.1')
    signal_cli_port = config.getint('Signal', 'port', fallback=7583)
    
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
        'signal_number': signal_number,
        'signal_cli_path': os.path.expanduser(signal_cli_path) if signal_cli_path else None,
        'unmanaged_signal_cli': unmanaged_signal_cli,
        'signal_cli_host': signal_cli_host,
        'signal_cli_port': signal_cli_port,
        'regex_patterns': regex_patterns,
        'timezone': timezone
    }

# Load configuration on import
try:
    app_config = get_config()
    VAULT_PATH = app_config['vault_path']
    SIGNAL_NUMBER = app_config['signal_number']
    SIGNAL_CLI_PATH = app_config['signal_cli_path']
    UNMANAGED_SIGNAL_CLI = app_config['unmanaged_signal_cli']
    SIGNAL_CLI_HOST = app_config['signal_cli_host']
    SIGNAL_CLI_PORT = app_config['signal_cli_port']
    REGEX_PATTERNS = app_config['regex_patterns']
    TIMEZONE = app_config['timezone']
except Exception as e:
    print(f"Error loading configuration: {e}")
    sys.exit(1)

