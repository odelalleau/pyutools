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


"""
Miscellaneous utility functions used in various places in pyutools.
"""


__all__ = [
    'execute',
    'verbosity_to_log_level',
    ]


import logging
import subprocess


class ExecuteError(Exception):
    """
    Raised by `execute` when `must_succeed` is True and the command fails.
    """


class Storage(object):

    """
    Basic container class.
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)


def execute(cmd, return_code=True, return_stdout=False, return_stderr=False,
            show_stdout=True, show_stderr=True, must_succeed=False):
    """
    Run a system command.

    :param cmd: The command to be run, either as a string or as a list of
    strings. If it is a string, it is split very naively (using blank spaces as
    separators), which only works if individual arguments do not contain blank
    spaces.

    :param return_code: Whether to return the command's return code.

    :param return_stdout: Whether to return the command's stdout.

    :param return_stderr: Whether to return the command's stderr.

    :param show_stdout: Whether the command's stdout should be printed to the
    standard output. Automatically set to False when `return_stdout` is True.

    :param show_stderr: Whether the command's stderr should be printed to the
    standard output. Automatically set to False when `return_stderr` is True.

    :param must_succeed: When True, automatically sets return_code=False and
    return_stdout=True. If the command's return code is non-zero, an
    ExecuteError exception is raised. This is useful for commands that are
    expected to succeed, for which we just need the output.

    :return: If only one of the `return_*` arguments is True, then the
    corresponding item is returned. If multiple `return_*` arguments are True,
    then return a list with the corresponding items. The order of the items is
    always the same as in (return code, stdout, sterr).
    Note that stdout and stderr are output as list of strings, where each
    string is a line of the output. Trailing empty lines are omitted.
    """
    if not isinstance(cmd, (basestring, list)):
        raise TypeError('The `cmd` argument must be a string or a list of '
                        'strings')
    if isinstance(cmd, basestring):
        cmd = cmd.split(' ')
    if must_succeed:
        return_code = False
        return_stdout = True
    # Set up the stdout / stderr for this command.
    if return_stdout:
        stdout = subprocess.PIPE
    elif show_stdout:
        stdout = None
    else:
        stdout = os.devnull()
    if return_stderr:
        stderr = subprocess.PIPE
    elif show_stderr:
        stderr = None
    else:
        stderr = os.devnull()

    # Run command.
    proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
    stdout_data, stderr_data = proc.communicate()
    r_code = proc.returncode

    # Failure condition.
    if must_succeed and r_code != 0:
        raise ExecuteError('Command failure with return code %s: %s' %
                           (r_code, cmd))

    # Function to format the output into a list of strings (removing the
    # trailing blank lines).
    def format(s):
        rval = s.split('\n')
        while rval and not rval[-1]:
            del rval[-1]
        return rval

    # Return desired output.
    rval = []
    if return_code:
        rval.append(r_code)
    if return_stdout:
        rval.append(format(stdout_data))
    if return_stderr:
        rval.append(format(stderr_data))
    if len(rval) == 1:
        return rval[0]
    else:
        return rval


def verbosity_to_log_level(verbosity):
    """
    Return the logging level associated to given verbosity level, i.e:

        0 -> ERROR
        1 -> INFO
        2 -> DEBUG

    Other verbosity values raise a ValueError.
    """
    if verbosity == 0:
        return logging.ERROR
    elif verbosity == 1:
        return logging.INFO
    elif verbosity == 2:
        return logging.DEBUG
    else:
        raise ValueError('Invalid value for verbosity: %s' % verbosity)
