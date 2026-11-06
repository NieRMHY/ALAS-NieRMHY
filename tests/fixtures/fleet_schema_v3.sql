-- Current fleet ledger. Each row in ships is one card, including duplicate names.
CREATE TABLE ships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position INTEGER NOT NULL UNIQUE CHECK(position >= 0),
    group_type INTEGER,
    name TEXT NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 125),
    rarity TEXT NOT NULL,
    base_rarity TEXT NOT NULL,
    extra_exp INTEGER CHECK(extra_exp >= 0),
    excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0, 1)),
    review INTEGER NOT NULL CHECK(review IN (0, 1)),
    source TEXT NOT NULL
) STRICT;

-- Current revisions and a few application settings, without scan history.
CREATE TABLE fleet_info (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    revision TEXT,
    updated_at TEXT NOT NULL DEFAULT '',
    imported_at TEXT,
    technology_fields INTEGER NOT NULL DEFAULT 0,
    pending_revision TEXT,
    pending_source TEXT,
    pending_updated_at TEXT
) STRICT;

-- One row per ship TYPE. NULL manual columns may mean an explicit blank, so
-- manual_fields records which overrides are present: bit 0 = manual row exists,
-- bits 1..5 = owned, full_star, lv120, level, level_toggle.
CREATE TABLE technology (
    group_type TEXT PRIMARY KEY NOT NULL,
    max_observed_level INTEGER CHECK(max_observed_level BETWEEN 1 AND 125),
    manual_fields INTEGER NOT NULL DEFAULT 0,
    owned INTEGER CHECK(owned IN (0, 1)),
    full_star INTEGER CHECK(full_star IN (0, 1)),
    lv120 INTEGER CHECK(lv120 IN (0, 1)),
    level INTEGER CHECK(level BETWEEN 1 AND 125),
    low_level INTEGER CHECK(low_level BETWEEN 1 AND 119),
    high_level INTEGER CHECK(high_level BETWEEN 120 AND 125)
) STRICT;

CREATE TABLE nation_technology (
    nation_key TEXT PRIMARY KEY NOT NULL,
    level INTEGER CHECK(level >= 0)
) STRICT;

-- Only the latest unreviewed reading, deleted as decisions are made.
CREATE TABLE pending_ships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL CHECK(operation IN ('add', 'update', 'remove', 'resolve')),
    ship_id INTEGER,
    fields INTEGER NOT NULL,
    group_type INTEGER,
    name TEXT NOT NULL,
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 125),
    rarity TEXT NOT NULL,
    base_rarity TEXT NOT NULL,
    extra_exp INTEGER CHECK(extra_exp >= 0),
    excluded INTEGER NOT NULL CHECK(excluded IN (0, 1)),
    review INTEGER NOT NULL CHECK(review IN (0, 1)),
    source TEXT NOT NULL
) STRICT;

CREATE TABLE pending_technology (
    group_type TEXT PRIMARY KEY NOT NULL,
    max_observed_level INTEGER CHECK(max_observed_level BETWEEN 1 AND 125),
    manual_fields INTEGER NOT NULL DEFAULT 0,
    owned INTEGER CHECK(owned IN (0, 1)),
    full_star INTEGER CHECK(full_star IN (0, 1)),
    lv120 INTEGER CHECK(lv120 IN (0, 1)),
    level INTEGER CHECK(level BETWEEN 1 AND 125),
    low_level INTEGER CHECK(low_level BETWEEN 1 AND 119),
    high_level INTEGER CHECK(high_level BETWEEN 120 AND 125)
) STRICT;

-- Eligible unmatched copies for a duplicate-identity decision. Consumed targets
-- are removed immediately, including when decisions are made in separate calls.
CREATE TABLE pending_targets (
    proposal_id INTEGER NOT NULL REFERENCES pending_ships(id) ON DELETE CASCADE,
    ship_id INTEGER NOT NULL REFERENCES ships(id) ON DELETE CASCADE,
    PRIMARY KEY(proposal_id, ship_id)
) STRICT;

CREATE TABLE pending_nations (
    nation_key TEXT PRIMARY KEY NOT NULL,
    level INTEGER CHECK(level >= 0)
) STRICT;
