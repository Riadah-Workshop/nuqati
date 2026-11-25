CREATE TABLE public.account_invitations (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone
);

CREATE SEQUENCE public.account_invitations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.account_invitations_id_seq OWNED BY public.account_invitations.id;

CREATE TABLE public.admin_trip_deletion_audit (
    id bigint NOT NULL,
    trip_id integer NOT NULL,
    company_id integer NOT NULL,
    performed_by integer NOT NULL,
    action character varying(24) NOT NULL,
    event_id integer,
    reason text NOT NULL,
    performed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.admin_trip_deletion_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.admin_trip_deletion_audit_id_seq OWNED BY public.admin_trip_deletion_audit.id;

CREATE TABLE public.admin_trip_end_audit (
    id bigint NOT NULL,
    trip_id integer NOT NULL,
    company_id integer NOT NULL,
    performed_by integer NOT NULL,
    reason text NOT NULL,
    performed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.admin_trip_end_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.admin_trip_end_audit_id_seq OWNED BY public.admin_trip_end_audit.id;

CREATE TABLE public.app_settings (
    key character varying(100) NOT NULL,
    value text NOT NULL
);

CREATE TABLE public.auth_attempt_buckets (
    key_hash character varying(64) NOT NULL,
    window_start timestamp with time zone NOT NULL,
    attempts integer NOT NULL,
    blocked_until timestamp with time zone
);

CREATE TABLE public.companies (
    id integer NOT NULL,
    name character varying(160) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.companies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.companies_id_seq OWNED BY public.companies.id;

CREATE TABLE public.company_delete_audit (
    id integer NOT NULL,
    company_id integer NOT NULL,
    company_name character varying(160) NOT NULL,
    actor_user_id integer NOT NULL,
    actor_email character varying(255) NOT NULL,
    backup_reference character varying(255) NOT NULL,
    deleted_counts json NOT NULL,
    deleted_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.company_delete_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.company_delete_audit_id_seq OWNED BY public.company_delete_audit.id;

CREATE TABLE public.company_driving_settings (
    company_id integer NOT NULL,
    speeding_kmh double precision NOT NULL,
    harsh_accel_ms2 double precision NOT NULL,
    harsh_brake_ms2 double precision NOT NULL
);

CREATE TABLE public.company_event_conditions (
    company_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    max_gps_age_seconds double precision NOT NULL,
    max_hdop double precision,
    min_satellites integer,
    max_accuracy_m double precision NOT NULL
);

CREATE TABLE public.dashboard_account_tokens (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    purpose character varying(24) NOT NULL,
    token_hash character varying(64) NOT NULL,
    new_email character varying(255),
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.dashboard_account_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.dashboard_account_tokens_id_seq OWNED BY public.dashboard_account_tokens.id;

CREATE TABLE public.deleted_mobile_trip_clients (
    driver_id integer NOT NULL,
    client_trip_id character varying(90) NOT NULL
);

CREATE TABLE public.driver_accounts (
    id integer NOT NULL,
    driver_id integer NOT NULL,
    user_id integer NOT NULL
);

CREATE SEQUENCE public.driver_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.driver_accounts_id_seq OWNED BY public.driver_accounts.id;

CREATE TABLE public.driver_connection_alerts (
    id bigint NOT NULL,
    driver_id integer NOT NULL,
    company_id integer NOT NULL,
    last_contact_at timestamp with time zone NOT NULL,
    detected_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    resolved_at timestamp with time zone,
    email_sent_at timestamp with time zone,
    email_last_attempt_at timestamp with time zone
);

CREATE SEQUENCE public.driver_connection_alerts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.driver_connection_alerts_id_seq OWNED BY public.driver_connection_alerts.id;

CREATE TABLE public.driver_device_sessions (
    user_id integer NOT NULL,
    device_id character varying(128) NOT NULL,
    session_id character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone NOT NULL
);

CREATE TABLE public.driver_locations (
    id integer NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    trip_id integer NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    accuracy_m double precision NOT NULL,
    speed_kmh double precision NOT NULL,
    recorded_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.driver_locations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.driver_locations_id_seq OWNED BY public.driver_locations.id;

CREATE TABLE public.driver_metadata (
    driver_id integer NOT NULL,
    id_number character varying(40) NOT NULL,
    site_name character varying(160) NOT NULL
);

CREATE TABLE public.driver_privacy_requests (
    id bigint NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reason character varying(500) DEFAULT ''::character varying NOT NULL,
    requested_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    decided_at timestamp with time zone,
    decided_by integer,
    activated_at timestamp with time zone,
    ended_at timestamp with time zone
);

CREATE SEQUENCE public.driver_privacy_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.driver_privacy_requests_id_seq OWNED BY public.driver_privacy_requests.id;

CREATE TABLE public.driver_service_history (
    vehicle_id integer NOT NULL,
    driver_id integer NOT NULL,
    company_id integer NOT NULL,
    service_type character varying(32) NOT NULL,
    knowledge character varying(12) NOT NULL,
    reading_type character varying(12),
    reading_km double precision,
    interval_km double precision,
    submitted_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.drivers (
    id integer NOT NULL,
    company_id integer NOT NULL,
    full_name character varying(160) NOT NULL,
    phone character varying(40) NOT NULL,
    status character varying(20) NOT NULL
);

CREATE SEQUENCE public.drivers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.drivers_id_seq OWNED BY public.drivers.id;

CREATE TABLE public.driving_events (
    id integer NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    trip_id integer NOT NULL,
    event_type character varying(32) NOT NULL,
    value double precision NOT NULL,
    latitude double precision,
    longitude double precision,
    recorded_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.driving_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.driving_events_id_seq OWNED BY public.driving_events.id;

CREATE TABLE public.handover_assignments (
    id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    driver_id integer NOT NULL,
    status character varying(32) NOT NULL,
    receipt_inspection_id integer,
    return_inspection_id integer,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone
);

CREATE SEQUENCE public.handover_assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.handover_assignments_id_seq OWNED BY public.handover_assignments.id;

CREATE TABLE public.handover_audit (
    id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    assignment_id integer,
    actor_user_id integer NOT NULL,
    action character varying(48) NOT NULL,
    detail text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.handover_audit_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.handover_audit_id_seq OWNED BY public.handover_audit.id;

CREATE TABLE public.handover_inspections (
    id integer NOT NULL,
    assignment_id integer NOT NULL,
    company_id integer NOT NULL,
    kind character varying(20) NOT NULL,
    odometer_km double precision NOT NULL,
    engine_status character varying(20) NOT NULL,
    interior_status character varying(20) NOT NULL,
    dashboard_warnings text NOT NULL,
    missing_items json NOT NULL,
    notes text NOT NULL,
    damage_items json NOT NULL,
    discrepancies json NOT NULL,
    driver_acknowledged boolean NOT NULL,
    driver_id integer NOT NULL,
    review_status character varying(20) NOT NULL,
    reviewer_id integer,
    review_note text NOT NULL,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.handover_inspections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.handover_inspections_id_seq OWNED BY public.handover_inspections.id;

CREATE TABLE public.handover_photos (
    id integer NOT NULL,
    inspection_id integer NOT NULL,
    company_id integer NOT NULL,
    category character varying(32) NOT NULL,
    note character varying(240) NOT NULL,
    mime_type character varying(24) NOT NULL,
    sha256 character varying(64) NOT NULL,
    data bytea NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.handover_photos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.handover_photos_id_seq OWNED BY public.handover_photos.id;

CREATE TABLE public.maintenance_schedules (
    id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    service_type character varying(32) NOT NULL,
    interval_km double precision NOT NULL,
    last_service_km double precision NOT NULL,
    warning_before_km double precision NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.maintenance_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.maintenance_schedules_id_seq OWNED BY public.maintenance_schedules.id;

CREATE TABLE public.mobile_diagnostics (
    event_id character varying(64) NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer,
    occurred_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    severity character varying(12) NOT NULL,
    category character varying(24) NOT NULL,
    code character varying(100) NOT NULL,
    detail character varying(450) NOT NULL
);

CREATE TABLE public.mobile_gps_sample_receipts (
    trip_id integer NOT NULL,
    sample_id character varying(80) NOT NULL,
    captured_at timestamp with time zone NOT NULL
);

CREATE TABLE public.mobile_lifecycle_audit (
    event_id character varying(90) NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.mobile_notification_audit (
    event_id character varying(90) NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer,
    notifications_enabled boolean NOT NULL,
    selected_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.mobile_privacy_audit (
    event_id character varying(90) NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer,
    privacy_enabled boolean NOT NULL,
    selected_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.mobile_safety_event_receipts (
    driver_id integer NOT NULL,
    event_id character varying(160) NOT NULL,
    trip_id integer NOT NULL
);

CREATE TABLE public.mobile_safety_observation (
    event_id character varying(90) NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer,
    event_type character varying(50) NOT NULL,
    speed_kmh double precision,
    observed_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.mobile_tracking_heartbeat (
    driver_id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer,
    screen_state character varying(12) NOT NULL,
    trip_active boolean NOT NULL,
    gps_fix_age_s integer,
    captured_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    connectivity_policy_version integer DEFAULT 1 NOT NULL,
    queued_gps_points integer,
    queued_safety_events integer,
    queued_trips integer
);

CREATE TABLE public.mobile_trip_client_ids (
    driver_id integer NOT NULL,
    client_trip_id character varying(90) NOT NULL,
    trip_id integer NOT NULL
);

CREATE TABLE public.mobile_trip_numbers (
    trip_id integer NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    trip_number integer NOT NULL,
    CONSTRAINT mobile_trip_numbers_trip_number_check CHECK ((trip_number > 0))
);

CREATE TABLE public.odometer_readings (
    id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    reading_km double precision NOT NULL,
    source character varying(30) NOT NULL,
    note text NOT NULL,
    created_at timestamp with time zone NOT NULL
);

CREATE SEQUENCE public.odometer_readings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.odometer_readings_id_seq OWNED BY public.odometer_readings.id;

CREATE TABLE public.report_email_subscriptions (
    id bigint NOT NULL,
    company_id integer NOT NULL,
    created_by integer NOT NULL,
    recipient character varying(254) NOT NULL,
    kind character varying(30) NOT NULL,
    frequency character varying(15) NOT NULL,
    scope_type character varying(20) NOT NULL,
    selected_ids text DEFAULT '[]'::text NOT NULL,
    site_name character varying(160),
    weekday integer DEFAULT 0 NOT NULL,
    month_day integer DEFAULT 1 NOT NULL,
    anchor_month integer DEFAULT 1 NOT NULL,
    send_hour integer DEFAULT 9 NOT NULL,
    send_minute integer DEFAULT 0 NOT NULL,
    timezone character varying(80) DEFAULT 'Asia/Riyadh'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    next_send_at timestamp with time zone NOT NULL,
    last_sent_at timestamp with time zone,
    last_error text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.report_email_subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.report_email_subscriptions_id_seq OWNED BY public.report_email_subscriptions.id;

CREATE TABLE public.security_audit (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    actor_user_id integer,
    actor_email character varying(255),
    actor_role character varying(24),
    company_id integer,
    action character varying(64) NOT NULL,
    outcome character varying(12) DEFAULT 'ok'::character varying NOT NULL,
    target_type character varying(32),
    target_id character varying(64),
    ip character varying(64),
    detail text
);

CREATE SEQUENCE public.security_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.security_audit_id_seq OWNED BY public.security_audit.id;

CREATE TABLE public.telematics_devices (
    id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    vendor character varying(20) NOT NULL,
    model character varying(80) NOT NULL,
    imei character varying(20) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen_at timestamp with time zone
);

ALTER TABLE public.telematics_devices ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.telematics_devices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE TABLE public.telematics_points (
    id bigint NOT NULL,
    device_id integer NOT NULL,
    company_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    speed_kmh double precision,
    heading integer,
    satellites integer,
    altitude_m integer,
    ignition boolean,
    accuracy_source character varying(40),
    raw_io text,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE public.telematics_points ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.telematics_points_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

CREATE TABLE public.trips (
    id integer NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone,
    distance_km double precision NOT NULL,
    status character varying(20) NOT NULL
);

CREATE SEQUENCE public.trips_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.trips_id_seq OWNED BY public.trips.id;

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    full_name character varying(160) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role character varying(32) NOT NULL,
    company_id integer,
    is_active boolean NOT NULL,
    auth_version integer NOT NULL
);

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

CREATE TABLE public.vehicles (
    id integer NOT NULL,
    company_id integer NOT NULL,
    plate_number character varying(40) NOT NULL,
    make_model character varying(120) NOT NULL,
    year integer,
    door_number character varying(40),
    assigned_driver_id integer,
    odometer_km double precision
);

CREATE SEQUENCE public.vehicles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.vehicles_id_seq OWNED BY public.vehicles.id;

CREATE TABLE public.workshop_assistance_requests (
    id bigint NOT NULL,
    company_id integer NOT NULL,
    driver_id integer NOT NULL,
    vehicle_id integer,
    category character varying(32) NOT NULL,
    description text NOT NULL,
    latitude double precision,
    longitude double precision,
    location_accuracy_m double precision,
    status character varying(32) DEFAULT 'new'::character varying NOT NULL,
    resolution_note text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.workshop_assistance_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.workshop_assistance_requests_id_seq OWNED BY public.workshop_assistance_requests.id;

ALTER TABLE ONLY public.account_invitations ALTER COLUMN id SET DEFAULT nextval('public.account_invitations_id_seq'::regclass);

ALTER TABLE ONLY public.admin_trip_deletion_audit ALTER COLUMN id SET DEFAULT nextval('public.admin_trip_deletion_audit_id_seq'::regclass);

ALTER TABLE ONLY public.admin_trip_end_audit ALTER COLUMN id SET DEFAULT nextval('public.admin_trip_end_audit_id_seq'::regclass);

ALTER TABLE ONLY public.companies ALTER COLUMN id SET DEFAULT nextval('public.companies_id_seq'::regclass);

ALTER TABLE ONLY public.company_delete_audit ALTER COLUMN id SET DEFAULT nextval('public.company_delete_audit_id_seq'::regclass);

ALTER TABLE ONLY public.dashboard_account_tokens ALTER COLUMN id SET DEFAULT nextval('public.dashboard_account_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.driver_accounts ALTER COLUMN id SET DEFAULT nextval('public.driver_accounts_id_seq'::regclass);

ALTER TABLE ONLY public.driver_connection_alerts ALTER COLUMN id SET DEFAULT nextval('public.driver_connection_alerts_id_seq'::regclass);

ALTER TABLE ONLY public.driver_locations ALTER COLUMN id SET DEFAULT nextval('public.driver_locations_id_seq'::regclass);

ALTER TABLE ONLY public.driver_privacy_requests ALTER COLUMN id SET DEFAULT nextval('public.driver_privacy_requests_id_seq'::regclass);

ALTER TABLE ONLY public.drivers ALTER COLUMN id SET DEFAULT nextval('public.drivers_id_seq'::regclass);

ALTER TABLE ONLY public.driving_events ALTER COLUMN id SET DEFAULT nextval('public.driving_events_id_seq'::regclass);

ALTER TABLE ONLY public.handover_assignments ALTER COLUMN id SET DEFAULT nextval('public.handover_assignments_id_seq'::regclass);

ALTER TABLE ONLY public.handover_audit ALTER COLUMN id SET DEFAULT nextval('public.handover_audit_id_seq'::regclass);

ALTER TABLE ONLY public.handover_inspections ALTER COLUMN id SET DEFAULT nextval('public.handover_inspections_id_seq'::regclass);

ALTER TABLE ONLY public.handover_photos ALTER COLUMN id SET DEFAULT nextval('public.handover_photos_id_seq'::regclass);

ALTER TABLE ONLY public.maintenance_schedules ALTER COLUMN id SET DEFAULT nextval('public.maintenance_schedules_id_seq'::regclass);

ALTER TABLE ONLY public.odometer_readings ALTER COLUMN id SET DEFAULT nextval('public.odometer_readings_id_seq'::regclass);

ALTER TABLE ONLY public.report_email_subscriptions ALTER COLUMN id SET DEFAULT nextval('public.report_email_subscriptions_id_seq'::regclass);

ALTER TABLE ONLY public.security_audit ALTER COLUMN id SET DEFAULT nextval('public.security_audit_id_seq'::regclass);

ALTER TABLE ONLY public.trips ALTER COLUMN id SET DEFAULT nextval('public.trips_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.vehicles ALTER COLUMN id SET DEFAULT nextval('public.vehicles_id_seq'::regclass);

ALTER TABLE ONLY public.workshop_assistance_requests ALTER COLUMN id SET DEFAULT nextval('public.workshop_assistance_requests_id_seq'::regclass);

ALTER TABLE ONLY public.account_invitations
    ADD CONSTRAINT account_invitations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.account_invitations
    ADD CONSTRAINT account_invitations_token_hash_key UNIQUE (token_hash);

ALTER TABLE ONLY public.admin_trip_deletion_audit
    ADD CONSTRAINT admin_trip_deletion_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.admin_trip_end_audit
    ADD CONSTRAINT admin_trip_end_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);

ALTER TABLE ONLY public.auth_attempt_buckets
    ADD CONSTRAINT auth_attempt_buckets_pkey PRIMARY KEY (key_hash);

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.company_delete_audit
    ADD CONSTRAINT company_delete_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.company_driving_settings
    ADD CONSTRAINT company_driving_settings_pkey PRIMARY KEY (company_id);

ALTER TABLE ONLY public.company_event_conditions
    ADD CONSTRAINT company_event_conditions_pkey PRIMARY KEY (company_id, event_type);

ALTER TABLE ONLY public.dashboard_account_tokens
    ADD CONSTRAINT dashboard_account_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.dashboard_account_tokens
    ADD CONSTRAINT dashboard_account_tokens_token_hash_key UNIQUE (token_hash);

ALTER TABLE ONLY public.deleted_mobile_trip_clients
    ADD CONSTRAINT deleted_mobile_trip_clients_pkey PRIMARY KEY (driver_id, client_trip_id);

ALTER TABLE ONLY public.driver_accounts
    ADD CONSTRAINT driver_accounts_driver_id_key UNIQUE (driver_id);

ALTER TABLE ONLY public.driver_accounts
    ADD CONSTRAINT driver_accounts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.driver_accounts
    ADD CONSTRAINT driver_accounts_user_id_key UNIQUE (user_id);

ALTER TABLE ONLY public.driver_connection_alerts
    ADD CONSTRAINT driver_connection_alerts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.driver_device_sessions
    ADD CONSTRAINT driver_device_sessions_pkey PRIMARY KEY (user_id);

ALTER TABLE ONLY public.driver_locations
    ADD CONSTRAINT driver_locations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.driver_metadata
    ADD CONSTRAINT driver_metadata_pkey PRIMARY KEY (driver_id);

ALTER TABLE ONLY public.driver_privacy_requests
    ADD CONSTRAINT driver_privacy_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.driver_service_history
    ADD CONSTRAINT driver_service_history_pkey PRIMARY KEY (vehicle_id, driver_id, service_type);

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.driving_events
    ADD CONSTRAINT driving_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.handover_assignments
    ADD CONSTRAINT handover_assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.handover_audit
    ADD CONSTRAINT handover_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.handover_inspections
    ADD CONSTRAINT handover_inspections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.handover_photos
    ADD CONSTRAINT handover_photos_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.mobile_diagnostics
    ADD CONSTRAINT mobile_diagnostics_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.mobile_gps_sample_receipts
    ADD CONSTRAINT mobile_gps_sample_receipts_pkey PRIMARY KEY (trip_id, sample_id);

ALTER TABLE ONLY public.mobile_lifecycle_audit
    ADD CONSTRAINT mobile_lifecycle_audit_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.mobile_notification_audit
    ADD CONSTRAINT mobile_notification_audit_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.mobile_privacy_audit
    ADD CONSTRAINT mobile_privacy_audit_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.mobile_safety_event_receipts
    ADD CONSTRAINT mobile_safety_event_receipts_pkey PRIMARY KEY (driver_id, event_id);

ALTER TABLE ONLY public.mobile_safety_observation
    ADD CONSTRAINT mobile_safety_observation_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.mobile_tracking_heartbeat
    ADD CONSTRAINT mobile_tracking_heartbeat_pkey PRIMARY KEY (driver_id);

ALTER TABLE ONLY public.mobile_trip_client_ids
    ADD CONSTRAINT mobile_trip_client_ids_pkey PRIMARY KEY (driver_id, client_trip_id);

ALTER TABLE ONLY public.mobile_trip_client_ids
    ADD CONSTRAINT mobile_trip_client_ids_trip_id_key UNIQUE (trip_id);

ALTER TABLE ONLY public.mobile_trip_numbers
    ADD CONSTRAINT mobile_trip_numbers_company_id_driver_id_trip_number_key UNIQUE (company_id, driver_id, trip_number);

ALTER TABLE ONLY public.mobile_trip_numbers
    ADD CONSTRAINT mobile_trip_numbers_pkey PRIMARY KEY (trip_id);

ALTER TABLE ONLY public.odometer_readings
    ADD CONSTRAINT odometer_readings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.report_email_subscriptions
    ADD CONSTRAINT report_email_subscriptions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.security_audit
    ADD CONSTRAINT security_audit_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.telematics_devices
    ADD CONSTRAINT telematics_devices_imei_key UNIQUE (imei);

ALTER TABLE ONLY public.telematics_devices
    ADD CONSTRAINT telematics_devices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.telematics_points
    ADD CONSTRAINT telematics_points_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.trips
    ADD CONSTRAINT trips_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.telematics_points
    ADD CONSTRAINT uq_telematics_point UNIQUE (device_id, recorded_at, latitude, longitude);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_plate_number_key UNIQUE (plate_number);

ALTER TABLE ONLY public.workshop_assistance_requests
    ADD CONSTRAINT workshop_assistance_requests_pkey PRIMARY KEY (id);

CREATE INDEX idx_dashboard_account_tokens_user ON public.dashboard_account_tokens USING btree (user_id, purpose, created_at);

CREATE INDEX idx_mobile_diagnostics_company_time ON public.mobile_diagnostics USING btree (company_id, received_at DESC);

CREATE INDEX idx_security_audit_actor ON public.security_audit USING btree (actor_user_id, created_at DESC);

CREATE INDEX idx_security_audit_company ON public.security_audit USING btree (company_id, created_at DESC);

CREATE INDEX idx_security_audit_time ON public.security_audit USING btree (created_at DESC);

CREATE INDEX idx_telematics_vehicle_time ON public.telematics_points USING btree (vehicle_id, recorded_at DESC);

CREATE INDEX ix_account_invitations_user_id ON public.account_invitations USING btree (user_id);

CREATE INDEX ix_driver_connection_alert_company ON public.driver_connection_alerts USING btree (company_id, detected_at DESC);

CREATE INDEX ix_driver_locations_company_id ON public.driver_locations USING btree (company_id);

CREATE INDEX ix_driver_locations_driver_id ON public.driver_locations USING btree (driver_id);

CREATE INDEX ix_driver_locations_trip_id ON public.driver_locations USING btree (trip_id);

CREATE INDEX ix_driver_privacy_requests_driver ON public.driver_privacy_requests USING btree (driver_id, id DESC);

CREATE INDEX ix_drivers_company_id ON public.drivers USING btree (company_id);

CREATE INDEX ix_driving_events_company_id ON public.driving_events USING btree (company_id);

CREATE INDEX ix_driving_events_driver_id ON public.driving_events USING btree (driver_id);

CREATE INDEX ix_driving_events_trip_id ON public.driving_events USING btree (trip_id);

CREATE INDEX ix_handover_assignments_company_id ON public.handover_assignments USING btree (company_id);

CREATE INDEX ix_handover_assignments_driver_id ON public.handover_assignments USING btree (driver_id);

CREATE INDEX ix_handover_assignments_vehicle_id ON public.handover_assignments USING btree (vehicle_id);

CREATE INDEX ix_handover_audit_company_id ON public.handover_audit USING btree (company_id);

CREATE INDEX ix_handover_audit_vehicle_id ON public.handover_audit USING btree (vehicle_id);

CREATE INDEX ix_handover_inspections_assignment_id ON public.handover_inspections USING btree (assignment_id);

CREATE INDEX ix_handover_inspections_company_id ON public.handover_inspections USING btree (company_id);

CREATE INDEX ix_handover_photos_company_id ON public.handover_photos USING btree (company_id);

CREATE INDEX ix_handover_photos_inspection_id ON public.handover_photos USING btree (inspection_id);

CREATE INDEX ix_maintenance_schedules_company_id ON public.maintenance_schedules USING btree (company_id);

CREATE INDEX ix_maintenance_schedules_vehicle_id ON public.maintenance_schedules USING btree (vehicle_id);

CREATE INDEX ix_odometer_readings_company_id ON public.odometer_readings USING btree (company_id);

CREATE INDEX ix_odometer_readings_vehicle_id ON public.odometer_readings USING btree (vehicle_id);

CREATE INDEX ix_trips_company_id ON public.trips USING btree (company_id);

CREATE INDEX ix_trips_driver_id ON public.trips USING btree (driver_id);

CREATE INDEX ix_trips_vehicle_id ON public.trips USING btree (vehicle_id);

CREATE INDEX ix_users_company_id ON public.users USING btree (company_id);

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);

CREATE INDEX ix_vehicles_company_id ON public.vehicles USING btree (company_id);

CREATE UNIQUE INDEX uq_handover_open_driver ON public.handover_assignments USING btree (driver_id) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'pending_receipt'::character varying, 'pending_return'::character varying])::text[]));

CREATE UNIQUE INDEX uq_handover_open_vehicle ON public.handover_assignments USING btree (vehicle_id) WHERE ((status)::text = ANY ((ARRAY['active'::character varying, 'pending_receipt'::character varying, 'pending_return'::character varying])::text[]));

CREATE UNIQUE INDEX ux_driver_connection_open_alert ON public.driver_connection_alerts USING btree (driver_id) WHERE (resolved_at IS NULL);

ALTER TABLE ONLY public.account_invitations
    ADD CONSTRAINT account_invitations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.company_driving_settings
    ADD CONSTRAINT company_driving_settings_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.company_event_conditions
    ADD CONSTRAINT company_event_conditions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.dashboard_account_tokens
    ADD CONSTRAINT dashboard_account_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.driver_accounts
    ADD CONSTRAINT driver_accounts_driver_id_fkey FOREIGN KEY (driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.driver_accounts
    ADD CONSTRAINT driver_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.driver_device_sessions
    ADD CONSTRAINT driver_device_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.driver_locations
    ADD CONSTRAINT driver_locations_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.driver_locations
    ADD CONSTRAINT driver_locations_driver_id_fkey FOREIGN KEY (driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.driver_locations
    ADD CONSTRAINT driver_locations_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES public.trips(id);

ALTER TABLE ONLY public.driver_metadata
    ADD CONSTRAINT driver_metadata_driver_id_fkey FOREIGN KEY (driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.driving_events
    ADD CONSTRAINT driving_events_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.driving_events
    ADD CONSTRAINT driving_events_driver_id_fkey FOREIGN KEY (driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.driving_events
    ADD CONSTRAINT driving_events_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES public.trips(id);

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.maintenance_schedules
    ADD CONSTRAINT maintenance_schedules_vehicle_id_fkey FOREIGN KEY (vehicle_id) REFERENCES public.vehicles(id);

ALTER TABLE ONLY public.mobile_trip_numbers
    ADD CONSTRAINT mobile_trip_numbers_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES public.trips(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.odometer_readings
    ADD CONSTRAINT odometer_readings_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.odometer_readings
    ADD CONSTRAINT odometer_readings_vehicle_id_fkey FOREIGN KEY (vehicle_id) REFERENCES public.vehicles(id);

ALTER TABLE ONLY public.report_email_subscriptions
    ADD CONSTRAINT report_email_subscriptions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.report_email_subscriptions
    ADD CONSTRAINT report_email_subscriptions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.trips
    ADD CONSTRAINT trips_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.trips
    ADD CONSTRAINT trips_driver_id_fkey FOREIGN KEY (driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.trips
    ADD CONSTRAINT trips_vehicle_id_fkey FOREIGN KEY (vehicle_id) REFERENCES public.vehicles(id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_assigned_driver_id_fkey FOREIGN KEY (assigned_driver_id) REFERENCES public.drivers(id);

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id);
