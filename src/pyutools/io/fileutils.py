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
Miscellaneous file utility functions.
"""


__all__ = ['is_same_file']


import hashlib
import os


def is_same_file(f1, f2):
    """
    Check whether two files are similar.

    :param f1: Path to the first file to compare.

    :param f2: Path to the second file to compare.

    :return: True if and only if `f1` and `f2` have the exact same content.
    """
    assert os.path.isfile(f1) and os.path.isfile(f2)
    stats = map(os.stat, (f1, f2))
    if stats[0].st_size != stats[1].st_size:
        # If they have different sizes they cannot be the same.
        return False
    # Look at their md5 hash.
    return md5(f1) == md5(f2)


def md5(f_path):
    """
    Return md5 hash of the given file.

    :param f_path: Path to the file whose MD5 sum is sought.

    :return: MD5 hash of `f_path`.
    """
    hasher = hashlib.md5()
    f_in = open(f_path, 'rb')
    try:
        # Read file in chunks of 10 Mb.
        chunk_size = 10 * 1024 * 1024
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    finally:
        f_in.close()
    return hasher.hexdigest()
