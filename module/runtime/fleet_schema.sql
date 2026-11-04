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
    review INTEGER NOT NULL CHECK(review IN (0, 1)),
    source TEXT NOT NULL,
    full_star INTEGER CHECK(full_star IN (0, 1)),
    form TEXT CHECK(form IN ('base', 'retrofit'))
) STRICT;

-- Current revisions and a few application settings, without scan history.
CREATE TABLE fleet_info (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    revision TEXT,
    updated_at TEXT NOT NULL DEFAULT '',
    imported_at TEXT,
    technology_initialized INTEGER NOT NULL DEFAULT 0 CHECK(technology_initialized IN (0, 1)),
    pending_revision TEXT,
    pending_source TEXT,
    pending_updated_at TEXT,
    reading_count INTEGER CHECK(reading_count >= 0),
    reading_review_count INTEGER CHECK(reading_review_count >= 0),
    reading_complete INTEGER CHECK(reading_complete IN (0, 1))
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
    review INTEGER NOT NULL CHECK(review IN (0, 1)),
    source TEXT NOT NULL,
    full_star INTEGER CHECK(full_star IN (0, 1)),
    form TEXT CHECK(form IN ('base', 'retrofit'))
) STRICT;

-- JSON imports are normalized before staging. NULL means this import does not
-- propose a change to the milestone, not an unknown saved milestone state.
CREATE TABLE pending_technology (
    group_type TEXT PRIMARY KEY NOT NULL,
    owned INTEGER CHECK(owned IN (0, 1)),
    full_star INTEGER CHECK(full_star IN (0, 1)),
    lv120 INTEGER CHECK(lv120 IN (0, 1))
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

-- Authoritative cumulative account milestones: completed or incomplete.
CREATE TABLE technology_progress (
    group_type TEXT PRIMARY KEY NOT NULL,
    owned INTEGER NOT NULL DEFAULT 0 CHECK(owned IN (0, 1)),
    full_star INTEGER NOT NULL DEFAULT 0 CHECK(full_star IN (0, 1)),
    lv120 INTEGER NOT NULL DEFAULT 0 CHECK(lv120 IN (0, 1)),
    awakening_pending INTEGER NOT NULL DEFAULT 0 CHECK(awakening_pending IN (0, 1)),
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
