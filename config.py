import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Directory for Obsidian notes. A subdirectory will be created for each group.
VAULT_PATH = os.path.expanduser("vault")

# signal-cli JSON-RPC endpoint (TCP Socket).
# Ensure signal-cli is running with:
# signal-cli -u YOUR_NUMBER jsonRpc --tcp 127.0.0.1:7583
SIGNAL_RPC_HOST = "127.0.0.1"
SIGNAL_RPC_PORT = 7583
