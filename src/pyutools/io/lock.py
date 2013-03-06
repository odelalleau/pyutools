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


__all__ = ['Lock']


import datetime
import os
import threading
import time

try:
    import sqlite3
except ImportError:
    # Python 2.4 compatibility.
    from pysqlite2 import dbapi2 as sqlite3

# Dummy logger. Overwrite it if you want to better manage logs.
class DummyLogger(object):
    def __getattr__(self, method_name):
        def rval(msg):
            return
            print ('%s\t%s: %s' % (
                   datetime.datetime.fromtimestamp(time.time()),
                   method_name.upper(), msg))
        return rval

logger = DummyLogger()


# This is the maximum number of locks that may be used simultaneously in the
# same directory. Default is one million.
MAX_N_LOCKS = 1000000


class Lock(object):
    
    """
    Lock associated to a directory on the filesystem.

    This lock can be used to manage inter-process synchronization. It is also
    thread-safe and may be used similary to threading.Lock() (although the
    overhead is higher, so there is no reason to use it if there is a single
    process).

    The lock is associated to a location on the filesystem, which must be a
    directory (that may or may not exist already).

    Since it uses sqlite as the back-end, this class is not NFS safe.
    """

    def __init__(self, dirname, timeout=10, refresh=None, wait=1,
                 err_if_timeout=False):
        """
        Constructor.

        :param dirname: The directory this lock is associated to. It does not
        need to exist already.

        :param timeout: If a lock has not been refreshed in the last `timeout`
        seconds, then it is automatically overridden. Setting this value to -1
        means no timeout (may block indefinitely).

        :param refresh: How often the lock should be refreshed, in seconds
        (this is done automatically in a different thread). The default (None)
        means we use `timeout` / 2. Setting this value to -1 means no refresh.
        If `timeout` is -1 and `refresh` is None, then it behaves as if
        `refresh` was -1.

        :param wait: If the lock cannot be obtained immediately when calling
        `acquire()`, wait this amount of time (in seconds) before trying again.

        :param err_if_timeout: If we time out, by default we take the lock.
        If True, we will raise a LockError exception.
        """
        # Parse arguments.
        self.dirname = dirname
        self.timeout = timeout
        self.wait = wait
        self.err_if_timeout = err_if_timeout
        if refresh is None:
            if self.timeout < 0:
                self.refresh = -1
            else:
                self.refresh = self.timeout / 2.
        else:
            self.refresh = refresh
        # Lock for thread-safety.
        self.thread_lock = threading.Lock()
        # Connection to sqlite database used to handle the main lock.
        self.db_conn = None
        # Cursor of the database.
        self.cursor = None
        # Current lock status.
        self.locked = False
        # Initialize the lock files.
        self._create_directory()
        self._init_db()

    def __del__(self):
        """
        Destructor.
        """
        self.shutdown()

    def _create_directory(self):
        """
        Create directory `self.dirname`.
        """
        if os.path.exists(self.dirname) and not os.path.isdir(self.dirname):
            raise ValueError('Not a directory: %s' % self.dirname)
        start = time.time()
        while True:
            if os.path.exists(self.dirname):
                break
            else:
                try:
                    os.makedirs(self.dirname)
                except Exception:
                    # May fail due to multiple processes attempting to create
                    # this directory at the same time.
                    # But if it has been more than 10s, then something must be
                    # wrong!
                    if time.time() - start > 10:
                        raise
                else:
                    break

    def _init_db(self):
        """
        Initialize connection to sqlite database.
        """
        self.db_name = os.path.join(self.dirname, 'lock.sqlite')
        self.db_conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.cursor = self.db_conn.cursor()
        # This table contains the id of the current holder of the lock.
        query = ('CREATE TABLE IF NOT EXISTS lock_info '
                 '(key INTEGER PRIMARY KEY, lock_id INTEGER, '
                 'lock_date DOUBLE);')
        self.cursor.execute(query)
        # This table is used to obtain a unique lock ID for each lock
        # associated to this directory.
        query = ('CREATE TABLE IF NOT EXISTS counter ('
                 'lock_id INTEGER PRIMARY KEY AUTOINCREMENT, '
                 'dummy INTEGER);')
        self.cursor.execute(query)
        self.db_conn.commit()
        def get_lock_id():
            # Obtain my lock ID.
            query = ('INSERT INTO counter (dummy) VALUES (0);')
            self.cursor.execute(query)
            self.db_conn.commit()
            self.lock_id = self.cursor.lastrowid
            # Note that we delete everything, to clean-up potential leftovers
            # (due e.g. to crashes).
            query = 'DELETE FROM counter;'
            self.cursor.execute(query)
            self.db_conn.commit()
        get_lock_id()
        # Ensure IDs are recycled. We use modulo so that if the reset fails for
        # some reason, it will still trigger later on.
        if self.lock_id % MAX_N_LOCKS == 0:
            # Reset the lock ID counter.
            query = 'DELETE FROM sqlite_sequence WHERE name = \'counter\';'
            self.cursor.execute(query)
            self.db_conn.commit()
            get_lock_id()

    def acquire(self):
        """
        Obtain lock.
        """
        # Ensure only one thread is attempting to get the lock in this process.
        self.thread_lock.acquire()
        assert not self.locked
        while True:
            # Read identity of current lock holder.
            query = 'SELECT lock_id, lock_date FROM lock_info WHERE key = 1'
            self.cursor.execute(query)
            self.db_conn.commit()
            result = self.cursor.fetchall()
            if result:
                # Note that for some reason (sqlite bug?), if the INSERT below
                # failed, the next SELECT returns two rows instead of one.
                # These rows are duplicated.
                assert len(result) in (1, 2), str(result)
                lock_id, lock_date = result[0]
                age = time.time() - lock_date
                # Someone is already holding the lock.
                logger.debug('Lock held by %s for %s seconds (I am %s)' %
                             (lock_id, age, self.lock_id))
                # Note that we also delete locks that are more than one hour
                # into the future, because it means they must be bugged
                # somehow.
                if self.timeout >= 0 and (age > self.timeout or -age > 3600):
                    if self.err_if_timeout:
                        raise LockError("Timeout expired while acquiring a "
                                        "lock (age = %fs)" % age)
                    # Delete outdated lock.
                    # Note that we specify the lock ID, because someone else
                    # may actually delete and create a new lock at the same
                    # time.
                    logger.debug('Overriding lock!')
                    query = ('DELETE FROM lock_info WHERE key = 1 AND '
                             'lock_id = %s' % lock_id)
                    self.cursor.execute(query)
                    self.db_conn.commit()
                else:
                    # Just wait for now.
                    time.sleep(self.wait)
                    continue
            # Attempt to grab lock.
            query = ('INSERT INTO lock_info (key, lock_id, lock_date) VALUES '
                     '(1, %s, %s)'% (self.lock_id, time.time()))
            try:
                self.cursor.execute(query)
                self.db_conn.commit()
            except Exception, e:
                # This will happen if someone else grabbed the lock first.
                logger.debug('Failed to grab lock (I am %s): %s' %
                             (self.lock_id, e))
                time.sleep(self.wait)
                continue
            break
        logger.debug('Successfully obtained lock (I am %s)' % self.lock_id)
        if self.refresh >= 0:
            # Register this lock for refresh.
            refresh_lock.register(self, self.db_conn, self.refresh)
        self.locked = True

    def release(self):
        """
        Release lock.

        A LockError exception is raised if the lock is not locked.
        """
        try:
            if not self.locked:
                raise LockError('Lock is already unlocked')
            # Unregister from automatic refresh.
            if self.refresh >= 0:
                refresh_lock.unregister(self)
            # Delete lock entry in sqlite table.
            query = ('DELETE FROM lock_info WHERE key = 1 AND '
                     'lock_id = %s' % self.lock_id)
            self.cursor.execute(query)
            self.db_conn.commit()
            logger.debug('Successfully released lock (I am %s)' % self.lock_id)
        finally:
            self.locked = False
            try:
                self.thread_lock.release()
            except threading.ThreadError:
                # Will happen if it was already unlocked.
                pass

    def shutdown(self):
        """
        Release lock and close all ressources.

        The lock may not be used anymore after this method has been called.
        """
        try:
            self.release()
        except LockError:
            # Will happen if already unlocked.
            pass
        # Acquire thread lock to be thread-safe.
        self.thread_lock.acquire()
        try:
            if self.cursor is not None:
                self.cursor.close()
                self.cursor = None
            if self.db_conn is not None:
                self.db_conn.close()
                self.db_conn = None
        finally:
            self.thread_lock.release()


