
-- Table: positions
CREATE TABLE positions (
    position_id     SERIAL PRIMARY KEY,
    meeting_id      UUID NOT NULL,
    agenda_item_id  VARCHAR(255),  -- Link to specific agenda item to distinguish multiple elections in same meeting
    position_name   VARCHAR(255) NOT NULL,
    is_open         BOOLEAN NOT NULL DEFAULT TRUE,
    poll_id         VARCHAR(36)  -- UUID of the poll in voting service
);

-- Table: nominations
CREATE TABLE nominations (
    position_id     INT NOT NULL,
    username        VARCHAR(255) NOT NULL,
    accepted        BOOLEAN NOT NULL DEFAULT FALSE,

    PRIMARY KEY (position_id, username),

    CONSTRAINT fk_nominations_positions
        FOREIGN KEY (position_id)
            REFERENCES positions(position_id)
            ON DELETE CASCADE
);
