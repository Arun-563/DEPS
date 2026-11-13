import os
from datetime import datetime, timedelta, date
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from psycopg2 import sql
import bcrypt
from dotenv import load_dotenv

from email_service import (
    notify_user_registered,
    notify_employee_role_updated,
    notify_donation_recorded,
    notify_blood_assigned,
)

load_dotenv(override=True)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/bloodbank"
)


@contextmanager
def get_db():
    """Opens a fresh PostgreSQL connection per request and closes it safely."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.route("/")
def index():
    if "user_id" in session and "role" in session:
        role = session["role"]
        return redirect(url_for(f"{role.lower().replace(' ', '')}_dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT city_id, name FROM city ORDER BY name")
        cities = cursor.fetchall()

        if request.method == "POST":
            name = request.form["name"].strip()
            blood_type = request.form["blood_type"].strip()
            city_id = request.form["city_id"]
            dob = request.form["dob"]
            contact = request.form["contact"].strip()
            password = request.form["password"]

            hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            try:
                cursor.execute(
                    """
                    INSERT INTO users (name, blood_type, city_id, dob, contact, password_hash)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING user_id
                    """,
                    (name, blood_type, city_id, dob, contact, hashed_password),
                )
                new_user_id = cursor.fetchone()[0]

                cursor.execute("SELECT name FROM city WHERE city_id = %s", (city_id,))
                city_row = cursor.fetchone()
                city_name = city_row[0] if city_row else "Registered City"
                conn.commit()

                notify_user_registered(
                    to_email=contact,
                    name=name,
                    user_id=new_user_id,
                    blood_type=blood_type,
                    city_name=city_name,
                )
                flash(
                    f"Registration successful! Your User ID is #{new_user_id} (also emailed to {contact}). Please log in.",
                    "success",
                )
                return redirect(url_for("login"))
            except psycopg2.Error as e:
                conn.rollback()
                error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
                flash(f"Registration error: {error_msg}", "error")

    return render_template("register.html", cities=cities)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session and "role" in session:
        role = session["role"]
        return redirect(url_for(f"{role.lower().replace(' ', '')}_dashboard"))

    if request.method == "POST":
        role = " ".join(word.capitalize() for word in request.form["role"].strip().split())
        user_id = request.form["user_id"].strip()
        password = request.form["password"].encode("utf-8")

        with get_db() as conn:
            cursor = conn.cursor()
            try:
                if role == "User":
                    cursor.execute(
                        "SELECT password_hash, name, blood_type, city_id FROM users WHERE user_id = %s",
                        (user_id,),
                    )
                    result = cursor.fetchone()
                    if result and bcrypt.checkpw(password, result[0].encode("utf-8")):
                        session["user_id"] = int(user_id)
                        session["name"] = result[1] or "User"
                        session["role"] = "user"
                        session["user_blood_type"] = result[2]
                        session["city_id"] = result[3]
                        return redirect(url_for("user_dashboard"))
                    flash("Invalid User ID or password.", "error")

                elif role in ("Admin", "Camp Coordinator", "Registrar"):
                    cursor.execute(
                        """
                        SELECT u.password_hash, u.name, e.employee_id, u.city_id
                        FROM employees e
                        JOIN users u ON e.user_id = u.user_id
                        WHERE e.user_id = %s AND e.role = %s
                        """,
                        (user_id, role),
                    )
                    result = cursor.fetchone()
                    if result and bcrypt.checkpw(password, result[0].encode("utf-8")):
                        session["user_id"] = int(user_id)
                        session["name"] = result[1] or role
                        session["role"] = role
                        session["employee_id"] = result[2]
                        session["city_id"] = result[3]
                        return redirect(url_for(f"{role.lower().replace(' ', '')}_dashboard"))
                    flash(f"Invalid credentials or role for {role}.", "error")
                else:
                    flash("Invalid role selected.", "error")
            except Exception as e:
                flash(f"Login error: {str(e)}", "error")

    return render_template("login.html")


@app.route("/demo_login/<role_key>")
def demo_login(role_key):
    """One-click demo login for recruiters/interviewers."""
    role_map = {
        "user": ("User", "user"),
        "registrar": ("Registrar", "Registrar"),
        "coordinator": ("Camp Coordinator", "Camp Coordinator"),
        "admin": ("Admin", "Admin"),
    }
    if role_key not in role_map:
        flash("Unknown demo role.", "error")
        return redirect(url_for("login"))

    _, db_role = role_map[role_key]

    with get_db() as conn:
        cursor = conn.cursor()
        if db_role == "user":
            cursor.execute("SELECT user_id, name, blood_type, city_id FROM users ORDER BY user_id ASC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                flash("Demo accounts not seeded yet. Run python seed.py first.", "error")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = row[0]
            session["name"] = row[1]
            session["role"] = "user"
            session["user_blood_type"] = row[2]
            session["city_id"] = row[3]
            flash(f"Logged in as Demo Donor ({row[1]}).", "success")
            return redirect(url_for("user_dashboard"))
        else:
            cursor.execute(
                """
                SELECT u.user_id, u.name, e.employee_id, u.city_id
                FROM employees e
                JOIN users u ON e.user_id = u.user_id
                WHERE e.role = %s
                ORDER BY e.employee_id ASC LIMIT 1
                """,
                (db_role,),
            )
            row = cursor.fetchone()
            if not row:
                flash(f"Demo {db_role} account not found. Run python seed.py first.", "error")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = row[0]
            session["name"] = row[1]
            session["role"] = db_role
            session["employee_id"] = row[2]
            session["city_id"] = row[3]
            flash(f"Logged in as Demo {db_role} ({row[1]}).", "success")
            return redirect(url_for(f"{db_role.lower().replace(' ', '')}_dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/user_dashboard", methods=["GET"])
def user_dashboard():
    if "user_id" not in session or session.get("role") != "user":
        session.clear()
        flash("Please log in as a donor/user.", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today_date = date.today()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_view_details(%s)", (user_id,))
        user_details = cursor.fetchone()[0]

        # Calculate 60-day donation eligibility status
        cursor.execute("SELECT MAX(donation_date) FROM donates WHERE user_id = %s", (user_id,))
        last_donation = cursor.fetchone()[0]
        if last_donation:
            next_eligible_date = last_donation + timedelta(days=60)
            is_eligible = today_date >= next_eligible_date
            days_remaining = max(0, (next_eligible_date - today_date).days)
        else:
            next_eligible_date = today_date
            is_eligible = True
            days_remaining = 0

        cursor.execute(
            """
            SELECT c.camp_id, ci.name, c.start_date, c.end_date
            FROM camp c
            JOIN city ci ON c.city_id = ci.city_id
            WHERE c.city_id = %s AND c.end_date >= CURRENT_DATE
            ORDER BY c.start_date ASC
            """,
            (session["city_id"],),
        )
        active_camps = cursor.fetchall()

    return render_template(
        "user_dashboard.html",
        user_details=user_details,
        active_camps=active_camps,
        today=today_date.isoformat(),
        is_eligible=is_eligible,
        next_eligible_date=next_eligible_date.isoformat(),
        days_remaining=days_remaining,
    )


@app.route("/campcoordinator_dashboard", methods=["GET", "POST"])
def campcoordinator_dashboard():
    if "user_id" not in session or session.get("role") != "Camp Coordinator":
        session.clear()
        flash("Please log in as a Camp Coordinator.", "error")
        return redirect(url_for("login"))

    city_id = session.get("city_id")
    name = session.get("name", "Camp Coordinator")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT update_expired_blood()")

        if request.method == "POST" and "add_camp" in request.form:
            start_date = request.form["start_date"]
            end_date = request.form["end_date"]
            try:
                cursor.execute("SELECT coordinator_add_camp(%s, %s, %s)", (city_id, start_date, end_date))
                camp_id = cursor.fetchone()[0]
                conn.commit()
                flash(f"Camp #{camp_id} scheduled successfully!", "success")
            except psycopg2.Error as e:
                conn.rollback()
                error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
                flash(f"Camp error: {error_msg}", "error")

        cursor.execute(
            """
            SELECT COUNT(i.blood_id)
            FROM inventory i
            JOIN camp c ON i.camp_id = c.camp_id
            WHERE c.city_id = %s AND i.assigned = 'ex'
            """,
            (city_id,),
        )
        expired_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT r.request_id, r.user_id, u.name, r.blood_type, r.units_required,
                   rs.process_id, rs.blood_id, i.expiry_date
            FROM requests r
            JOIN request_status rs ON r.request_id = rs.request_id
            JOIN users u ON r.user_id = u.user_id
            JOIN inventory i ON rs.blood_id = i.blood_id
            WHERE rs.status = 'no'
              AND rs.blood_found = 'yes'
              AND rs.blood_id IS NOT NULL
              AND u.city_id = %s
            """,
            (city_id,),
        )
        pending_requests = cursor.fetchall()

        cursor.execute(
            "SELECT camp_id, start_date, end_date FROM camp WHERE city_id = %s ORDER BY start_date DESC",
            (city_id,),
        )
        camps = cursor.fetchall()

        cursor.execute(
            """
            SELECT i.blood_type, COUNT(i.blood_id) AS blood_count, MIN(i.expiry_date) AS earliest_expiry
            FROM inventory i
            JOIN camp c ON i.camp_id = c.camp_id
            WHERE c.city_id = %s AND i.expiry_date > CURRENT_DATE AND i.assigned = 'no'
            GROUP BY i.blood_type
            ORDER BY i.blood_type
            """,
            (city_id,),
        )
        inventory = cursor.fetchall()

    return render_template(
        "campcoordinator_dashboard.html",
        camps=camps,
        pending_requests=pending_requests,
        inventory=inventory,
        expired_count=expired_count,
        city_id=city_id,
        name=name,
    )


