import os
from datetime import date, timedelta
import psycopg2
import bcrypt
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/bloodbank"
)


def run_seed():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    with open("database.sql", "r", encoding="utf-8") as f:
        cur.execute(f.read())

    # 1. Cities
    cities = [
        ("Kochi", 76.2673, 9.9312),
        ("Bengaluru", 77.5946, 12.9716),
        ("Mumbai", 72.8777, 19.0760),
    ]
    city_ids = {}
    for name, lon, lat in cities:
        cur.execute("SELECT city_id FROM city WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT admin_add_city(%s, %s, %s)", (name, lon, lat))
            city_ids[name] = cur.fetchone()[0]
        else:
            city_ids[name] = row[0]

    kochi_id = city_ids["Kochi"]
    pw_hash = bcrypt.hashpw(b"demo123", bcrypt.gensalt()).decode("utf-8")

    # 2. Sample Users (Donors + Staff)
    sample_users = [
        ("Arjun Menon", "O+", kochi_id, "1998-05-14", "busysha4@gmail.com"),
        ("Priya Nair", "A+", kochi_id, "1995-08-22", "priya.registrar@example.com"),
        ("Rahul Varma", "B+", kochi_id, "1992-11-03", "rahul.coord@example.com"),
        ("Meera Krishnan", "AB+", kochi_id, "1990-02-19", "meera.admin@example.com"),
        ("Sneha Das", "O-", kochi_id, "2000-07-11", "sneha.recipient@example.com"),
    ]

    user_ids = []
    for name, btype, cid, dob, contact in sample_users:
        cur.execute("SELECT user_id FROM users WHERE contact = %s", (contact,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                INSERT INTO users (name, blood_type, city_id, dob, contact, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING user_id
                """,
                (name, btype, cid, dob, contact, pw_hash),
            )
            user_ids.append(cur.fetchone()[0])
        else:
            user_ids.append(row[0])

    donor_id, reg_uid, coord_uid, admin_uid, recipient_uid = user_ids

    # 3. Assign Employee Roles
    staff = [
        ("Registrar", reg_uid, 45000),
        ("Camp Coordinator", coord_uid, 55000),
        ("Admin", admin_uid, 75000),
    ]
    for role, uid, salary in staff:
        cur.execute(
            """
            INSERT INTO employees (role, user_id, salary)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (role, uid, salary),
        )

    # 4. Active Blood Camp in Kochi
    today = date.today()
    cur.execute("SELECT camp_id FROM camp WHERE city_id = %s LIMIT 1", (kochi_id,))
    camp_row = cur.fetchone()
    if not camp_row:
        cur.execute(
            "SELECT coordinator_add_camp(%s, %s, %s)",
            (kochi_id, today - timedelta(days=5), today + timedelta(days=25)),
        )
        camp_id = cur.fetchone()[0]
    else:
        camp_id = camp_row[0]

    # 5. Seed Initial Blood Inventory Units
    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        units = ["O+", "O-", "A+", "B+", "AB+", "O+"]
        for bt in units:
            cur.execute(
                """
                INSERT INTO inventory (camp_id, blood_type, expiry_date, assigned)
                VALUES (%s, %s, %s, 'no')
                """,
                (camp_id, bt, today + timedelta(days=35)),
            )

    conn.commit()
    cur.close()
    conn.close()
    print("Database schema and demo seed data initialized successfully!")


if __name__ == "__main__":
    run_seed()
