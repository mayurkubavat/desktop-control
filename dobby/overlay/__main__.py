"""Entry point for the overlay helper process: ``python -m dobby.overlay``.

``python -m dobby.overlay --demo`` runs a short self-driving demo instead of
reading commands from stdin.
"""

import os
import sys

if __name__ == "__main__":
    if sys.platform == "darwin":
        from .mac_helper import main
    elif sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        from .x11_helper import main
    else:
        sys.stderr.write("dobby.overlay helper needs macOS or a Linux X11 DISPLAY\n")
        sys.exit(2)

    sys.exit(main(sys.argv[1:]))
