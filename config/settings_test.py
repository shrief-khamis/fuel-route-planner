"""Settings for the test suite: the normal settings, but tests never write log files.

The variable is set before the normal settings load, so it wins over a value in .env.
"""

import os

os.environ['LOG_FILE_ENABLED'] = 'false'

from .settings import *  # noqa: E402, F403
