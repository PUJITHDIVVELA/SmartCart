import sqlite3
import os
import config

def init_db():
    db_path = getattr(config, 'DB_PATH', os.path.join(os.path.dirname(__file__), getattr(config, 'DB_NAME', 'smartcart.db')))
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if os.path.exists(schema_path):
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_script = f.read()
        cursor.executescript(schema_script)
    
    conn.commit()
    conn.close()
    print(f"SQLite database successfully initialized at {db_path}")

if __name__ == '__main__':
    init_db()
