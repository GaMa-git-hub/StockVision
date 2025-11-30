import mysql.connector
import config

def get_db_connection():
    connection = mysql.connector.connect(
        host = config.MYSQL_HOST,
        user = config.MYSQL_USER,
        password = config.MYSQL_PASSWORD,
        database = config.MYSQL_DB
    )
    return connection