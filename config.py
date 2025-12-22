import sys
import configparser
import os

def get_config():
    """
    Reads configuration from config.ini and returns it as a dictionary.
    """
    config = configparser.ConfigParser()
    config.read('config.ini')

    # Basic error handling
    if not config.has_section('Vault') or not config.has_section('Signal'):
        raise Exception("Config file config.ini is missing required sections ([Vault], [Signal]).")

    # Read values
    vault_path = config.get('Vault', 'path')
    inbox_path = config.get('Vault', 'inbox')
    signal_number = config.get('Signal', 'Number')
    
    # Read regex patterns if available
    regex_patterns = {}
    if config.has_section('Regex'):
        regex_patterns = dict(config.items('Regex'))

    # Expand user path for vault_path and inbox_path
    return {
        'vault_path': os.path.expanduser(vault_path),
        'inbox_path': os.path.expanduser(inbox_path),
        'signal_number': signal_number,
        'regex_patterns': regex_patterns
    }

# Load configuration on import
try:
    app_config = get_config()
    VAULT_PATH = app_config['vault_path']
    INBOX_PATH = app_config['inbox_path']
    SIGNAL_NUMBER = app_config['signal_number']
    REGEX_PATTERNS = app_config['regex_patterns']
except Exception as e:
    print(f"Error loading configuration: {e}")
    sys.exit(1)

