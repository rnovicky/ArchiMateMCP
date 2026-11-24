"""
Starts the server from any working directory:  python run_server.py [stdio | http | check | config]

MCP clients start a stdio server without choosing its working directory, so
they cannot use "python -m app"; they run this file (see: python -m app config).
"""

from app.__main__ import main

if __name__ == "__main__":
    main()