@app.route("/approve_request/<int:process_id>", methods=["POST"])
def approve_request(process_id):
    if "user_id" not in session or session.get("role") != "Camp Coordinator":
        flash("Unauthorized access.", "error")
        return redirect(url_for("login"))

    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT u.contact, u.name, r.blood_type, r.request_id, rs.blood_id
                FROM request_status rs
                JOIN requests r ON rs.request_id = r.request_id
                JOIN users u ON r.user_id = u.user_id
                WHERE rs.process_id = %s
                """,
                (process_id,),
            )
            info = cursor.fetchone()

            cursor.execute("SELECT process_blood_request(%s, %s)", (process_id, "approve"))
            conn.commit()

            if info:
                notify_blood_assigned(
                    to_email=info[0],
                    name=info[1],
                    blood_type=info[2],
                    request_id=info[3],
                    blood_id=info[4],
                    status_stage="approved",
                )
            flash("Request approved and recipient notified via email!", "success")
        except psycopg2.Error as e:
            conn.rollback()
            error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
            flash(f"Error approving request: {error_msg}", "error")

    return redirect(url_for("campcoordinator_dashboard"))


@app.route("/reject_request/<int:process_id>", methods=["POST"])
def reject_request(process_id):
    if "user_id" not in session or session.get("role") != "Camp Coordinator":
        flash("Unauthorized access.", "error")
        return redirect(url_for("login"))

    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT process_blood_request(%s, %s)", (process_id, "reject"))
            conn.commit()
            flash("Request rejected and blood unit returned to inventory.", "success")
        except psycopg2.Error as e:
            conn.rollback()
            error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
            flash(f"Error rejecting request: {error_msg}", "error")

    return redirect(url_for("campcoordinator_dashboard"))


@app.route("/registrar_dashboard", methods=["GET", "POST"])
def registrar_dashboard():
    if "user_id" not in session or session.get("role") != "Registrar":
        session.clear()
        flash("Please log in as a Registrar.", "error")
        return redirect(url_for("login"))

    employee_id = session.get("employee_id")
    name = session.get("name", "Registrar")
    today_date = date.today()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT city_id, name FROM city ORDER BY name")
        cities = cursor.fetchall()

        selected_city_id = None
        inventory = []
        filter_user_id = None
        searched_users = []
        search_query = ""

        if request.method == "POST":
            if "search_users" in request.form:
                search_query = request.form.get("search_query", "").strip()
                if search_query:
                    cursor.execute(
                        """
                        SELECT u.user_id, u.name, u.blood_type, c.name, u.contact
                        FROM users u
                        JOIN city c ON u.city_id = c.city_id
                        WHERE u.name ILIKE %s OR u.contact ILIKE %s OR CAST(u.user_id AS TEXT) = %s
                        ORDER BY u.user_id ASC
                        LIMIT 10
                        """,
                        (f"%{search_query}%", f"%{search_query}%", search_query),
                    )
                    searched_users = cursor.fetchall()

            elif "record_donation" in request.form:
                try:
                    donor_user_id = int(request.form["donor_user_id"])
                    donation_date = today_date
                    donation_date_str = donation_date.strftime("%Y-%m-%d")

                    cursor.execute(
                        "SELECT name, contact, blood_type FROM users WHERE user_id = %s",
                        (donor_user_id,),
                    )
                    donor_info = cursor.fetchone()
                    if not donor_info:
                        flash(f"Donor User ID #{donor_user_id} does not exist.", "error")
                    else:
                        # Check if employee_id column exists on donates for audit tracking
                        cursor.execute(
                            """
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'donates' AND column_name = 'employee_id'
                            """
                        )
                        has_emp_col = cursor.fetchone() is not None

                        if has_emp_col:
                            cursor.execute(
                                """
                                INSERT INTO donates (user_id, blood_id, donation_date, employee_id)
                                VALUES (%s, 0, %s, %s)
                                RETURNING blood_id
                                """,
                                (donor_user_id, donation_date, employee_id),
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO donates (user_id, blood_id, donation_date)
                                VALUES (%s, 0, %s)
                                RETURNING blood_id
                                """,
                                (donor_user_id, donation_date),
                            )
                        blood_id = cursor.fetchone()[0]
                        conn.commit()

                        u_name, u_email, u_blood = donor_info
                        expiry_str = (donation_date + timedelta(days=42)).strftime("%Y-%m-%d")
                        notify_donation_recorded(
                            to_email=u_email,
                            name=u_name,
                            blood_type=u_blood,
                            blood_id=blood_id,
                            donation_date=donation_date_str,
                            expiry_date=expiry_str,
                        )
                        flash(
                            f"Verified donation logged for {u_name} (Unit #{blood_id}) by Registrar #{employee_id}! Receipt sent to {u_email}.",
                            "success",
                        )

                except psycopg2.Error as e:
                    conn.rollback()
                    error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
                    flash(f"Donation error: {error_msg}", "error")
                except ValueError:
                    flash("Please enter a valid numeric Donor User ID.", "error")

            elif "view_inventory" in request.form:
                selected_city_id = request.form.get("city_id")
                if selected_city_id:
                    cursor.execute(
                        """
                        SELECT i.blood_type, COUNT(i.blood_id) AS quantity, c.name, MIN(i.expiry_date) AS earliest_expiry
                        FROM inventory i
                        JOIN camp ca ON i.camp_id = ca.camp_id
                        JOIN city c ON ca.city_id = c.city_id
                        WHERE ca.city_id = %s AND i.expiry_date > CURRENT_DATE AND i.assigned = 'no'
                        GROUP BY i.blood_type, c.name
                        ORDER BY i.blood_type
                        """,
                        (selected_city_id,),
                    )
                    inventory = cursor.fetchall()

            elif "request_blood" in request.form:
                recipient_user_id = request.form["recipient_user_id"]
                blood_type = request.form["blood_type"]
                units_required = int(request.form["units_required"])
                request_date = today_date.strftime("%Y-%m-%d")

                try:
                    cursor.execute(
                        "SELECT registrar_add_request(%s, %s, %s, %s, %s)",
                        (recipient_user_id, employee_id, blood_type, units_required, request_date),
                    )
                    request_id = cursor.fetchone()[0]

                    cursor.execute(
                        """
                        SELECT rs.blood_found, rs.blood_id, u.contact, u.name
                        FROM request_status rs
                        JOIN requests r ON rs.request_id = r.request_id
                        JOIN users u ON r.user_id = u.user_id
                        WHERE rs.request_id = %s
                        """,
                        (request_id,),
                    )
                    match = cursor.fetchone()
                    conn.commit()

                    if match and match[0] == "yes" and match[1]:
                        notify_blood_assigned(
                            to_email=match[2],
                            name=match[3],
                            blood_type=blood_type,
                            request_id=request_id,
                            blood_id=match[1],
                            status_stage="reserved",
                        )
                        flash(
                            f"Request #{request_id} created & auto-matched to Unit #{match[1]}! Email sent to {match[2]}.",
                            "success",
                        )
                    else:
                        flash(f"Request #{request_id} logged (queued for matching inventory).", "info")

                except psycopg2.Error as e:
                    conn.rollback()
                    error_msg = e.diag.message_primary if e.diag and e.diag.message_primary else str(e)
                    flash(f"Request error: {error_msg}", "error")

            elif "filter_user" in request.form:
                raw_filter = request.form.get("filter_user_id", "").strip()
                if raw_filter.isdigit():
                    filter_user_id = int(raw_filter)

        if filter_user_id:
            cursor.execute(
                """
                SELECT d.user_id, u.name, d.blood_id, i.blood_type, d.donation_date, c.name, u.contact
                FROM donates d
                JOIN users u ON d.user_id = u.user_id
                JOIN inventory i ON d.blood_id = i.blood_id
                JOIN camp ca ON i.camp_id = ca.camp_id
                JOIN city c ON ca.city_id = c.city_id
                WHERE d.user_id = %s
                ORDER BY d.donation_date DESC
                """,
                (filter_user_id,),
            )
        else:
            cursor.execute(
                """
                SELECT d.user_id, u.name, d.blood_id, i.blood_type, d.donation_date, c.name, u.contact
                FROM donates d
                JOIN users u ON d.user_id = u.user_id
                JOIN inventory i ON d.blood_id = i.blood_id
                JOIN camp ca ON i.camp_id = ca.camp_id
                JOIN city c ON ca.city_id = c.city_id
                ORDER BY d.donation_date DESC
                LIMIT 20
                """
            )
        donations = cursor.fetchall()

        if filter_user_id:
            cursor.execute(
                """
                SELECT r.request_id, r.user_id, u.name, r.employee_id, r.blood_type, r.units_required, r.request_date
                FROM requests r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.user_id = %s
                ORDER BY r.request_date DESC
                """,
                (filter_user_id,),
            )
        else:
            cursor.execute(
                """
                SELECT r.request_id, r.user_id, u.name, r.employee_id, r.blood_type, r.units_required, r.request_date
                FROM requests r
                JOIN users u ON r.user_id = u.user_id
                ORDER BY r.request_date DESC
                LIMIT 20
                """
            )
        requests_list = cursor.fetchall()

        cursor.execute(
            """
            SELECT rs.process_id, rs.request_id, rs.blood_id, rs.status, rs.blood_found, rs.date_approved
            FROM request_status rs
            ORDER BY rs.process_id DESC
            """
        )
        request_status = cursor.fetchall()

    return render_template(
        "registrar_dashboard.html",
        cities=cities,
        selected_city_id=selected_city_id,
        inventory=inventory,
        donations=donations,
        requests=requests_list,
        request_status=request_status,
        filter_user_id=filter_user_id,
        searched_users=searched_users,
        search_query=search_query,
        today=today_date.isoformat(),
        name=name,
    )

