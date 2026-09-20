import logging

from django.core.cache.backends.db import DatabaseCache
from django.db import DatabaseError

logger = logging.getLogger(__name__)


class ResilientDatabaseCache(DatabaseCache):
    """A database cache that fails *open* instead of taking the site down.

    The cache only backs rate limiting and OTP attempt counting. If its table
    is missing (a deploy that skipped `migrate`/`createcachetable`) or the
    database hiccups, an unhandled error here would turn every login into a
    500. Instead the operation is skipped and a loud error is logged, so
    logins keep working while operators fix it.
    """

    def _guard(self, operation, default, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DatabaseError as exc:
            logger.error(
                'Cache table %r unavailable during %s (%s). Rate limiting and OTP '
                'attempt limits are NOT being enforced. Run: '
                'python manage.py createcachetable',
                self._table, operation, exc,
            )
            return default

    def get_many(self, keys, version=None):
        return self._guard('get_many', {}, super().get_many, keys, version)

    def set(self, key, value, timeout=None, version=None):
        return self._guard('set', None, super().set, key, value, timeout, version)

    def add(self, key, value, timeout=None, version=None):
        return self._guard('add', False, super().add, key, value, timeout, version)

    def touch(self, key, timeout=None, version=None):
        return self._guard('touch', False, super().touch, key, timeout, version)

    def delete(self, key, version=None):
        return self._guard('delete', False, super().delete, key, version)

    def delete_many(self, keys, version=None):
        return self._guard('delete_many', None, super().delete_many, keys, version)

    def has_key(self, key, version=None):
        return self._guard('has_key', False, super().has_key, key, version)

    def clear(self):
        return self._guard('clear', None, super().clear)
