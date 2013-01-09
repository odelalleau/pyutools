#!/usr/bin/env python
#
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


__all__ = []


import argparse
import logging
import os
import shutil
import sys


import pyutools
from pyutools.misc.util import execute


def get_root_commits():
    """
    Return the list of root commits in the repository.

    If unable to find any or if an error occurs, an empty list is returned.
    Note that a repository may have multiple root commits (this is why the
    returned value is a list).
    """
    rcode, stdout = execute('git rev-list --max-parents=0 HEAD',
                            return_stdout=True)
    if rcode != 0:
        return []
    return [s.strip() for s in stdout]


def main():
    """
    Executable entry point.

    :return: 0 on success, non-zero on failure.
    """
    args = parse_arguments()
    logger = pyutools.io.get_logger(
            name='pyutools.git.scripts.flatten',
            out=sys.stdout if args.log is None else args.log,
            level=pyutools.misc.util.verbosity_to_log_level(args.verbosity))
    rval = run(args, logger)
    return rval


def parse_arguments():
    """
    Parse command-line arguments.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
            description=(
                'Flatten Git history. This script must be run from the root '
                'directory of a Git repository.'))
    parser.add_argument('--verbosity', help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    parser.add_argument('--log', help='Output to this log file instead of stdout')
    return parser.parse_args()


def run(args, logger):
    """
    Perform flattening.

    :param args: Object holding (parsed) arguments.

    :logger: The logger to use for output purpose.

    :return: 0 on success, non-zero integer on failure.
    """
    # Ensure we are at the root of a Git repository.
    if not os.path.isdir('.git'):
        raise RuntimeError(
            'Unable to find a .git folder in current working directory. You '
            'must run this script from the root of a Git repository.')

    # Identify the repository root. Currently we only support a single root.
    roots = get_root_commits()
    if len(roots) > 1:
        raise NotImplementedError(
            'Found multiple root commits in this repository. Current '
            'implementation only supports a single root commit.')
    if len(roots) == 0:
        raise RuntimeError('Unable to find the root commit.')
    assert len(roots) == 1
    root = roots[0]
    logger.debug('Found root commit: %s' % root)

    # Initialize recursion: flatten from first commit to HEAD.

    return 0


if __name__ == '__main__':
    sys.exit(main())
