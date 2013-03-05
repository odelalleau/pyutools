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
Synchronize Git and P4 repositories.

IMPORTANT: When running, this script takes a lock in the local Git repository
since it assumes to be the only one modifying it. It also assumes that noone
else is currently modifying the P4 workspace. Violating these assumptions may
lead to unexpected results, possibly including permanent loss of data or
corrupted repositories. The lock is not NFS safe, so when running multiple
instances of this script, the Git repository MUST be local to where the script
is being executed.

This script requires a working Git <-> P4 setup to be already established with
the 'git p4' utility. Its goal is to merge (actually rebase) a remote Git
branch on top of the current P4 head. It differs from the basic usage of
'git p4' in the following ways:

    1. It takes changes from another branch instead of the current P4 branch.
    2. This branch is obtained from a remote repository instead of being local.
    3. Commits from P4 are pushed back to the remote repository.
    4. It preserves author names in the Git repository without requiring P4
       admin priviledges.

Because of point 3, this script can also be used to simply update a remote Git
repository with the latest P4 commits (see below for an example).

For this script to work the Git remote repository must have at least these
two branches:
    - A "feature branch" which is the branch whose commits we wish to add to
      the P4 history (option --git-branch)
    - A "mirror branch" which is meant to always be mirroring the P4 history
      (option --p4-branch).
Typically, the "feature branch" was branched from an earlier state of the
"mirror branch".

This script's simplified workflow is as follows:

              1. Import Git update <-- Git remote feature branch
P4 server --> 2. Import P4 update
              3. Perform rebase
P4 server <-- 4. Submit to P4
              5. Push to Git       --> Git remote feature & mirror branches

Note in particular that the Git remote feature branch is overridden by this
script with the rebased branch (when successful), to reduce the risk of people
accidentally using the old (outdated) feature branch.

RETURN VALUE:
    0 = success
    1 = the remote feature branch cannot be automatically rebased (it needs
        to be manually rebased and re-submitted)
    2 = unexpected error (see logs for more information)

EXAMPLES:

Note that these examples omit the "--git-repo" option, which is mandatory in
practice.

* To add remote feature branch "my_feature" to the "v1.5" branch, use:

    git_p4_sync.py --git-branch=my_feature --p4-branch=v1.5

* To only update the mirror branch "master" with latest P4 code, use:

    git_p4_sync.py --git-branch=master --p4-branch=master
