"""Management command to create database if it doesn't exist"""
import psycopg2
from psycopg2 import sql
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Creates the PostgreSQL database if it does not exist'

    def handle(self, *args, **options):
        db_settings = settings.DATABASES['default']
        db_name = db_settings['NAME']
        db_user = db_settings['USER']
        db_password = db_settings['PASSWORD']
        db_host = db_settings['HOST']
        db_port = db_settings['PORT']

        # Connect to PostgreSQL server (not specific database)
        try:
            conn = psycopg2.connect(
                dbname='postgres',
                user=db_user,
                password=db_password,
                host=db_host,
                port=db_port
            )
            conn.autocommit = True
            cursor = conn.cursor()

            # Check if database exists
            cursor.execute(
                "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
                (db_name,)
            )
            exists = cursor.fetchone()

            if not exists:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
                )
                self.stdout.write(self.style.SUCCESS(f'Database "{db_name}" created successfully'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Database "{db_name}" already exists'))

            cursor.close()
            conn.close()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating database: {e}'))
