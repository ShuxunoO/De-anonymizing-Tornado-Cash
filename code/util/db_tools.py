"""
@file db_tools.py
@brief Database utility functions for PostgreSQL operations.

@details
Provides a set of helper functions for connecting to PostgreSQL database
and executing queries with proper error handling and SQL injection prevention.
"""
import psycopg2


DB_HOST = 'xxx'
DB_PORT = 5432
DB_NAME = 'xxx'
DB_USER = 'xxx'
DB_PASSWORD = 'xxx'


def connect_db():
    """
    @brief Establishes a connection to the PostgreSQL database.
    @return Connection object on success, None on failure.
    """
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        print(f"[Error] Database connection failed: {e}")
        return None


def execute_query(conn, sql):
    """
    @brief Executes a SQL query and returns all results.
    @param conn Database connection object.
    @param sql SQL query string.
    @return List of result rows, empty list on failure.
    """
    if conn is None:
        print("[Error] Connection is None")
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        cursor.close()
        return result
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[Error] Execute query failed: {e}")
        return []


def execute_query_params(conn, sql, params=None):
    """
    @brief Executes a parameterized SQL query to prevent SQL injection.
    @param conn Database connection object.
    @param sql SQL query string using %s as placeholders.
    @param params Tuple or list of parameters, defaults to None.
    @return List of result rows, empty list on failure.
    """
    if conn is None:
        print("[Error] Connection is None")
        return []
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        result = cursor.fetchall()
        cursor.close()
        return result
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[Error] Execute query failed: {e}")
        return []


def execute_update(conn, sql, params=None, auto_commit=True):
    """
    @brief Executes a SQL update statement (INSERT/UPDATE/DELETE).
    @param conn Database connection object.
    @param sql SQL update statement using %s as placeholders.
    @param params Tuple or list of parameters, defaults to None.
    @param auto_commit Whether to auto-commit the transaction, defaults to True.
    @return Number of affected rows, -1 on failure.
    """
    if conn is None:
        print("[Error] Connection is None")
        return -1
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rowcount = cursor.rowcount
        if auto_commit:
            conn.commit()
        cursor.close()
        return rowcount
    except psycopg2.Error as e:
        conn.rollback()
        print(f"[Error] Execute update failed: {e}")
        return -1
