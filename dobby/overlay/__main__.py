"""Entry point for the overlay helper process: ``python -m dobby.overlay``.

``python -m dobby.overlay --demo`` runs a short self-driving demo instead of
reading commands from stdin.
"""

import sys

if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.stderr.write("dobby.overlay helper only runs on macOS\n")
        sys.exit(2)
    from .mac_helper import main

    sys.exit(main(sys.argv[1:]))
