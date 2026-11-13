-- Production-Ready PostgreSQL Schema, Triggers & Functions for Blood Bank System

BEGIN;

CREATE TABLE IF NOT EXISTS public.city
(
    city_id serial NOT NULL,
    name character varying(100) NOT NULL UNIQUE,
    location point NOT NULL,
    CONSTRAINT city_pkey PRIMARY KEY (city_id)
);

CREATE TABLE IF NOT EXISTS public.camp
(
    camp_id serial NOT NULL,
    city_id integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    CONSTRAINT camp_pkey PRIMARY KEY (camp_id),
    CONSTRAINT camp_city_id_fkey FOREIGN KEY (city_id)
        REFERENCES public.city (city_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.users
(
    user_id serial NOT NULL,
    password_hash character varying(255) NOT NULL,
    blood_type character varying(10) NOT NULL,
    name character varying(100) NOT NULL,
    city_id integer NOT NULL,
    dob date NOT NULL,
    contact text NOT NULL,
    CONSTRAINT users_pkey PRIMARY KEY (user_id),
    CONSTRAINT users_city_id_fkey FOREIGN KEY (city_id)
        REFERENCES public.city (city_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.employees
(
    employee_id serial NOT NULL,
    role character varying(50) NOT NULL,
    user_id integer NOT NULL,
    salary numeric NOT NULL,
    CONSTRAINT employees_pkey PRIMARY KEY (employee_id),
    CONSTRAINT employees_user_id_key UNIQUE (user_id),
    CONSTRAINT employees_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES public.users (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.inventory
(
    blood_id serial NOT NULL,
    camp_id integer NOT NULL,
    blood_type character varying(5) NOT NULL,
    expiry_date date NOT NULL,
    assigned character varying(3) DEFAULT 'no',
    CONSTRAINT inventory_pkey PRIMARY KEY (blood_id),
    CONSTRAINT inventory_camp_id_fkey FOREIGN KEY (camp_id)
        REFERENCES public.camp (camp_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.donates
(
    user_id integer NOT NULL,
    blood_id integer NOT NULL,
    donation_date date NOT NULL,
    CONSTRAINT donates_pkey PRIMARY KEY (user_id, blood_id),
    CONSTRAINT donates_blood_id_fkey FOREIGN KEY (blood_id)
        REFERENCES public.inventory (blood_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT donates_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES public.users (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.requests
(
    request_id serial NOT NULL,
    user_id integer NOT NULL,
    employee_id integer NOT NULL,
    units_required integer NOT NULL DEFAULT 1,
    blood_type character varying(10) NOT NULL,
    request_date date NOT NULL DEFAULT CURRENT_DATE,
    CONSTRAINT requests_pkey PRIMARY KEY (request_id),
    CONSTRAINT requests_employee_id_fkey FOREIGN KEY (employee_id)
        REFERENCES public.employees (employee_id) ON DELETE RESTRICT,
    CONSTRAINT requests_user_id_fkey FOREIGN KEY (user_id)
        REFERENCES public.users (user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.request_status
(
    process_id serial NOT NULL,
    request_id integer NOT NULL,
    blood_id integer,
    status character varying(20) NOT NULL DEFAULT 'no',
    date_approved date,
    blood_found character varying(3) DEFAULT 'no',
    CONSTRAINT request_status_pkey PRIMARY KEY (process_id),
    CONSTRAINT request_status_blood_id_fkey FOREIGN KEY (blood_id)
        REFERENCES public.inventory (blood_id) ON DELETE SET NULL,
    CONSTRAINT request_status_request_id_fkey FOREIGN KEY (request_id)
        REFERENCES public.requests (request_id) ON DELETE CASCADE
);

-- Trigger 1: Auto-match new inventory unit to oldest pending request in same city
CREATE OR REPLACE FUNCTION match_blood_to_request() RETURNS TRIGGER AS $$
DECLARE
    v_request_id INT;
    v_process_id INT;
    v_city_id INT;
BEGIN
    IF NEW.assigned = 'no' THEN
        SELECT city_id INTO v_city_id
        FROM camp
        WHERE camp_id = NEW.camp_id;

        SELECT r.request_id, rs.process_id INTO v_request_id, v_process_id
        FROM requests r
        JOIN request_status rs ON r.request_id = rs.request_id
        JOIN users u ON r.user_id = u.user_id
        WHERE r.blood_type = NEW.blood_type
          AND u.city_id = v_city_id
          AND rs.status = 'no'
          AND rs.blood_found = 'no'
          AND rs.blood_id IS NULL
        ORDER BY r.request_date ASC, r.request_id ASC
        LIMIT 1;

        IF v_request_id IS NOT NULL THEN
            UPDATE inventory
            SET assigned = 'yes'
            WHERE blood_id = NEW.blood_id;

            UPDATE request_status
            SET blood_id = NEW.blood_id,
                blood_found = 'yes'
            WHERE process_id = v_process_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS inventory_trigger ON inventory;
CREATE TRIGGER inventory_trigger
AFTER INSERT OR UPDATE OF assigned ON inventory
FOR EACH ROW
WHEN (NEW.assigned = 'no')
EXECUTE FUNCTION match_blood_to_request();

-- Trigger 2: Create request_status & auto-assign matching inventory unit on new request
CREATE OR REPLACE FUNCTION handle_new_request() RETURNS TRIGGER AS $$
DECLARE
    v_city_id INT;
    v_blood_id INT;
    v_process_id INT;
BEGIN
    SELECT city_id INTO v_city_id
    FROM users
    WHERE user_id = NEW.user_id;

    INSERT INTO request_status (request_id, status, blood_found)
    VALUES (NEW.request_id, 'no', 'no')
    RETURNING process_id INTO v_process_id;

    SELECT i.blood_id INTO v_blood_id
    FROM inventory i
    JOIN camp c ON i.camp_id = c.camp_id
    WHERE i.blood_type = NEW.blood_type
      AND i.assigned = 'no'
      AND i.expiry_date > CURRENT_DATE
      AND c.city_id = v_city_id
    ORDER BY i.expiry_date ASC
    LIMIT 1;

    IF v_blood_id IS NOT NULL THEN
        UPDATE inventory
        SET assigned = 'yes'
        WHERE blood_id = v_blood_id;

        UPDATE request_status
        SET blood_id = v_blood_id,
            blood_found = 'yes'
        WHERE process_id = v_process_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS request_trigger ON requests;
CREATE TRIGGER request_trigger
AFTER INSERT ON requests
FOR EACH ROW
EXECUTE FUNCTION handle_new_request();

-- Trigger 3: Validate 60-day cooldown & create inventory row cleanly on donation insert
CREATE OR REPLACE FUNCTION handle_donation_inventory() RETURNS TRIGGER AS $$
DECLARE
    v_blood_type VARCHAR;
    v_city_id INT;
    v_camp_id INT;
    v_last_donation DATE;
BEGIN
    SELECT MAX(donation_date) INTO v_last_donation
    FROM donates
    WHERE user_id = NEW.user_id;

    IF v_last_donation IS NOT NULL THEN
        IF NEW.donation_date = v_last_donation THEN
            RAISE EXCEPTION 'User % cannot donate multiple times on the same day (%)', NEW.user_id, NEW.donation_date;
        END IF;
        IF NEW.donation_date < v_last_donation + INTERVAL '60 days' THEN
            RAISE EXCEPTION 'Cooldown active: Next eligible donation date is %', (v_last_donation + INTERVAL '60 days')::date;
        END IF;
    END IF;

    SELECT blood_type, city_id INTO v_blood_type, v_city_id
    FROM users
    WHERE user_id = NEW.user_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User % not found', NEW.user_id;
    END IF;

    SELECT camp_id INTO v_camp_id
    FROM camp
    WHERE city_id = v_city_id
      AND start_date <= NEW.donation_date
      AND end_date >= NEW.donation_date
    LIMIT 1;

    IF v_camp_id IS NULL THEN
        RAISE EXCEPTION 'No active donation camp in your city on %', NEW.donation_date;
    END IF;

    INSERT INTO inventory (camp_id, blood_type, expiry_date, assigned)
    VALUES (v_camp_id, v_blood_type, NEW.donation_date + INTERVAL '42 days', 'no')
    RETURNING blood_id INTO NEW.blood_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS donation_trigger ON donates;
CREATE TRIGGER donation_trigger
BEFORE INSERT ON donates
FOR EACH ROW
EXECUTE FUNCTION handle_donation_inventory();

-- Function: Mark expired units
CREATE OR REPLACE FUNCTION update_expired_blood()
RETURNS INTEGER AS $$
DECLARE
    v_updated_count INTEGER;
BEGIN
    UPDATE inventory
    SET assigned = 'ex'
    WHERE expiry_date <= CURRENT_DATE
      AND assigned = 'no';

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    RETURN v_updated_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Add City
CREATE OR REPLACE FUNCTION admin_add_city(p_city_name VARCHAR, p_longitude DOUBLE PRECISION, p_latitude DOUBLE PRECISION)
RETURNS INTEGER AS $$
DECLARE
    v_city_id INTEGER;
BEGIN
    INSERT INTO city (name, location)
    VALUES (p_city_name, POINT(p_longitude, p_latitude))
    RETURNING city_id INTO v_city_id;
    RETURN v_city_id;
END;
$$ LANGUAGE plpgsql;

-- Function: User Dashboard JSONB View
CREATE OR REPLACE FUNCTION user_view_details(p_user_id INTEGER)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'user_id', u.user_id,
        'name', u.name,
        'blood_type', u.blood_type,
        'city_name', COALESCE(c.name, 'Unknown'),
        'dob', u.dob,
        'contact', u.contact,
        'donations', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'blood_id', d.blood_id,
                    'donation_date', d.donation_date,
                    'camp_city', c2.name,
                    'expiry_date', i.expiry_date,
                    'assigned', i.assigned
                ) ORDER BY d.donation_date DESC
            )
            FROM donates d
            LEFT JOIN inventory i ON d.blood_id = i.blood_id
            LEFT JOIN camp ca ON i.camp_id = ca.camp_id
            LEFT JOIN city c2 ON ca.city_id = c2.city_id
            WHERE d.user_id = p_user_id),
            '[]'::jsonb
        ),
        'requests', COALESCE(
            (SELECT jsonb_agg(
                jsonb_build_object(
                    'request_id', r.request_id,
                    'blood_type', r.blood_type,
                    'units_required', r.units_required,
                    'request_date', r.request_date,
                    'status', COALESCE(rs.status, 'no'),
                    'blood_found', COALESCE(rs.blood_found, 'no'),
                    'blood_id', rs.blood_id
                ) ORDER BY r.request_date DESC
            )
            FROM requests r
            LEFT JOIN request_status rs ON r.request_id = rs.request_id
            WHERE r.user_id = p_user_id),
            '[]'::jsonb
        )
    ) INTO v_result
    FROM users u
    LEFT JOIN city c ON u.city_id = c.city_id
    WHERE u.user_id = p_user_id;

    IF v_result IS NULL THEN
        RAISE EXCEPTION 'User ID % not found', p_user_id;
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Function: Add Camp
CREATE OR REPLACE FUNCTION coordinator_add_camp(p_city_id INTEGER, p_start_date DATE, p_end_date DATE)
RETURNS INTEGER AS $$
DECLARE
    v_camp_id INTEGER;
BEGIN
    IF p_end_date < p_start_date THEN
        RAISE EXCEPTION 'End date must be on or after start date';
    END IF;

    INSERT INTO camp (city_id, start_date, end_date)
    VALUES (p_city_id, p_start_date, p_end_date)
    RETURNING camp_id INTO v_camp_id;

    RETURN v_camp_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Registrar Add Request
CREATE OR REPLACE FUNCTION registrar_add_request(p_user_id INTEGER, p_employee_id INTEGER, p_blood_type VARCHAR, p_units_required INTEGER, p_request_date DATE)
RETURNS INTEGER AS $$
DECLARE
    v_request_id INTEGER;
BEGIN
    IF p_units_required <= 0 THEN
        RAISE EXCEPTION 'Units required must be positive';
    END IF;

    IF p_blood_type NOT IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-') THEN
        RAISE EXCEPTION 'Invalid blood type: %', p_blood_type;
    END IF;

    INSERT INTO requests (user_id, employee_id, units_required, blood_type, request_date)
    VALUES (p_user_id, p_employee_id, p_units_required, p_blood_type, p_request_date)
    RETURNING request_id INTO v_request_id;

    RETURN v_request_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Approve or Reject Blood Request
CREATE OR REPLACE FUNCTION process_blood_request(
    p_process_id INT,
    p_action VARCHAR
) RETURNS VOID AS $$
DECLARE
    v_blood_id INT;
BEGIN
    SELECT blood_id INTO v_blood_id
    FROM request_status
    WHERE process_id = p_process_id
    FOR UPDATE;

    IF v_blood_id IS NULL THEN
        RAISE EXCEPTION 'No blood assigned to process_id %', p_process_id;
    END IF;

    IF p_action = 'approve' THEN
        UPDATE inventory
        SET assigned = 'yes'
        WHERE blood_id = v_blood_id;

        UPDATE request_status
        SET status = 'yes',
            blood_found = 'yes',
            date_approved = CURRENT_DATE
        WHERE process_id = p_process_id;
    ELSIF p_action = 'reject' THEN
        UPDATE inventory
        SET assigned = 'no'
        WHERE blood_id = v_blood_id;

        UPDATE request_status
        SET blood_id = NULL,
            status = 'yes',
            blood_found = 'no',
            date_approved = CURRENT_DATE
        WHERE process_id = p_process_id;
    ELSE
        RAISE EXCEPTION 'Invalid action: %. Must be approve or reject.', p_action;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE INDEX IF NOT EXISTS idx_inventory ON inventory (blood_type, expiry_date);
CREATE INDEX IF NOT EXISTS idx_request ON requests (request_id);
CREATE INDEX IF NOT EXISTS idx_users ON users (user_id);

COMMIT;