class RefreshLock(object):

    """
    Object responsible for refreshing locks.

    Whenever a lock needs to be refreshed, the refreshing thread is started if
    it is not running already.
    """

    def __init__(self):
        self.thread_lock = threading.Lock()
        self.refresh_thread = None

    def register(self, lock, db_conn, refresh):
        """
        Register a new lock for refresh.

        :param lock: The `Lock` instance to register.

        :param db_conn: Connection to the sqlite database.

        :param refresh: How often it should be refreshed (in seconds).
        """
        self.thread_lock.acquire()
        try:
            while True:
                if self.refresh_thread is None:
                    self.refresh_thread = RefreshThread()
                self.refresh_thread.register(lock, db_conn, refresh)
                if self.refresh_thread.started:
                    if self.refresh_thread.stopped:
                        # Thread is over already: need to start a new one.
                        logger.debug('Will need to create new thread')
                        self.refresh_thread = None
                        continue
                    logger.debug('Re-using existing refresh thread')
                    break
                else:
                    # Start it.
                    logger.debug('Starting new refresh thread')
                    self.refresh_thread.event.clear()
                    self.refresh_thread.start()
                    break
        finally:
            self.thread_lock.release()

    def unregister(self, lock):
        """
        Unregister a lock.
        """
        self.thread_lock.acquire()
        try:
            self.refresh_thread.unregister(lock)
        finally:
            self.thread_lock.release()


