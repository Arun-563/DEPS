import os
import threading
import requests


def _send_async(to_email: str, subject: str, html_body: str):
    api_key = os.environ.get("BREVO_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "").strip()
    from_name = os.environ.get("FROM_NAME", "Deps Blood Bank").strip()

    if not to_email or "@" not in to_email:
        print(f"[Email Skipped - Invalid Address] To: {to_email}")
        return

    if not api_key or not from_email:
        print(f"[Email Skipped - Missing BREVO_KEY or FROM_EMAIL in .env] To: {to_email}")
        return

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "sender": {"name": from_name, "email": from_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_body,
            },
            timeout=10,
        )
        print(f"[Email Result] Status: {resp.status_code} | To: {to_email} | Response: {resp.text}")
    except Exception as e:
        print(f"[Email Exception] {e}")


def send_email_background(to_email: str, subject: str, html_body: str):
    thread = threading.Thread(
        target=_send_async,
        args=(to_email, subject, html_body),
        daemon=False,
    )
    thread.start()


def notify_user_registered(to_email: str, name: str, user_id: int, blood_type: str, city_name: str):
    subject = f"Welcome to Deps Blood Bank! Your User ID is #{user_id}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; border: 1px solid #e5e7eb; border-radius: 10px; padding: 24px;">
        <h2 style="color: #dc2626; margin-top: 0;">Welcome, {name}!</h2>
        <p>Your account on <strong>Deps Blood Bank</strong> has been successfully created. Save your User ID below—you will need it to log in and at donation camps:</p>
        <div style="background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px; text-align: center; margin: 16px 0;">
            <div style="font-size: 12px; text-transform: uppercase; color: #991b1b; font-weight: bold;">Your Login User ID</div>
            <div style="font-size: 28px; font-weight: bold; color: #dc2626; margin-top: 4px;">#{user_id}</div>
        </div>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Registered Name:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{name}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Blood Group:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{blood_type}</td></tr>
            <tr><td style="padding: 8px;"><strong>City:</strong></td><td style="padding: 8px;">{city_name}</td></tr>
        </table>
        <p style="color: #4b5563; font-size: 14px;">Keep this email for future reference when logging in or visiting a Registrar desk.</p>
    </div>
    """
    send_email_background(to_email, subject, html)


def notify_employee_role_updated(to_email: str, name: str, user_id: int, employee_id: int, new_role: str, salary: int, action_type: str = "updated"):
    if action_type == "assigned":
        subject = f"Staff Appointment: You are now a {new_role} (Employee #{employee_id})"
        heading = "New Staff Role Assigned"
        intro = f"You have been appointed as a <strong>{new_role}</strong> at <strong>Deps Blood Bank</strong>."
    else:
        subject = f"Designation & Compensation Updated: {new_role}"
        heading = "Staff Designation / Salary Updated"
        intro = f"An administrator has updated your staff profile on <strong>Deps Blood Bank</strong>."

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; border: 1px solid #e5e7eb; border-radius: 10px; padding: 24px;">
        <h2 style="color: #dc2626; margin-top: 0;">{heading}</h2>
        <p>Hello {name},</p>
        <p>{intro}</p>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>User ID (Login):</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">#{user_id}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Employee ID:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">#{employee_id}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Current Designation:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>{new_role}</strong></td></tr>
            <tr><td style="padding: 8px;"><strong>Updated Salary:</strong></td><td style="padding: 8px;">&#8377;{salary:,}</td></tr>
        </table>
        <p style="color: #4b5563; font-size: 14px;">Log in with your User ID (<strong>#{user_id}</strong>) and select <strong>{new_role}</strong> as your role to access your portal.</p>
    </div>
    """
    send_email_background(to_email, subject, html)


def notify_donation_recorded(to_email: str, name: str, blood_type: str, blood_id: int, donation_date: str, expiry_date: str):
    subject = f"Thank You for Donating Blood! (Unit #{blood_id})"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; border: 1px solid #e5e7eb; border-radius: 10px; padding: 24px;">
        <h2 style="color: #dc2626; margin-top: 0;">Thank You, {name}!</h2>
        <p>Your blood donation has been officially logged into our inventory system.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Blood Unit ID:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">#{blood_id}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Blood Group:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{blood_type}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;"><strong>Donation Date:</strong></td><td style="padding: 8px; border-bottom: 1px solid #f3f4f6;">{donation_date}</td></tr>
            <tr><td style="padding: 8px;"><strong>Valid Until:</strong></td><td style="padding: 8px;">{expiry_date}</td></tr>
        </table>
        <p style="color: #4b5563; font-size: 14px;">Every unit saves lives. You will be eligible to donate again 60 days after {donation_date}.</p>
    </div>
    """
    send_email_background(to_email, subject, html)


def notify_blood_assigned(to_email: str, name: str, blood_type: str, request_id: int, blood_id: int, status_stage: str):
    if status_stage == "reserved":
        subject = f"Blood Unit #{blood_id} Reserved for Your Request (#{request_id})"
        heading = "Matching Blood Unit Found & Reserved"
        msg = f"A matching <strong>{blood_type}</strong> unit (Unit <strong>#{blood_id}</strong>) has been automatically matched to your Request <strong>#{request_id}</strong> and is awaiting Camp Coordinator approval."
    else:
        subject = f"Approved: Blood Unit #{blood_id} Ready for Request (#{request_id})"
        heading = "Blood Allocation Approved"
        msg = f"Your request (<strong>#{request_id}</strong>) for <strong>{blood_type}</strong> has been approved by the Camp Coordinator. Blood Unit <strong>#{blood_id}</strong> is allocated and ready."

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: auto; border: 1px solid #e5e7eb; border-radius: 10px; padding: 24px;">
        <h2 style="color: #dc2626; margin-top: 0;">{heading}</h2>
        <p>Hello {name},</p>
        <p>{msg}</p>
        <p style="color: #4b5563; font-size: 14px;">Please contact your city blood bank registrar for collection details.</p>
    </div>
    """
    send_email_background(to_email, subject, html)