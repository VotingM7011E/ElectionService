
CREATE TABLE position (
    position_id     SERIAL PRIMARY KEY,
    meeting_id      INT NOT NULL,
    position_name   VARCHAR(255) NOT NULL,
    description     TEXT,
    CONSTRAINT fk_position_meeting
        FOREIGN KEY (meeting_id) REFERENCES meeting(meeting_id)
        ON DELETE CASCADE
);