class RefreshThread(threading.Thread):

    """
    The main thread responsible for refreshing locks.
    """

    def __init__(self):
        # Dictionary of locks to manage.
        # The key is the Python memory address of a `Lock` instance.
        self.locks = {}
        self.thread_lock = threading.Lock()
        # Indicates something new happened (registration or unregistration).
        self.event = threading.Event()
        self.started = False
        self.stopped = False
        threading.Thread.__init__(self)

    def register(self, lock, db_conn, refresh):
        """
        Register a new lock for rerfresh.

        See `RefreshLock.register` for more information.
        """
        self.thread_lock.acquire()
        try:
            obj_id = id(lock)
            if obj_id in self.locks:
                # This should not happen, but we close existing cursor if
                # needed.
                logger.warning('This Lock memory address already exists!')
                lock_info = self.locks[obj_id]
                cursor = self.locks[obj_id][2]
                try:
                    cursor.close()
                except Exception:
                    pass
            self.locks[obj_id] = [lock, db_conn, db_conn.cursor(),
                                  refresh, time.time() + refresh]
            logger.debug('Event: registered new lock: %s' % lock.lock_id)
            self.event.set()
        finally:
            self.thread_lock.release()

    def unregister(self, lock):
        """
        Unregister a lock.
        """
        self.thread_lock.acquire()
        try:
            lock, db_conn, cursor, refresh, next_refresh = self.locks[id(lock)]
            try:
                cursor.close()
            except Exception:
                logger.warning('Exception when trying to close cursor')
            del self.locks[id(lock)]
            logger.debug('Event: unregistered a lock')
            self.event.set()
        finally:
            self.thread_lock.release()

    def run(self):
        self.started = True
        while True:
            # Find next lock to refresh.
            self.thread_lock.acquire()
            try:
                if not self.locks:
                    self.stopped = True
                    break
                next_lock_time = None
                next_lock_info = None
                for k, v in self.locks.iteritems():
                    if next_lock_time is None or v[-1] < next_lock_time:
                        next_lock_time = v[-1]
                        next_lock_info = v
                assert next_lock_info is not None
                wait_time = max(0, next_lock_info[-1] - time.time())
            finally:
                self.thread_lock.release()
            # Wait for this lock to be ready to be refreshed.
            logger.debug('Waiting for: %s seconds' % wait_time)
            self.event.wait(wait_time)
            # Perform the refresh.
            self.thread_lock.acquire()
            try:
                if self.event.isSet():
                    # If something happened, we may need to revise our
                    # schedule.
                    self.event.clear()
                    logger.debug('New event!')
                    continue
                lock, db_conn, cursor, refresh, next_refresh = next_lock_info
                if id(lock) not in self.locks:
                    # Must have been unregistered already.
                    continue
                now = time.time()
                query = ('UPDATE lock_info SET lock_date = %s '
                         'WHERE key = 1 AND lock_id = %s' %
                         (now, lock.lock_id))
                cursor.execute(query)
                db_conn.commit()
                # Update information for next refresh of this lock.
                next_lock_info[-1] = now + refresh
                logger.debug('Refreshed lock: %s' % lock.lock_id)
            finally:
                self.thread_lock.release()


class LockError(Exception):
    """
    Base class for Lock exceptions.
    """


# Singleton.
refresh_lock = RefreshLock()
