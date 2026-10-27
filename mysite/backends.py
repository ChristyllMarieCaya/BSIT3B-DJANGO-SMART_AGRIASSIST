from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper

class DatabaseWrapper(MySQLDatabaseWrapper):
    def check_database_version_supported(self):
        # Bypass the version check for MariaDB 10.4
        pass