"""


import argparse
import os
import sys
import traceback


import pyutools
from pyutools.io import Lock
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
    r_code, stdout, stderr = execute(cmd, return_stdout=True,
                                     return_stderr=True)
    if stdout:
        logger.debug('Command stdout: %s' % stdout)
    if stderr:
        logger.debug('Command stderr: %s' % stderr)
    if r_code != 0:
        raise RuntimeError('Non-zero return code in command: %s\nstdout: %s\nstderr: %s' % (
                cmd, stdout, stderr))
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
    except SystemExit:
        raise
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
                'Synchronize Git and P4 repositories. See in-file docstring '
                'for more details and examples.'))
    parser.add_argument('--verbosity',
                        help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    parser.add_argument('--log',
                        help='Output to this log file instead of stdout')
    parser.add_argument('--remote', default='origin',
                        help='Name of remote repository (default: origin)')
    parser.add_argument('--git-repo', help='Path to local Git repository',
                        required=True)
    parser.add_argument('--git-branch',
                         help='Remote feature branch to merge into P4',
                        required=True)
    parser.add_argument('--p4-branch', required=True,
                        help='Remote mirror branch of the P4 branch')

    return parser.parse_args()


def run(args):
    """
    Perform Git <-> P4 synchronization.

    :param args: Object holding (parsed) arguments.

    :return: See documentation of `main()` function.
    """
    logger.debug('Command arguments are: %s' % sys.argv)

    # Ensure no slash in branch names (untested).
    assert '/' not in args.git_branch and '/' not in args.p4_branch

    cwd = os.getcwd()

    lock = None
    try:
        # Move to the git repository folder.
        os.chdir(args.git_repo)

        # Wait 300s for possible long network latency.
        lock = Lock(os.path.join('.git', 'p4_git_sync_lock'), timeout=300,
                    refresh=30, err_if_timeout=True)
        lock.acquire()

        # Ensure git repository is clean.
        assert not exec_out('git status --porcelain'), 'Need clean repository'

        # Obtain email address associated to the P4 user account.
        p4_user_info = exec_out('p4 user -o')
        p4_email = None
        for line in p4_user_info:
            if line.lower().startswith('email:'):
                p4_email = line[len('email:'):].strip()
        logger.debug('Obtained P4 email: %s' % p4_email)
        assert p4_email is not None

        # Switch to desired P4 target branch.
        exec_out('git checkout %s' % args.p4_branch)

        # Fetch from remote.
        exec_out('git fetch %s' % args.remote)

        # Ensure we are in synch with remote. Usually this should always be the
        # case, unless a previous synchronization attempt was interrupted in
        # a non-clean state.
        head_before = get_current_head()
        exec_out('git reset --hard %s/%s' % (args.remote, args.p4_branch))
        # Known head of the P4 branch before we start synchronization.
        p4_init_head = get_current_head()
        if p4_init_head != head_before:
            logger.warning(
                'The %s local branch had to be reset to %s/%s. It is '
                'suspicious that they were out of synch: is it because of '
                'a previous script failure?' %
                (args.p4_branch, args.remote, args.p4_branch))

        # Fetch from P4.
        exec_out('git p4 sync')

        # Perform local update (should be a straight fast-forward update).
        exec_out('git p4 rebase')
        if get_current_head() != p4_init_head:
            # New commits from P4: push them to remote.
            logger.debug('Pushing new commits from P4 -> Git')
            exec_out('git push %s %s:%s' %
                     (args.remote, args.p4_branch, args.p4_branch))
            logger.info('New commits from P4')
        else:
            logger.info('No new commits from P4')
        p4_cur_head = get_current_head()

        # Find the remote P4 branch.
        # Note that the master is typically p4/master, but other branches can
        # be of the form p4/some_dir/another_branch (the reason for this
        # difference is unknown).
        remote_p4_branch = None
        for branch in exec_out('git branch -r'):
            branch = branch.strip()
            if (branch.endswith('/%s' % args.p4_branch) and
                branch.startswith('p4/') and
                '->' not in branch):
                # Found it.
                assert remote_p4_branch is None, (
                       "Found multiple p4-branch: %s %s" % (remote_p4_branch,
                                                            branch))
                remote_p4_branch = branch
        assert remote_p4_branch is not None, (
               "p4-branch not found: " + p4_branch)

        # This is the branch we want to add to P4.
        remo_branch = '%s/%s' % (args.remote, args.git_branch)

        # Create temporary work branch.
        work_branch = 'git_to_p4_tmp'
        if exec_code('git checkout %s' % work_branch) == 0:
            # This means the work branch already exists (leftover from a
            # previous failed call): we just reset it.
            exec_out('git reset --hard %s' % remo_branch)
        else:
            # This means the work branch does not exist yet, so we create it.
            exec_out('git checkout -b %s %s' % (work_branch, remo_branch))

        # Attempt to rebase on top of P4 head.
        if exec_code('git rebase %s' % args.p4_branch) != 0:
            # Failed rebase: rollback and exit.
            exec_out('git rebase --abort')
            logger.info('Unable to rebase branch on top of P4 head, please '
                        'rebase manually the git-branch to merge, then try '
                        'again')
            return 1
        logger.debug('Rebase successful')

        # Get changes into P4 branch.
        exec_out('git checkout %s' % args.p4_branch)
        exec_out('git reset --hard %s' % work_branch)

        # Submit to P4. Note that it might still fail if a very recent P4
        # commit just introduced a conflict.
        r_code, stdout, stderr = exec_all('git p4 submit')

        if r_code == 0:
            # Success:
            #   1. Restore author names in Git branch.
            #   2. Push to remote repository.

            # To restore author names, we first find the match between the
            # result of 'git p4 submit' and our local rebase. Then we alter
            # commits to modify their authors. Finally, we update the remote
            # tracking branch with this information.
            git_p4_commits = exec_out('git rev-list HEAD ^%s' % p4_cur_head)
            our_commits = exec_out('git rev-list %s ^%s' %
                                   (work_branch, p4_cur_head))
            our_idx = 0
            get_commit_log = lambda commit: exec_out(
                    # Note that we remove the first line (commit hash).
                    'git rev-list --pretty=%s%n%b -n 1 ' + commit)[1:]
            author = []
            if not git_p4_commits:
                logger.info("No new commit in git-branch")

            for p4_commit in git_p4_commits:
                # Get commit message log.
                p4_log = get_commit_log(p4_commit)
                # Remove text added by git-p4.
                assert p4_log[-1].startswith('[git-p4: depot-paths = ')
                p4_log = p4_log[:-1]
                # Also remove any trailing empty line.
                while p4_log and not p4_log[-1]:
                    p4_log = p4_log[:-1]
                # Attempt to find a matching commit in our commits.
                found = False
                while our_idx < len(our_commits):
                    our_commit = our_commits[our_idx]
                    our_log = get_commit_log(our_commit)
                    if p4_log == our_log:
                        # Found it!
                        found = True
                        break
                    # This must mean this commit has been skipped (can happen
                    # if someone committed to P4 an identical commit).
                    our_idx += 1
                if found:
                    # Obtain author information.
                    name, email = exec_out(
                            'git rev-list --pretty=%an%n%ae -n 1 ' +
                            our_commit)[1:3]
                    author.append((p4_commit, name, email))
                else:
                    # If we cannot find a matching commit this means we have
                    # reached P4-specific commits.
                    break
            logger.debug('Author information: %s' % author)
            # Now modify author names.
            for commit, name, email in author:
                logger.debug('Updating author of commit %s: %s / %s' %
                             (commit, name, email))
                exec_out(['git', 'filter-branch', '-f', '--env-filter', """\
