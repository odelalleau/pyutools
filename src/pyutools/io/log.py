# Copyright (c) 2012, Olivier Delalleau
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""
Common logging utilities.
"""


__all__ = ['get_logger']


import logging
import sys


_loggers = {}


def get_logger(name, level=None, out=None):
    """
    Obtain a logger by its name.

    :param name: Name of the logger.

    :param level: Level of the logger (`None` means we use current logging
        default behavior).
    
    :param out: Where do we want this logger to output information, among:
        - `None`: Do not assign any output to this logger.
        - 'stdout': Output to stdout stream.
        - 'stderr': Output to stderr stream.
    """
    if name not in _loggers:
        # Actually create the logger.
        logger = logging.getLogger(name)
        if level is not None:
            logger.setLevel(level)
        if out is not None:
            if out == 'stdout':
                handler = logging.StreamHandler(sys.stdout)
            elif out == 'stderr':
                handler = logging.StreamHandler(sys.stderr)
            else:
                raise ValueError('Invalid value for \'out\' argument: %s' %
                                 out)
            if level is not None:
                handler.setLevel(level)
            logger.addHandler(handler)
        _loggers[name] = logger
    return _loggers[name]
