# 🩸 Deps Blood Bank — Automated Inventory & RBAC Management System

**Live Demo:** [ https://deps-bloodbank.onrender.com/](https://deps-bloodbank.onrender.com/)  
**Repository:** [github.com/Arun-563/DEPS](https://github.com/Arun-563/DEPS)

---

## 📌 Overview

**Deps Blood Bank** is a full-stack blood bank operations and inventory management platform built with **Flask**, **PostgreSQL (Neon)**, **Tailwind CSS**, and the **Brevo Transactional Email API**.

Rather than building a naive CRUD application where users self-report donations or constantly poll the database for inventory matches, this system models **real-world hospital blood bank workflows**:
- **Zero Phantom Inventory:** Donors cannot directly mint inventory units or submit unverified blood requests. Every walk-in donation and patient blood request must be physically verified and logged by an authorized **Registrar** at a camp or hospital desk, creating a full audit trail (`employee_id`).
- **Event-Driven Database Automation (No Polling Overhead):** Instead of running wasteful background loops or polling the database every few seconds to match blood requests with available bags, Deps Blood Bank uses **PostgreSQL Triggers & PL/pgSQL Stored Functions**. Matching, stock reservation, expiry updates, and cooldown enforcement execute **automatically and atomically only at the exact moment a state change occurs** (`INSERT`/`UPDATE`).

---

## 🏗️ System Architecture & Clever Automation

### 1. Event-Driven Triggers & Stored Procedures (Zero Resource Polling)
Traditional systems often rely on periodic cron jobs or continuous polling listeners to pair open blood requests with incoming donations—consuming unnecessary CPU and database I/O. Deps Blood Bank solves this at the database layer using **event-driven triggers**:

- **Donation Ingestion & Cooldown Trigger (`donates`):**
  - Enforces a strict **60-day medical recovery cooldown** between donations per donor.
  - Verifies that an **active donation camp** exists in the donor's registered city on `CURRENT_DATE`.
  - Automatically mints a new blood unit in `inventory` with a **42-day shelf life** (`CURRENT_DATE + 42 days`).
  - **Instant End-to-End Request Matching:** The moment a new blood unit enters `inventory`, a database trigger checks for waiting, unfulfilled `requests` of that blood group in the city and immediately reserves the newly donated unit—without any external listener polling the database.

- **Request Creation & Auto-Reservation (`registrar_add_request`):**
  - When a Registrar logs a verified patient blood request, PostgreSQL immediately searches active, non-expired, unassigned inventory (`expiry_date > CURRENT_DATE AND assigned = 'no'`) using **FEFO (First-Expired, First-Out)** priority.
  - If a compatible unit is available, it locks and reserves that unit (`blood_found = 'yes'`) within the same transaction. If not, the request stays queued until a matching donation trigger fires.

- **Camp Coordinator Approval State Machine (`process_blood_request`):**
  - Reserved units require final sign-off from a **Camp Coordinator** before dispatch (`approve` or `reject`).
  - Approving finalizes allocation (`status = 'yes'`); rejecting safely releases the reserved blood unit back into available city inventory (`assigned = 'no'`).

- **Automated Shelf-Life Expiry Sweep (`update_expired_blood`):**
  - Automatically flags any unassigned unit past its 42-day window (`assigned = 'ex'`) whenever coordinator inventory views are accessed, preventing expired stock from ever being matched.

---

### 2. Role-Based Access Control (RBAC) — What Each Role Can Do

| Role | Responsibilities & Permissions |
| :--- | :--- |
| **Donor / User** *(Read-Only Portal)* | • Registers once and receives their unique **User ID** via email.<br>• Views personal **60-day donation eligibility countdown**.<br>• Checks active donation camps in their city.<br>• Tracks personal donation history (unit status: `Available`, `Reserved/Assigned`, `Expired`) and blood request allocations. |
| **Registrar** *(Front-Desk Verification)* | • Looks up registered residents by Name, Email, or User ID.<br>• **Verifies & Logs Walk-In Donations** (locked to `CURRENT_DATE`) after physical screening.<br>• **Submits Verified Blood Requests** on behalf of patients/hospitals, triggering instant FEFO stock matching.<br>• Audits city-wide live blood stock by blood group and earliest expiry date. |
| **Camp Coordinator** *(Operations & Dispatch)* | • Schedules new blood donation camps (`coordinator_add_camp`) with start/end date validation.<br>• Reviews auto-reserved blood allocations and **Approves or Rejects** final dispatch.<br>• Monitors active city inventory and expired unit counts. |
| **Admin** *(City & Staff Governance)* | • Adds new cities with geospatial coordinates (`admin_add_city`).<br>• Searches city residents and **appoints new staff** (`Registrar` or `Camp Coordinator`).<br>• **Updates employee designations & salaries** (e.g., promoting a Registrar to Camp Coordinator) or removes staff—automatically notifying the employee via email. |

---

### 3. Asynchronous Transactional Email Notifications (Brevo API)
All critical lifecycle events dispatch formatted HTML email alerts on non-blocking background worker threads (`threading.Thread`) so external SMTP/HTTP latency never slows down database transactions:
1. **Account Registration:** Sends the user's generated numeric **User ID** (`#ID`) upon sign-up so they always have their login and camp check-in ID handy.
2. **Walk-In Donation Receipt:** Sends the Blood Unit ID, blood group, donation date, and 42-day expiration date when a Registrar logs a donation.
3. **Blood Reservation & Approval Alerts:** Notifies the recipient when a matching unit is auto-reserved by a trigger, and again when the Camp Coordinator approves final release.
4. **Staff Appointment & Designation Updates:** Automatically emails employees whenever an Admin appoints them or updates their role (`Registrar` $\leftrightarrow$ `Camp Coordinator`) or compensation.

---

## 🧪 Exploring the Live Demo (Guidelines for Evaluators)

You can explore all four roles directly from the login page using the **One-Click Demo Login** buttons (or by registering a fresh account):

1. **Recommended Walkthrough Flow:**
   - Start as **Demo Admin** $\rightarrow$ inspect city metrics, staff directory, and role/salary controls.
   - Switch to **Demo Camp Coordinator** $\rightarrow$ ensure an active camp exists for today's date and review pending blood approvals.
   - Switch to **Demo Registrar** $\rightarrow$ use the User Lookup bar to find a donor's ID, record a walk-in donation, or submit a blood request to see instant trigger matching in action.
   - Switch to **Demo Donor** $\rightarrow$ view the updated eligibility countdown, donation history, and request tracking.

2. **Note on Shared Live Database:**
   - This deployment runs against a live **PostgreSQL (Neon)** database to replicate real-world transactional persistence and trigger execution.
   - Please avoid entering spam, destructive test strings, or fake medical data when exploring—every action commits directly to the live database. *(Note: On free-tier hosting, the first request after 15 minutes of inactivity may take ~30–40 seconds to wake the server.)*

---

## 🛠️ Tech Stack

- **Backend:** Python 3, Flask, Gunicorn, `psycopg2`, `bcrypt`
- **Database:** PostgreSQL (Neon Serverless) with PL/pgSQL Triggers & Stored Functions
- **Frontend:** Jinja2 Templates, Tailwind CSS
- **Email Service:** Brevo REST API (`v3/smtp/email`) with background thread workers

---

## 💻 Local Setup

```bash
# 1. Clone the repository
git clone [https://github.com/Arun-563/DEPS.git](https://github.com/Arun-563/DEPS.git)
cd DEPS

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables (.env)
cat <<EOF> .env
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
SECRET_KEY=your-secret-key
BREVO_KEY=your-brevo-api-key
FROM_EMAIL=your-verified-sender@example.com
FROM_NAME=Deps Blood Bank
EOF

# 5. Run the application
flask --app app run --debug


