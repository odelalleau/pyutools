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
A debug Theano Op.
"""

import theano
from theano import tensor


class DebugOp(theano.gof.Op):
    """
    An Op that can be used to monitor computations in a Theano graph.

    Its default behavior is to behave like an Identity Op.
    """

    def __init__(self, condition=None, action=None):
        """
        Constructor.

        :param condition: A function that, when evaluated on this Op's input,
        should return a boolean. If its returned value is True, then the
        `action` function is run. Default behavior is to always return True.

        :param action: The function to execute when `condition` is True. It is
        executed with the Op's input as input. Default behavior is to do
        nothing.
        """
        self.condition = condition
        self.action = action

    def __eq__(self, other):
        return (type(self) == type(other) and
                self.condition is other.condition and
                self.action is other.action)

    def __hash__(self):
        return hash(type(self))

    def make_node(self, x):
        x = tensor.as_tensor_variable(x)
        return theano.Apply(self, inputs=[x], outputs=[x.type()])

    def perform(self, node, inputs, outputs):
        x = inputs[0]
        x = x.copy()
        if ((self.condition is None or self.condition(x)) and
            self.action is not None):
            # Run the action.
            self.action(x)
        outputs[0][0] = x

    def grad(self, inputs, output_gradients):
        return output_gradients