an="$GIT_AUTHOR_NAME"
am="$GIT_AUTHOR_EMAIL"
if [ "$GIT_AUTHOR_EMAIL" = "%s" -a "$GIT_COMMIT" = "%s" ]
then
an="%s"
am="%s"
fi
export GIT_AUTHOR_NAME="$an"
export GIT_AUTHOR_EMAIL="$am"
""" % (p4_email, commit, name, email), 'HEAD', '^%s' % p4_cur_head])

            # It remains to update the reference to the remote tracking branch
            # in order to make it use the new names.
            exec_out('git update-ref refs/remotes/%s %s' %
                     (remote_p4_branch, 'HEAD'))

            # Now we can push the result.
            exec_out('git push %s %s:%s' %
                     (args.remote, args.p4_branch, args.p4_branch))
            # We also push to the branch that we merged, to ensure users do not
            # accidentally work on an outdated branch.
            exec_out('git push --force %s %s:%s' %
                     (args.remote, args.p4_branch, args.git_branch))
            logger.info('Successfully synchronized Git <-> P4 repositories')
            return 0

        else:
            logger.debug('Submit failed, resetting repo state')
            # Reset state of the repo.
            exec_out('git reset --hard %s' % p4_cur_head)
            # Verify that:
            #   1. The remote P4 branch has indeed been updated, and
            #   2. There is indeed a conflict when trying to rebase on
            #      top of its new head.
            # If this is not the case, there must be another problem.
            can_explain_failure = False
            new_remote_p4_head = exec_out(
                                'git rev-list %s -n 1' % remote_p4_branch)[0]
            if new_remote_p4_head != p4_cur_head:
                logger.debug('Attempting to rebase on top of remote P4 branch '
                             'to validate the conflict situation')
                exec_out('git checkout -b %s' % work_branch)
                exec_out('git reset --hard %s' % remo_branch)
                r_code = exec_code('git rebase %s' % remote_p4_branch)
                can_explain_failure = (r_code != 0)
            if can_explain_failure:
                # Update P4 branch and push to remote repository before
                # failing.
                logger.debug('Conflict situation validated: aborting')
                exec_out('git rebase --abort')
                exec_out('git checkout %s' % args.p4_branch)
                exec_out('git p4 rebase')
                exec_out('git p4 push %s %s:%s' %
                         (args.remote, args.p4_branch, args.p4_branch))
                logger.info('Unable to rebase branch on top of P4 head, '
                            'please rebase manually then try again')
                return 1
            else:
                # Rebase is possible: something else must be wrong.
                logger.warning(
                    'Submission failed unexpectedly.\n'
                    'The stdout output is:\n'
                    '%s\n\n'
                    'The stderr output is:\n'
                    '%s' % (stdout, stderr))
                raise RuntimeError(
                    '\'git p4 submit\' failed even though it seems possible to '
                    'rebase the submitted Git changes on top of the P4 branch')
    finally:
        os.chdir(cwd)
        if lock is not None and lock.locked:
            lock.release()

    assert False, 'This point should be unreachable'


if __name__ == '__main__':
    sys.exit(main())
