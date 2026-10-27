import copy
try:
    import pymysql
    pymysql.install_as_MySQLdb()
except ImportError:
    pass

# Python 3.14 compatibility patch for Django 5.0 BaseContext.__copy__
try:
    from django.template import context as django_context

    def _base_context_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    django_context.BaseContext.__copy__ = _base_context_copy
except Exception:
    pass
