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


"""
Add new Git commits into Perforce history.
"""


import argparse
import logging
import os
import shutil
import sys
import traceback


import pyutools
from pyutools.misc import util
from pyutools.misc.util import execute


logger = None


def exec_out(cmd):
    """
    Return the stdout output of command 'cmd'. Raise exception on failure.

    By failure, we mean when the command's return code is non-zero.
    The stderr output is ignored (only logged in debug mode).
    """
    logger.debug('Running command: %s' % cmd)
    stdout, stderr = execute(cmd, must_succeed=True, return_stderr=True)
    if stderr:
        logger.debug('Command stderr: %s' % stderr)
    return stdout


def exec_all(cmd):
    """
    Return the return code, stdout and stderr of the command.
    """
    logger.debug('Running command: %s' % cmd)
    r_code, stdout, stderr = execute(
                                cmd, return_stdout=True, return_stderr=True)
    return r_code, stdout, stderr


def exec_code(cmd):
    """
    Return the return code only of the command.

    The stdout and stderr outputs are ignored (only logged in debug mode).
    """
    logger.debug('Running command: %s' % cmd)
    r_code, stdout, stderr = execute(
                                cmd, return_stdout=True, return_stderr=True)
    if stdout:
        logger.debug('Command stdout: %s' % stdout)
    if stderr:
        logger.debug('Command stderr: %s' % stderr)
    return r_code


def get_current_head():
    """
    Return hash of the current HEAD commit.
    """
    return exec_out('git rev-list HEAD -n 1')[0]


def main():
    """
    Executable entry point.

    :return: An integer among:
        0: success
        1: the Git branch needs to be manually rebased on the updated P4 branch
        2: unexpected error (check logs for more details)
    """
    global logger
    try:
        args = parse_arguments()
        logger = pyutools.io.get_logger(
                name='pyutools.git.scripts.git_to_p4',
                out=sys.stdout if args.log is None else args.log,
                level=util.verbosity_to_log_level(args.verbosity))
        return run(args)
    except:
        msg = ('Exception raised:\n%s' %
               '\n'.join(traceback.format_exception(*sys.exc_info())))
        if logger is None:
            print msg
        else:
            logger.error(msg)
        return 2


def parse_arguments():
    """
    Parse command-line arguments.

    :return: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
            description=(
                'Move new Git commits into Perforce history.'))
    parser.add_argument('--verbosity',
                        help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    parser.add_argument('--log',
                        help='Output to this log file instead of stdout')
    parser.add_argument('--git-repo', help='Path to the Git repository')
    parser.add_argument('--git-branch', help='Git branch to add to Perforce')
    parser.add_argument('--p4-branch',
                        help='Perforce branch (as renamed by git-p4) that '
                             'should receive the content of the Git branch')

    return parser.parse_args()


def run(args):
    """
    Perform git -> p4 copy.

    :param args: Object holding (parsed) arguments.

    :return: See documentation of `main()` function.
    """
    logger.info('Command arguments are: %s' % sys.argv)

    # Ensure no slash in branch names (untested).
    assert '/' not in args.git_branch and '/' not in args.p4_branch

    cwd = os.getcwd()
    try:
        # Move to the git repository folder.
        os.chdir(args.git_repo)
        # Ensure git repository is clean.
        assert not exec_out('git status --porcelain'), 'Need clean repository'
        # Switch to desired P4 target branch.
        exec_out('git checkout %s' % args.p4_branch)
        p4_init_head = get_current_head()
        # Fetch from P4.
        exec_out('git p4 sync')
        # Perform local update (should be a straight fast-forward update).
        exec_out('git p4 rebase')
        if get_current_head() != p4_init_head:
            # New commits from P4: push them to origin.
            logger.debug('Pushing new commits from P4 -> Git')
            exec_out('git push origin %s:%s' %
                     (args.p4_branch, args.p4_branch))
        else:
            logger.debug('No new commits from P4')
        p4_cur_head = get_current_head()
        # Fetch from origin.
        exec_out('git fetch origin')
        # This is the branch we want to add to P4.
        orig_branch = 'origin/%s' % args.git_branch
        # Create temporary work branch to work into.
        work_branch = 'git_to_p4_tmp'
        if exec_code('git checkout %s' % work_branch) == 0:
            # This means the work branch already exists (leftover from a
            # previous failed call): we just reset it.
            exec_out('git reset --hard %s' % orig_branch)
        else:
            # This means the work branch does not exist yet, so we create it.
            exec_out('git checkout -b %s %s' % (work_branch, orig_branch))
        # Attempt to rebase on top of P4 head.
        if exec_code('git rebase %s' % args.p4_branch) != 0:
            # Failed rebase: rollback and exit.
            exec_out('git rebase --abort')
            logger.info('Unable to rebase branch on top of P4 head, please '
                        'rebase manually then try again')
            return 1
        logger.debug('Rebase successful')
        # Get changes into P4 branch.
        exec_out('git checkout %s' % args.p4_branch)
        exec_out('git reset --hard %s' % work_branch)
        # Submit to P4. Note that it might still fail if a very recent P4
        # commit just introduced a conflict.
        r_code, stdout, stderr = exec_all('git p4 submit')
        if r_code == 0:
            # Push to origin.
            exec_out('git push origin %s:%s' %
                     (args.p4_branch, args.p4_branch))
            # We also push to the branch that we merged, to ensure users do not
            # accidentally work on an outdated branch.
            exec_out('git push --force origin %s:%s' %
                     (args.p4_branch, args.git_branch))
            logger.info('Successfully updated P4 repository')
            return 0
        else:
            logger.debug('Submit failed, resetting repo state')
            # Reset state of the repo.
            exec_out('git reset --hard %s' % p4_cur_head)
            # Verify that there is indeed a conflict when trying to rebase on
            # top of the current known state of the remote P4 branch. If this
            # is not the case, there must be another problem.
            logger.debug('Attempting to rebase on top of remote P4 branch to '
                         'validate the conflict situation')
            exec_out('git checkout -b %s' % work_branch)
            exec_out('git reset --hard %s' % orig_branch)
            # We need to figure out which branch is the remote P4 branch.
            remote_p4_branch = None
            for branch in exec_out('git branch -r'):
                branch = branch.strip()
                if (branch.endswith('/%s' % args.p4_branch) and
                    branch.startswith('p4/') and
                    '->' not in branch):
                    # Note that for some unknown reason, the master is:
                    #   p4/master
                    # while another branch can be
                    #   p4/some_dir/another_branch
                    assert remote_p4_branch is None
                    remote_p4_branch = branch
            assert remote_p4_branch is not None
            r_code = exec_code('git rebase %s' % remote_p4_branch)
            if r_code == 0:
                # Rebase succeeded: something must be wrong!
                logger.warning(
                    'Submission failed unexpectedly.\n'
                    'The stdout output is:\n'
                    '%s\n\n'
                    'The stderr output is:\n'
                    '%s' % (stdout, stderr))
                raise RuntimeError(
                    '\'git p4 submit\' failed even though \'git rebase\' worked')
            else:
                # Update P4 branch and push to origin repository before
                # failing.
                logger.debug('Conflict situation validated: aborting')
                exec_out('git rebase --abort')
                exec_out('git checkout %s' % args.p4_branch)
                exec_out('git p4 rebase')
                exec_out('git p4 push origin %s:%s' %
                         (args.p4_branch, args.p4_branch))
                logger.info('Unable to rebase branch on top of P4 head, '
                            'please rebase manually then try again')
                return 1
    finally:
        os.chdir(cwd)

    assert False, 'This point should be unreachable'


if __name__ == '__main__':
    sys.exit(main())
