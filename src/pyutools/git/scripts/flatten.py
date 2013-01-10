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
from pyutools.misc import util
from pyutools.misc.util import execute


def my_exec(cmd):
    return execute(cmd, must_succeed=True)


def analyze_branches(logger, clean_up=False, clean_up_idx_0=True):
    """
    Perform analysis of branches and potentially deletes some.

    :param logger: Logger object.

    :param clean_up_idx_0: Whether to also delete the work branch with index 0
    (which typically contains the final output). Has no effect when `clean_up`
    is False (in which case we do not delete branch).

    :return: The current branch (None if not currently on a branch).
    """
    branches = my_exec('git branch')
    current_branch = None
    for branch in branches:
        is_current = branch.startswith('*')
        if is_current:
            branch = branch[1:]
            current_branch = branch.strip()
        branch = branch.strip()
        template = 'flatten_tmp_branch_'
        if branch.startswith(template):
            # This is a temporary branch previously created by this script.
            branch_idx = int(branch[len(template):])
            if clean_up:
                if branch_idx == 0 and not clean_up_idx_0:
                    # Keep branch with index 0 if we asked for it.
                    continue
                if is_current:
                    raise RuntimeError(
                            'You are currently on branch \'%s\' which needs '
                            'to be deleted. Please first move to another '
                            'branch.' % branch)
                logger.debug('Deleting old temporary branch: %s' % branch)
                my_exec('git branch -D %s' % branch)
            else:
                raise RuntimeError(
                        'Found branch \'%s\' that is probably a leftover '
                        'from a previous flattening attempt. Please run this '
                        'script with the --clean option to delete it, or '
                        'do it manually.')
    return current_branch


def flatten(start, end, state):
    """
    Flatten from commit `start` to commit `end`.

    This was meant to be a recursive function, whose state is a storage object
    holding:
        - logger: the current logger
        - branch_idx: the current maximum temporary branch index
        - origin: name of the original branch we want to get back to after
          flattening

    However, the current implementation is not recursive, to keep things
    simple. Making it recursive would be useful to avoid situations where a
    huge branch may be collapsed to a single commit due to a conflict caused
    by a minor side-branch, which could have been resolved by recursively
    linearizing this huge branch. Such "recursivization" is left for future
    work.

    Before exiting, this function always restores the original branch found
    in `state.origin` (even if an exception is raised).

    :return: The name of the flattened branch.
    """
    # Wrapper around `_flatten` to restore the original branch.
    try:
        return _flatten(start, end, state)
    except:
        # Throw away local changes.
        my_exec('git reset --hard %s' % state.origin)
        raise
    finally:
        # Restore original branch.
        my_exec('git checkout %s' % state.origin)


