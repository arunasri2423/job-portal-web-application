import sqlite3

DB_PATH = "job_portal.db"

def delete_admin_user():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Delete user with both username and email matching
    cursor.execute(
        "DELETE FROM user WHERE username=? AND email=?",
        ('admin', 'admin@gmail.com')
    )
    conn.commit()
    if cursor.rowcount > 0:
        print("Admin user deleted successfully.")
    else:
        print("Admin user not found.")
    conn.close()

if __name__ == "__main__":
    delete_admin_user()