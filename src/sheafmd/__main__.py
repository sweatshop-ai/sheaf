"""python -m sheafmd is the same as the sheaf command."""
import sys

from .cli import main

sys.exit(main())