@app.route("/admin_dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "Admin":
        session.clear()
        flash("Please log in as an Admin.", "error")
        return redirect(url_for("login"))

    admin_city_id = session.get("city_id")
    name = session.get("name", "Admin")

    with get_db() as conn:
        cursor = conn.cursor()
        if request.method == "POST":
            if "add_city" in request.form:
                try:
                    city_name = request.form["city_name"].strip()
                    longitude = float(request.form["longitude"])
                    latitude = float(request.form["latitude"])
                    cursor.execute("SELECT admin_add_city(%s, %s, %s)", (city_name, longitude, latitude))
                    city_id = cursor.fetchone()[0]
                    conn.commit()
                    flash(f"City {city_name} (ID: {city_id}) added!", "success")
                except Exception as e:
                    conn.rollback()
                    flash(f"City error: {e}", "error")

            elif "add_employee" in request.form:
                try:
                    emp_user_id = int(request.form["user_id"])
                    role = request.form["role"]
                    salary = int(request.form["salary"])
                    cursor.execute(
                        "SELECT city_id, name, contact FROM users WHERE user_id = %s",
                        (emp_user_id,),
                    )
                    user = cursor.fetchone()
                    if not user or user[0] != admin_city_id:
                        flash("User must exist and belong to your city.", "error")
                    elif role not in ("Camp Coordinator", "Registrar"):
                        flash("Invalid role.", "error")
                    else:
                        cursor.execute(
                            """
                            INSERT INTO employees (role, user_id, salary)
                            VALUES (%s, %s, %s)
                            RETURNING employee_id
                            """,
                            (role, emp_user_id, salary),
                        )
                        new_emp_id = cursor.fetchone()[0]
                        conn.commit()

                        notify_employee_role_updated(
                            to_email=user[2],
                            name=user[1],
                            user_id=emp_user_id,
                            employee_id=new_emp_id,
                            new_role=role,
                            salary=salary,
                            action_type="assigned",
                        )
                        flash(f"Employee #{new_emp_id} assigned as {role} and notified via email!", "success")
                except Exception as e:
                    conn.rollback()
                    flash(f"Employee error: {e}", "error")

            elif "update_employee" in request.form:
                try:
                    emp_id = int(request.form["employee_id"])
                    new_role = request.form["role"]
                    new_salary = int(request.form["salary"])

                    if new_role not in ("Camp Coordinator", "Registrar"):
                        flash("Invalid designation selected.", "error")
                    else:
                        cursor.execute(
                            """
                            SELECT e.user_id, e.role, e.salary, u.name, u.contact
                            FROM employees e
                            JOIN users u ON e.user_id = u.user_id
                            WHERE e.employee_id = %s AND u.city_id = %s AND e.role != 'Admin'
                            """,
                            (emp_id, admin_city_id),
                        )
                        emp_row = cursor.fetchone()
                        if not emp_row:
                            flash("Employee not found in your city.", "error")
                        else:
                            cursor.execute(
                                """
                                UPDATE employees
                                SET role = %s, salary = %s
                                WHERE employee_id = %s
                                """,
                                (new_role, new_salary, emp_id),
                            )
                            conn.commit()

                            notify_employee_role_updated(
                                to_email=emp_row[4],
                                name=emp_row[3],
                                user_id=emp_row[0],
                                employee_id=emp_id,
                                new_role=new_role,
                                salary=new_salary,
                                action_type="updated",
                            )
                            flash(
                                f"Updated {emp_row[3]} (Emp #{emp_id}) to {new_role} (₹{new_salary:,}) and sent notification email!",
                                "success",
                            )
                except Exception as e:
                    conn.rollback()
                    flash(f"Update error: {e}", "error")

            elif "delete_employee" in request.form:
                try:
                    emp_id = int(request.form["employee_id"])
                    cursor.execute(
                        "DELETE FROM employees WHERE employee_id = %s AND role != 'Admin'",
                        (emp_id,),
                    )
                    conn.commit()
                    flash("Employee removed.", "success")
                except Exception as e:
                    conn.rollback()
                    flash(f"Delete error: {e}", "error")

        def parse_point(point_str):
            if point_str:
                try:
                    coords = point_str.strip("()").split(",")
                    return (float(coords[0]), float(coords[1]))
                except (ValueError, IndexError):
                    return None
            return None

        cursor.execute("SELECT city_id, name, location FROM city ORDER BY name")
        cities = [(c[0], c[1], parse_point(c[2])) for c in cursor.fetchall()]

        cursor.execute(
            """
            SELECT e.employee_id, e.role, e.user_id, e.salary, u.name, u.contact
            FROM employees e
            JOIN users u ON e.user_id = u.user_id
            WHERE e.role != 'Admin' AND u.city_id = %s
            ORDER BY e.employee_id
            """,
            (admin_city_id,),
        )
        employees = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM donates")
        total_donations = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM requests")
        total_requests = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM request_status WHERE status = 'yes'")
        fulfilled_requests = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT i.blood_type, COUNT(i.blood_id) AS quantity
            FROM inventory i
            WHERE i.expiry_date > CURRENT_DATE AND i.assigned = 'no'
            GROUP BY i.blood_type
            ORDER BY i.blood_type
            """
        )
        inventory_stats = cursor.fetchall()

    return render_template(
        "admin_dashboard.html",
        cities=cities,
        employees=employees,
        total_donations=total_donations,
        total_requests=total_requests,
        fulfilled_requests=fulfilled_requests,
        inventory_stats=inventory_stats,
        name=name,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)