def _flatten(start, end, state):
    """
    Actual implementation of `flatten`.
    """
    logger = state.logger

    # Helper function to create a new branch with a unique name.
    def make_new_branch(commit):
        name = 'flatten_tmp_branch_%s' % state.branch_idx
        execute('git checkout -b %s %s' % (name, commit),
                must_succeed=True)
        state.branch_idx += 1
        return name

    # Work in a new temporary branch.
    base_branch = make_new_branch(end)

    # First attempt: simple rebase. If it works then we are good to go.
    logger.debug('Attempting a rebase on top of %s' % start)
    r_code, stdout, stderr = execute('git rebase %s' % start,
                                     return_stdout=True,
                                     return_stderr=True)
    if r_code == 0:
        logger.debug('Rebase successful!')
        return base_branch

    logger.debug('Rebase failure -- rolling back')
    execute('git rebase --abort', must_succeed=True)

    # Get parent/child relationships.
    # The `data` dictionary maps a commit hash to a `Storage` instance holding:
    #   - the commit hash
    #   - its parents
    #   - its children
    logger.debug('Analyzing parent/child relationships')
    data = dict()
    commits = execute('git rev-list --parents --reverse --topo-order %s' % end,
                      must_succeed=True)
    for commit_info in commits:
        tokens = commit_info.split(' ')
        commit = tokens[0]
        parents = tokens[1:]
        commit_info = util.Storage(
                hash=commit,
                parents=[data[h] for h in parents],
                children=[])
        for p in commit_info.parents:
            assert commit_info not in p.children
            p.children.append(commit_info)
        assert commit not in data
        data[commit] = commit_info

    # TODO Explain somewhere why not recursive.

    # In this branch we will perform temporary rebases.
    rebase_branch = make_new_branch(end)

    # Need another work branch for the final result.
    work_branch = make_new_branch(start)

    # The algorithm works as follows:
    #   * We apply commits that can be applied on top of each other, until
    #     we find a merge commit (>= 2 parents).
    #   * When a merge commit is found, we attempt to rebase the unprocessed
    #     child on top of current head:
    #       - If this works, the resulting commits are cherry-picked into
    #         the work branch.
    #       - If this fails, then we manually create a patch that represents
    #         the diff from the merge commit, and apply this patch instead.

    head = data[start]

    while head.children:
        child = head.children[0]
        assert child.parents
        if len(child.parents) == 1:
            # This is not a merge commit: apply it.
            execute('git cherry-pick %s' % child.hash, must_succeed=True)
        else:
            if len(child.parents) > 2:
                raise NotImplementedError(
                        'Found a merge commit with %s parents, but the '
                        'current implementation only supports two parents.' %
                        len(child.parents))
            # Get the other parent of this child.
            if head is child.parents[0]:
                other = child.parents[1]
            else:
                assert head is child.parents[1]
                other = child.parents[0]
            # Attempt to rebase the other parent on top of the current head.
            # We do this in a new branch whose head is the other parent.
            execute('git branch -D %s' % rebase_branch, must_succeed=True)
            logger.debug('Attempting to rebase %s on top of %s' %
                         (other.hash, head.hash))
            execute('git checkout -b %s %s' % (rebase_branch, other.hash),
                    must_succeed=True)
            r_code, stdout, stderr = execute(
                    'git rebase %s' % head.hash, return_stdout=True,
                    return_stderr=True)
            if r_code == 0:
                logger.debug('Rebase successful')
                # Apply resulting commits on top of current head of the work
                # branch.
                # First we obtain these commits.
                to_apply = execute('git rev-list --reverse HEAD ^%s' %
                                   head.hash, must_succeed=True)
                execute('git checkout %s' % work_branch, must_succeed=True)
                for commit in to_apply:
                    execute('git cherry-pick %s' % commit, must_succeed=True)
            else:
                logger.debug('Rebase failed -- rolling back')
                my_exec('git rebase --abort')
                # We re-run a dummy rebase that solves conflicts in a very
                # stupid way (always keeping the rebased branch's commits),
                # so as to be able to gather the list of commits being
                # considered. We will combine their commit notes in the
                # patch being committed.
                # TODO This can probably be obtained in a simpler way through
                # a command of the form ``git -rev-list --left-right A...B``
                # but for now we are keeping this version since it seems to
                # work (however the current version provides useless commit
                # hashes in the logs).
                logger.debug('Dummy rebase to gather list of commits')
                my_exec('git rebase -X theirs %s' % head.hash)
                patch_info = my_exec('git log %s..HEAD' % head.hash)
                my_exec('git checkout %s' % work_branch)
                # Instead build a patch with the diff.
                logger.debug('Building patch')
                diff = my_exec('git diff --full-index --binary %s %s' %
                               (head.hash, child.hash))
                diff_f_name = '.tmp.flatten_patch'
                diff_file = open(diff_f_name, 'w')
                try:
                    diff_file.write('\n'.join(diff) + '\n')
                finally:
                    diff_file.close()
                try:
                    # Apply the patch.
                    logger.debug('Applying patch')
                    r_code = execute('git apply --check %s' % diff_f_name)
                    if r_code != 0:
                        raise RuntimeError('Merge patch cannot be applied')
                    my_exec('git apply --index %s' % diff_f_name)
                    logger.debug('Patch successfully applied, committing it')
                    commit_f_name = '.tmp.flatten_msg'
                    commit_file = open(commit_f_name, 'w')
                    try:
                        commit_file.write(
                            'Automatic patch built from combined commits\n'
                            '\n'
                            'This patch is made of the following commits:\n'
                            '\n' +
                            '\n'.join(patch_info) + '\n')
                    finally:
                        commit_file.close()
                    try:
                        my_exec('git commit -F %s' % commit_f_name)
                    finally:
                        os.remove(commit_f_name)
                finally:
                    os.remove(diff_f_name)
        # Update current head.
        head = child
       
    return work_branch


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
    parser.add_argument('--verbosity',
                        help='Verbosity level (0 to 2, default 1)',
                        type=int, default=1)
    parser.add_argument('--log',
                        help='Output to this log file instead of stdout')
    parser.add_argument('--clean', action='store_true',
                        help='Automatically delete temporary branches created '
                             'by a previous call to this script')

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

    # Ensure the repository is in a clean state.
    if execute('git status --porcelain', must_succeed=True):
        raise RuntimeError(
                'The \'git status\' command reports that the repository is '
                'not currently in a clean state. You need to clean it up '
                'before you can use this script.')
    logger.debug('Current repository is clean')

    # Ensure there is no leftover branch from a previous flattening attempt,
    # cleaning them as necessary.
    current_branch = analyze_branches(logger, clean_up=args.clean)
    assert current_branch is not None

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

    # Flatten from first commit to HEAD.
    state = util.Storage(logger=logger, branch_idx=1, origin=current_branch)
    flattened_branch = flatten(root, 'HEAD', state)
    # Save the result and clean up temporary work branch.
    if flattened_branch is not None:
        my_exec('git checkout -b flatten_tmp_branch_0 %s' %
                flattened_branch)
        analyze_branches(logger, clean_up=True, clean_up_idx_0=False)

    return 0


if __name__ == '__main__':
    sys.exit(main())
