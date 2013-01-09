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
    logger = pyutools.io.get_logger(
            name='pyutools.misc.scripts.restore_backup',
            out=sys.stdout if args.log is None else args.log,
            level=pyutools.misc.util.verbosity_to_log_level(args.verbosity))
    # Verify that archive is empty.
    if args.archive is not None:
        assert os.path.isdir(args.archive)
        if (os.listdir(args.archive) and
            not pyutools.io.confirm(
                'Archive folder (%s) is not empty, are you sure you want to '
                'continue?' % args.archive)):
                # Abort if user asks for it.
                return 1
    rval = run(args, logger)
    if rval == 0:
        logger.info('Restoration was successful')
    else:
        logger.warn('Restoration could not be fully performed (error code: %s)'
                    % rval)
    return rval


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
    parser.add_argument('--log', help='Output to this log file instead of stdout')
    parser.add_argument('--move', action='store_true',
                        help='Specify that restored files should be moved '
                             'rather than copied')
    parser.add_argument('--archive',
                        help='Archive folder for deleted files when using the '
                             '--move option')
    parser.add_argument('--verbosity', help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    return parser.parse_args()


def restore_symlink(src, dst, logger):
    """
    Handle the restoration of a symlink.

    :param src: The source symlink to be restored.

    :param dst: The destination path for the restored symlink.

    :param logger: Logger to use for output.

    :return: 0 on success, 1 if a conflict was found, 2 if an error occurred.
    """
    rval = 0
    assert os.path.islink(src)
    if os.path.lexists(dst):
        if os.path.islink(dst):
            # Are they the same links?
            if os.readlink(src) == os.readlink(dst):
                logger.debug(
                        'Skipping existing identical symlink: '
                        '%s == %s' % (src, dst))
            else:
                logger.debug('The destination symlink already exists and is '
                             'not the same: %s' % dst)
                rval = 1
        else:
            logger.debug('The destination path already exists and is not a '
                         'symlink: %s' % dst)
            rval = 1
    else:
        # Copy symlink.
        logger.debug('Restoring symlink: %s -> %s' % (src, dst))
        try:
            pyutools.io.copy_link(src, dst)
        except Exception:
            logger.debug('Failed to restore symlink: %s' % src)
            rval = 2
    return rval


def run(args, logger):
    """
    Perform the restoration.

    :param args: Object holding (parsed) arguments.

    :logger: The logger to use for output purpose.

    :return: 0 on success, non-zero integer on failure.
    """
    logger.debug('Starting restore process %s -> %s' %
                 (args.source, args.destination))
    for check_dir in ('source', 'destination'):
        if not os.path.isdir(getattr(args, check_dir)):
            logger.error('%s argument is not an existing folder: %s' %
                         (check_dir.capitalize(), getattr(args, check_dir)))
            return 1

    # List of files for which a conflict was detected.
    conflicts = []
    # List of exceptions raised during the walk.
    exceptions = []

    def add_conflict(f_path, f_dest):
        logger.debug('Conflict detected: %s != %s' % (f_path, f_dest))
        conflicts.append(f_path)

    def walk_error(exc):
        """
        Called when an exception is raised during the walk.
        """
        exc_str = str(exc)
        logger.debug('Exception during walk: %s' % exc_str)
        exceptions.append(exc_str)

    # List of files whose restoration failed.
    failed_files = []
    # List of directories whose restoration failed.
    failed_dirs = []
    # Set of directories already fully restored "as is". It is used to be more
    # efficient, by avoiding the need to check their content.
    # Note that this set also contains directories found in `failed_dirs`.
    restored_dirs = set()
    for dir_path, dir_names, file_names in os.walk(args.source,
                                                   onerror=walk_error):
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
        if not os.path.lexists(dest_path):
            logger.debug('Creating folder: %s' % dest_path)
            try:
                os.mkdir(dest_path)
            except Exception:
                logger.debug('Unable to create folder: %s' % dest_path)
                failed_dirs.append(dir_path)
                continue
        else:
            if not os.path.isdir(dest_path):
                logger.error('Destination folder exists but is not a folder: '
                             '%s' % dest_path)
                return 1

        # Examine files.
        for f_name in file_names:
            f_path = os.path.join(dir_path, f_name)
            f_dest = os.path.join(dest_path, f_name)
            # Symbolic links are handled in a specific way.
            if os.path.islink(f_path):
                rcode = restore_symlink(f_path, f_dest, logger)
                if rcode == 1:
                    add_conflict(f_path, f_dest)
                elif rcode == 2:
                    failed_files.append(f_path)
                else:
                    assert rcode == 0
            elif not os.path.isfile(f_path):
                logger.debug('Failed to restore broken file: %s' % f_path)
                failed_files.append(f_path)
            elif os.path.islink(f_dest):
                # Source is not a link but destination is.
                add_conflict(f_path, f_dest)
            elif os.path.lexists(f_dest):
                if not pyutools.io.can_read_file(f_path):
                    logger.debug('Cannot read source file: %s' % f_path)
                    failed_files.append(f_path)
                elif (os.path.isfile(f_dest) and
                      not pyutools.io.can_read_file(f_dest)):
                    logger.debug('Cannot read destination file: %s' % f_dest)
                    failed_files.append(f_path)
                elif (os.path.isfile(f_dest) and
                      pyutools.io.is_same_file(f_path, f_dest)):
                    # This is the same file.
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
                            if not os.path.lexists(arch_dir):
                                os.makedirs(arch_dir)
                            shutil.move(f_path, f_arch)
                else:
                   # We have a conflict.
                   add_conflict(f_path, f_dest)
            else:
                # File does not exist: we restore it.
                logger.debug('Restoring: %s -> %s' % (f_path, f_dest))
                try:
                    if args.move:
                        shutil.move(f_path, f_dest)
                    else:
                        shutil.copy2(f_path, f_dest)
                except Exception:
                    logger.debug('Failed to restore file: %s' % f_path)
                    failed_files.append(f_path)

        # Examine folders.
        for d_name in dir_names:
            d_path = os.path.join(dir_path, d_name)
            d_dest = os.path.join(dest_path, d_name)

            if os.path.islink(d_path):
                rcode = restore_symlink(d_path, d_dest, logger)
                if rcode == 1:
                    add_conflict(d_path, d_dest)
                elif rcode == 2:
                    failed_dirs.append(d_path)
                else:
                    assert rcode == 0

            elif os.path.islink(d_dest):
                # Source is not a link but destination is.
                add_conflict(d_path, d_dest)

            elif os.path.lexists(d_dest):
                assert os.path.isdir(d_path)
                if os.path.isdir(d_dest):
                    # If it is an existing folder then we will walk into it at
                    # some point: nothing needs to be done here.
                    logger.debug('Folder already exists, will recurse into it: '
                                 '%s' % d_dest)
                else:
                    logger.debug('Failed to restore directory because '
                                 'destination exists but is not a directory: '
                                 '%s' % d_dest)
                    failed_dirs.append(d_path)
            else:
                assert os.path.isdir(d_path)
                logger.debug('Restoring: %s -> %s' % (d_path, d_dest))
                try:
                    if args.move:
                        shutil.move(d_path, d_dest)
                    else:
                        shutil.copytree(d_path, d_dest, symlinks=True)
                except Exception:
                    logger.debug('Failed to restore directory: %s' % d_path)
                    failed_dirs.append(d_path)
                restored_dirs.add(d_path)

    rval = 0
    if failed_files:
        logger.warning('The following files could not be restored '
                       '(maybe you do not have proper permissions): '
                       '\n  %s' % '\n  '.join(sorted(failed_files)))
        rval = 1

    if failed_dirs:
        logger.warning('The following folders could not be fully restored '
                       '(maybe you do not have proper permissions): '
                       '\n  %s' % '\n  '.join(sorted(failed_dirs)))
        rval = 1

    if conflicts:
        logger.warning('The following files are in conflict and thus were not '
                       'restored:\n  %s' % '\n  '.join(conflicts))
        rval = 1

    if exceptions:
        logger.warning('The following exceptions were raised during the walk:'
                       '\n  %s' % '\n  '.join(sorted(exceptions)))
        rval = 1

    return rval


if __name__ == '__main__':
    sys.exit(main())
