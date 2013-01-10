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
This script is used to flatten (= linearize) the history of a Git repository.

It relies heavily on Git's "rebase" mechanism to attempt to rebase parallel
branches on top of each other. When this is not possible due to conflicts, an
"aggregated" commit is automatically generated to represent the merge (and the
descriptions of all commits being aggregated are saved in this commit's
description).
"""


import argparse
import logging
import os
import shutil
import sys


import pyutools
from pyutools.misc import util
from pyutools.misc.util import execute


def analyze_branches(logger, clean_up=False, clean_up_idx_0=True):
    """
    Perform analysis of branches and potentially deletes some.

    :param logger: Logger object.

    :param clean_up_idx_0: Whether to also delete the work branch with index 0
    (which typically contains the final output). Has no effect when `clean_up`
    is False (in which case we do not delete branch).

    :return: The current branch (None if not currently on a branch).
    """
    branches = exec_out('git branch')
    current_branch = None
    for branch in branches:
        is_current = branch.startswith('*')
        if is_current:
            if 'no branch' in branch:
                raise RuntimeError(
                        'You are not currently on a branch. You need to be '
                        'on a branch to run this script.')
            branch = branch[1:]
            current_branch = branch.strip()
        assert 'no branch' not in branch
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
                exec_out('git branch -D %s' % branch)
            else:
                raise RuntimeError(
                        'Found branch \'%s\' that is probably a leftover '
                        'from a previous flattening attempt. Please run this '
                        'script with the --clean option to delete it, or '
                        'do it manually.' % branch)
    return current_branch


def exec_out(cmd):
    """
    Return the stdout output of command 'cmd'. Raise exception on failure.

    By failure, we mean when the command's return code is non-zero.
    """
    return execute(cmd, must_succeed=True)


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

    Another way to improve this function would be to have a smarter algorithm
    to choose which branch to follow when building the flattened history.
    Currently we use git's so-called "topological order", which seems to favor
    the master branch in a typical "merge to master" scenario, but it may not
    necessarily be guaranteed, nor the best way to go. See this discussion:
        http://www.kerneltrap.org/mailarchive/git/2006/2/13/200897/thread

    Before exiting, this function always restores the original branch found
    in `state.origin` (even if an exception is raised).

    :return: The name of the flattened branch.
    """
    # Wrapper around `_flatten` to restore the original branch.
    try:
        return _flatten(start, end, state)
    except:
        # Throw away local changes.
        exec_out('git reset --hard %s' % state.origin)
        raise
    finally:
        # Restore original branch.
        exec_out('git checkout %s' % state.origin)


