CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE segments (
    id integer PRIMARY KEY,
    name text NOT NULL,
    kind text NOT NULL,
    location geography(Point, 4326) NOT NULL,
    criticality double precision NOT NULL CHECK (criticality BETWEEN 0 AND 1)
);
CREATE INDEX segments_location ON segments USING gist(location);
CREATE TABLE incidents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id integer NOT NULL REFERENCES segments,
    category text NOT NULL CHECK (category IN ('ice', 'snow', 'delay')),
    status text NOT NULL CHECK (status IN ('VERIFYING','ACTIVE','RESOLVED','RECHECK','CLOSED')),
    started_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    resolved_at timestamptz,
    closed_at timestamptz,
    recheck_at timestamptz,
    score double precision NOT NULL DEFAULT 0,
    explanation jsonb NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX one_open_incident ON incidents(segment_id, category) WHERE status <> 'CLOSED';
CREATE TABLE signals (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL,
    external_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    segment_id integer REFERENCES segments,
    incident_id bigint REFERENCES incidents,
    category text NOT NULL,
    text text NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    synthetic boolean NOT NULL,
    UNIQUE(source, external_id)
);
CREATE TABLE context (
    source text NOT NULL,
    segment_id integer NOT NULL REFERENCES segments,
    observed_at timestamptz NOT NULL,
    value double precision NOT NULL CHECK (value BETWEEN 0 AND 1),
    synthetic boolean NOT NULL,
    PRIMARY KEY(source, segment_id)
);
CREATE TABLE source_status (
    source text PRIMARY KEY,
    last_success timestamptz,
    last_error text
);
CREATE TABLE transitions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    incident_id bigint NOT NULL REFERENCES incidents,
    status text NOT NULL,
    changed_at timestamptz NOT NULL,
    reason text NOT NULL
);
