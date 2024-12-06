#!/bin/sh

if [ "$DATABASE" = "postgres" ] && [ "$FLASK_DEBUG" = "0" ]
then
    echo "Waiting for postgres..."

    while ! nc -z $SQL_HOST $SQL_PORT; do
      sleep 0.1
    done

    echo "PostgresSQL started"
fi


if [ "$FLASK_DEBUG" = "1" ]
then
    echo "Creating the database tables..."
    python manage.py create_db
    echo "Tables created"
fi

#python manage.py fill_db

exec "$@"