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


def main():
    """
    Executable entry point.

    :return: 0 on success, non-zero on failure.
    """
    args = parse_arguments()
    # Verify that we know what we are doing when using the '--move' option.
    if args.move:
        if not pyutools.io.confirm(
                'Using the \'--move\' option will delete files from the '
                'backup folder, are you sure you want to continue?'):
            return 1
    # Setup logger.
    if args.verbosity == 0:
        level = logging.ERROR
    elif args.verbosity == 1:
        level = logging.INFO
    elif args.verbosity == 2:
        level = logging.DEBUG
    else:
        raise ValueError('Invalid value for verbosity: %s' % args.verbosity)
    logger = pyutools.io.get_logger(
            name='pyutools.misc.scripts.restore_backup',
            out='stdout',
            level=level)
    # Verify that archive is empty.
    if args.archive is not None:
        assert os.path.isdir(args.archive)
        if (os.listdir(args.archive) and
            not pyutools.io.confirm(
                'Archive folder (%s) is not empty, are you sure you want to '
                'continue?' % args.archive)):
                # Abort if user asks for it.
                return 1
    return run(args, logger)


def parse_arguments():
    """
    Parse command-line arguments.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
            description=(
                'Restore backed up files into their original folder. '
                'This script will automatically restore missing files, skip '
                'identical files, and prompt for manual merge in case of '
                'conflicts.'))
    parser.add_argument('--source', help='Folder containing backed up files',
                        required=True)
    parser.add_argument('--destination', help='Folder we want to restore files into',
                        required=True)
    parser.add_argument('--move', action='store_true',
                        help='Specify that restored files should be moved '
                             'rather than copied')
    parser.add_argument('--archive',
                        help='Archive folder for deleted files when using the '
                             '--move option')
    parser.add_argument('--verbosity', help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    return parser.parse_args()


def run(args, logger):
    """
    Perform the restoration.

    :param args: Object holding (parsed) arguments.

    :logger: The logger to use for output purpose.

    :return: 0 on success, non-zero integer on failure.
    """
    logger.debug('Restoring %s -> %s' % (args.source, args.destination))
    for check_dir in ('source', 'destination'):
        if not os.path.isdir(getattr(args, check_dir)):
            logger.error('%s argument is not an existing folder: %s' %
                         (check_dir.capitalize(), getattr(args, check_dir)))
            return 1
    # List of files for which a conflict was detected.
    conflicts = []
    # Set of directories already fully restored "as is". It is used to be more
    # efficient, by avoiding the need to check their content.
    restored_dirs = set()
    for dir_path, dir_names, file_names in os.walk(args.source):
        if dir_path in restored_dirs:
            # This folder has already been fully restored.
            logger.debug('Skipping folder already restored: %s' % dir_path)
            continue
        # Find destination path.
        rel_path = os.path.relpath(dir_path, args.source)
        dest_path = os.path.join(args.destination, rel_path)
        logger.debug('Subfolder: %s -> %s' % (dir_path, dest_path))
        if args.archive is not None:
            arch_path = os.path.join(args.archive, rel_path)
        else:
            arch_path = None

        # Create destination directory if needed.
        if not os.path.exists(dest_path):
            logger.debug('Creating folder: %s' % dest_path)
            os.mkdir(dest_path)
        else:
            if not os.path.isdir(dest_path):
                logger.error('Destination folder exists but is not a folder: '
                             '%s' % dest_path)
                return 1

        # Examine files.
        for f_name in file_names:
            f_path = os.path.join(dir_path, f_name)
            if os.path.islink(f_path):
                logger.error('Symbolic links are not currently supported: %s' %
                             f_path)
                return 1
            assert os.path.isfile(f_path)
            f_dest = os.path.join(dest_path, f_name)
            if os.path.exists(f_dest):
                if pyutools.io.is_same_file(f_path, f_dest):
                    logger.debug('Skipping existing identical file: %s == %s' %
                                 (f_path, f_dest))
                    if args.move:
                        if arch_path is None:
                            logger.debug('Deleting file: %s' % f_path)
                            os.remove(f_path)
                        else:
                            f_arch = os.path.join(arch_path, f_name)
                            logger.debug('Moving to archive: %s -> %s' %
                                         (f_path, f_arch))
                            arch_dir = os.path.dirname(f_arch)
                            if not os.path.exists(arch_dir):
                                os.makedirs(arch_dir)
                            shutil.move(f_path, f_arch)
                else:
                   # We have a conflict.
                   logger.debug('Conflict detected: %s != %s' %
                                (f_path, f_dest))
                   conflicts.append(f_path)
            else:
                # File does not exist: we restore it.
                logger.debug('Restoring: %s -> %s' % (f_path, f_dest))
                if args.move:
                    shutil.move(f_path, f_dest)
                else:
                    shutil.copy2(f_path, f_dest)

        # Examine folders.
        for d_name in dir_names:
            d_path = os.path.join(dir_path, d_name)
            assert not os.path.islink(d_path)
            assert os.path.isdir(d_path)
            d_dest = os.path.join(dest_path, d_name)
            if os.path.exists(d_dest):
                logger.debug('Folder already exists, will recurse into it: %s'
                             % d_dest)
            else:
                logger.debug('Restoring: %s -> %s' % (d_path, d_dest))
                if args.move:
                    shutil.move(d_path, d_dest)
                else:
                    shutil.copytree(d_path, d_dest, symlinks=True)
                restored_dirs.add(d_path)

    if conflicts:
        logger.info('The following files are in conflict and thus were not '
                    'restored:\n  %s' % '\n  '.join(conflicts))

    return 0

if __name__ == '__main__':
    sys.exit(main())
