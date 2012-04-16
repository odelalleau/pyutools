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
A debug Theano mode.
"""

import theano


class DebugMode(theano.compile.mode.Mode):
    """
    A mode that can be used to debug function execution.

    Its default behavior is to behave like the 'FAST_RUN' mode.
    """

    def __init__(self, pre_func=None, post_func=None):
        """
        Constructor.

        :param pre_func: A function to call before executing a thunk, with
        arguments:
            - the thunk index
            - the Apply node
            - the thunk to be called

        :param post_func: A function to call after executing a thunk, with same
        arguments as `pre_func`.
        """
        self.pre_func = pre_func
        self.post_func = post_func
        wrap_linker = theano.gof.WrapLinkerMany([theano.gof.OpWiseCLinker()],
                                                [self.eval])
        super(DebugMode, self).__init__(wrap_linker, optimizer='fast_run')

    def eval(self, i, node, fn):
        """
        The method that calls the the thunk `fn`.
        """
        node.debug_thunk = fn
        if self.pre_func is not None:
            self.pre_func(i, node, fn)
        fn()
        if self.post_func is not None:
            self.post_func(i, node, fn)