def _flatten(start, end, state):
    """
    Actual implementation of `flatten`.
    """
    logger = state.logger

    # Helper function to create a new branch with a unique name.
    def make_new_branch(commit):
        logger.debug('Creating new branch #%s' % state.branch_idx)
        name = 'flatten_tmp_branch_%s' % state.branch_idx
        exec_out('git checkout -b %s %s' % (name, commit))
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
        assert execute('git diff --quiet %s' % end) == 0
        logger.debug('Rebase successful!')
        return base_branch

    logger.debug('Rebase failure -- rolling back')
    exec_out('git rebase --abort')

    # Get parent/child relationships.
    # The `data` dictionary maps a commit hash to a `Storage` instance holding:
    #   - the commit hash
    #   - its parents
    #   - its children
    logger.debug('Analyzing parent/child relationships')
    data = dict()
    commits = exec_out('git rev-list --parents --reverse --topo-order %s' %
                       end)
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
            logger.debug('Cherry-picking %s' % child.hash)
            exec_out('git cherry-pick --allow-empty %s' % child.hash)
            # Ensure end result is as expected.
            assert execute('git diff --quiet %s' % child.hash) == 0
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
            exec_out('git branch -D %s' % rebase_branch)
            logger.debug('Attempting to rebase %s on top of %s to yield %s' %
                         (other.hash, head.hash, child.hash))
            exec_out('git checkout -b %s %s' % (rebase_branch, other.hash))
            r_code, stdout, stderr = execute(
                    'git rebase %s' % head.hash, return_stdout=True,
                    return_stderr=True)
            if r_code == 0:
                logger.debug('Rebase successful')
                # Apply resulting commits on top of current head of the work
                # branch.
                # First we obtain these commits.
                rebase_head = get_current_head()
                to_apply = exec_out('git rev-list --reverse HEAD ^%s' %
                                    head.hash)
                exec_out('git checkout %s' % work_branch)
                for commit in to_apply:
                    exec_out('git cherry-pick %s' % commit)
                # It can happen that the end result is not as expected. This
                # is the case when 'rebase' and 'merge' both succeed without
                # conflict and yet give different results. Another situation is
                # when the merge commit contains some manual changes.
                has_diff = execute('git diff --quiet %s' % child.hash)
                if has_diff != 0:
                    logger.debug(
                        'Rebase + cherry-pick did not yield the expected '
                        'result: it yielded %s while the expected result was '
                        '%s (the rebased branch can be found at %s)' %
                        (get_current_head(), child.hash, rebase_head))
                    logger.debug('Adding a new commit to fix this situation')
                    # In such a situation, we add a new commit to fix it.
                    # First set working directory to its expected state.
                    exec_out('git checkout %s .' % child.hash)
                    # Then commit the change.
                    exec_out(['git', 'commit', '-a', '-m',
                             'Automated recovery from unexpected rebase '
                             'result'])
                    # Now there should be no more diff.
                    if execute('git diff --quiet %s' % child.hash) != 0:
                        raise RuntimeError(
                            'There remain changes after attempted recovery. '
                            'The current head is %s, and differs from %s' %
                            (get_current_head(), child.hash))

            else:
                logger.debug('Rebase failed -- rolling back')
                exec_out('git rebase --abort')
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
                exec_out('git rebase -X theirs %s' % head.hash)
                patch_info = exec_out('git log %s..HEAD' % head.hash)
                exec_out('git checkout %s' % work_branch)
                # Instead build a patch with the diff.
                logger.debug('Building patch')
                diff = exec_out('git diff --full-index --binary %s..%s' %
                               (head.hash, child.hash))
                diff_f_name = '.tmp.flatten_patch'
                diff_file = open(diff_f_name, 'w')
                try:
                    # Note the last empty line to ensure binary diffs are not
                    # corrupted.
                    diff_file.write('\n'.join(diff) + '\n\n')
                finally:
                    diff_file.close()
                patch_success = False
                try:
                    # Apply the patch.
                    if diff:
                        logger.debug('Applying patch')
                        r_code = execute('git apply --check %s' % diff_f_name)
                    else:
                        logger.debug('Patch is empty: skipping it')
                        r_code = 0
                    head_before = get_current_head()
                    if r_code != 0:
                        raise RuntimeError(
                            'Merge patch cannot be applied on top of %s' %
                            head_before)
                    if diff:
                        exec_out('git apply --index %s' % diff_f_name)
                        logger.debug(
                                   'Patch successfully applied, committing it')
                    else:
                        logger.debug('Committing an empty commit')
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
                        exec_out('git commit --allow-empty -F %s' %
                                commit_f_name)
                    finally:
                        os.remove(commit_f_name)
                    # Ensure the end result is the one expected.
                    has_diff = execute('git diff --quiet %s' % child.hash)
                    if has_diff != 0:
                        # The patch did not yield the expected result.
                        raise RuntimeError(
                            'Patch was applied on %s but did not work as '
                            'expected.\n'
                            'It yielded %s while the expected result was %s' %
                            (head_before, get_current_head(), child.hash))

                    patch_success = True
                finally:
                    if patch_success:
                        os.remove(diff_f_name)
        # Update current head.
        head = child
       
    return work_branch


def get_current_head():
    """
    Return hash of the current HEAD commit.
    """
    return exec_out('git rev-list HEAD -n 1')[0]


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
                'directory of a Git repository, while on the branch to be '
                'linearized (this branch will not be modified in the '
                'process).'))
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
    if exec_out('git status --porcelain'):
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
    flattened_branch = flatten(root, get_current_head(), state)
    # Save the result and clean up temporary work branch.
    if flattened_branch is not None:
        exec_out('git checkout -b flatten_tmp_branch_0 %s' %
                flattened_branch)
        analyze_branches(logger, clean_up=True, clean_up_idx_0=False)

    return 0


if __name__ == '__main__':
    sys.exit(main())
