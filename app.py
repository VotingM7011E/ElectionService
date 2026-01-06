from flask import Flask, jsonify, request
import random
import requests
import os
import uuid
from sqlalchemy import create_engine, MetaData
from mq import publish_event

app = Flask(__name__)

# Database connection setup
app.config["DATABASE_URL"] = os.getenv("DATABASE_URI")
if not app.config["DATABASE_URL"]:
    raise RuntimeError("DATABASE_URL not set")

engine = create_engine(app.config["DATABASE_URL"])
metadata = MetaData()
metadata.reflect(bind=engine)  # Auto-load existing tables from database

# Get the positions table and nominations table
positions_table = metadata.tables['positions']
nominations_table = metadata.tables['nominations']

@app.route("/")
def root():
    return "ElectionService API running"

def create_poll_in_voting_service(meeting_id, position_name, accepted_candidates):
    """
    Create a poll in the voting service for the accepted candidates.
    Uses RabbitMQ message queue to send the poll creation request.
    Returns the poll_id (UUID) if successful, None otherwise.
    """
    # Generate a unique poll_id
    poll_id = str(uuid.uuid4())
    
    # Prepare the poll data
    vote_data = {
        "meeting_id": meeting_id,
        "poll_id": poll_id,
        "pollType": "single",  # Single choice voting for elections
        "options": accepted_candidates
    }
    
    try:
        # Publish event to RabbitMQ for voting service to consume
        publish_event(
            routing_key="voting.create",
            data={"vote": vote_data}
        )
        
        print(f"Successfully published voting.create event for poll {poll_id} for position '{position_name}'")
        return poll_id
        
    except Exception as e:
        print(f"Error publishing poll creation event: {e}")
        import traceback
        traceback.print_exc()
        return None

#--------------------
# Position Management Service Endpoints
#--------------------

@app.route("/positions", methods=["POST"])
def create_position():
    """
    POST /positions
    Create a new position.
    Request body: {
        "meeting_id": 123,
        "position_name": "President",
        "agenda_item_id": "optional-id-to-link-to-agenda-item"
    }
    """
    # Get data from the request body
    data = request.get_json()
    
    # Extract meeting_id, position_name, and optional agenda_item_id
    meeting_id = data.get('meeting_id')
    position_name = data.get('position_name')
    agenda_item_id = data.get('agenda_item_id')  # Optional: link to specific agenda item

    # Validate required fields
    if meeting_id is None or not position_name:
        return jsonify({"error": "meeting_id and position_name are required"}), 400
    
    # Insert into PostgreSQL database
    with engine.connect() as conn:
        insert_stmt = positions_table.insert().values(
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            position_name=position_name,
            is_open=True
        )
        result = conn.execute(insert_stmt)
        conn.commit()
        
        # Get the auto-generated position_id
        position_id = result.inserted_primary_key[0]

    created_position = {
        "position_id": position_id,
        "meeting_id": meeting_id,  
        "position_name": position_name,
        "is_open": True 
    }

    return jsonify(created_position), 201

@app.route("/positions", methods=["GET"])
def get_positions():
    """
    GET /positions?meeting_id={uuid}&agenda_item_id={id}
    Retrieve positions. Can filter by meeting_id and/or agenda_item_id.
    """
    meeting_id = request.args.get('meeting_id')
    agenda_item_id = request.args.get('agenda_item_id')
    
    with engine.connect() as conn:
        # Build query with optional filters
        select_stmt = positions_table.select()
        
        if meeting_id:
            select_stmt = select_stmt.where(positions_table.c.meeting_id == meeting_id)
        
        if agenda_item_id:
            select_stmt = select_stmt.where(positions_table.c.agenda_item_id == agenda_item_id)
        
        rows = conn.execute(select_stmt).fetchall()
        
        # Convert rows to list of dictionaries
        positions_list = [
            {
                "position_id": row.position_id,
                "meeting_id": row.meeting_id,
                "agenda_item_id": row.agenda_item_id if hasattr(row, 'agenda_item_id') else None,
                "position_name": row.position_name,
                "is_open": row.is_open,
                "poll_id": row.poll_id if hasattr(row, 'poll_id') else None
            }
            for row in rows
        ]

    return jsonify(positions_list), 200

@app.route("/positions/<int:position_id>/close", methods=["POST"])
def close_position(position_id):
    """
    POST /positions/{position_id}/close
    Close a position for nominations and create a poll in voting service.
    """
    with engine.connect() as conn:
        # First, fetch the position to get its details
        select_position_stmt = positions_table.select().where(
            positions_table.c.position_id == position_id
        )
        position = conn.execute(select_position_stmt).fetchone()
        
        if position is None:
            return jsonify({"error": "Could not find position with the provided id"}), 404
        
        if not position.is_open:
            return jsonify({"error": "Position is already closed"}), 400
        
        # Get all accepted nominations for this position
        select_nominations_stmt = nominations_table.select().where(
            (nominations_table.c.position_id == position_id) &
            (nominations_table.c.accepted == True)
        )
        accepted_nominations = conn.execute(select_nominations_stmt).fetchall()
        
        # Check if there are at least 2 accepted candidates
        if len(accepted_nominations) < 2:
            return jsonify({
                "error": "Cannot close position with fewer than 2 accepted candidates. Need at least 2 candidates to create a poll."
            }), 400
        
        # Extract candidate usernames
        accepted_candidates = [nom.username for nom in accepted_nominations]
        
        # Create poll in voting service
        poll_id = create_poll_in_voting_service(
            meeting_id=position.meeting_id,
            position_name=position.position_name,
            accepted_candidates=accepted_candidates
        )
        
        if poll_id is None:
            return jsonify({
                "error": "Failed to create poll in voting service. Position not closed."
            }), 500
        
        # UPDATE the position to set is_open = False and store poll_id
        update_stmt = positions_table.update().where(
            positions_table.c.position_id == position_id
        ).values(
            is_open=False,
            poll_id=poll_id
        )
        conn.execute(update_stmt)
        conn.commit()
        
        # Fetch the updated position to return it
        select_stmt = positions_table.select().where(
            positions_table.c.position_id == position_id
        )
        row = conn.execute(select_stmt).fetchone()
        
        closed_position = {
            "position_id": row.position_id,
            "meeting_id": row.meeting_id,
            "position_name": row.position_name,
            "is_open": row.is_open,
            "poll_id": poll_id,
            "candidates": accepted_candidates
        }

    return jsonify(closed_position), 200

@app.route("/positions/<int:position_id>/nominations", methods=["POST"])
def nominate_candidate(position_id):
    """
    POST /positions/{position_id}/nominations
    Nominate a candidate for a position.
    """
    data = request.get_json()
    username = data.get('username')
    
    # Validate required fields
    if not username:
        return jsonify({"error": "username is required"}), 400
    
    # Insert into nominations_table (not positions_table!)
    with engine.connect() as conn:
        # Check if position exists and is open
        check_stmt = positions_table.select().where(
            positions_table.c.position_id == position_id
        )
        position = conn.execute(check_stmt).fetchone()
        
        if position is None:
            return jsonify({"error": "Could not find position with the provided id"}), 404
        
        if not position.is_open:
            return jsonify({"error": "Position is closed for nominations"}), 400
        
        # Insert the nomination (position_id + username is the primary key)
        insert_stmt = nominations_table.insert().values(
            position_id=position_id,
            username=username,
            accepted=False  # default value
        )
        
        try:
            conn.execute(insert_stmt)
            conn.commit()
        except Exception as e:
            # Handle duplicate nomination (same user, same position)
            return jsonify({"error": "Nomination already exists for this user and position"}), 409

    nomination = {
        "position_id": position_id,
        "username": username, 
        "accepted": False
    }

    return jsonify(nomination), 201

@app.route("/positions/<int:position_id>/nominations", methods=["GET"])
def get_nominations(position_id):
    """
    GET /positions/{position_id}/nominations
    Retrieve all nominations for a position.
    """
    with engine.connect() as conn:
        # Fetch ALL nominations for given position
        select_stmt = nominations_table.select().where(
            nominations_table.c.position_id == position_id
        )
        rows = conn.execute(select_stmt).fetchall()
        
        nominations = [
            {
                "position_id": row.position_id,
                "username": row.username,
                "accepted": row.accepted
            }
            for row in rows
        ]

    return jsonify(nominations), 200

@app.route("/positions/<int:position_id>/nominations/<string:username>/status", methods=["GET"])
def get_nomination_status_for_candidate(position_id, username):
    """
    GET /positions/{position_id}/nominations/{candidate_name}/status
    Retrieve the nomination status for a candidate.
    """
    with engine.connect() as conn:
        # Fetch nomination for given position and candidate
        select_stmt = nominations_table.select().where(
            (nominations_table.c.position_id == position_id) &
            (nominations_table.c.username == username)
        )
        rows = conn.execute(select_stmt).fetchall()
        
        # Convert rows to list of dictionaries
        nominations = [
            {
                "position_id": row.position_id,
                "username": row.username,
                "accepted": row.accepted
            }
            for row in rows
        ]

    return jsonify(nominations), 200

@app.route("/positions/<int:position_id>/nominations/<string:candidate_name>/accept", methods=["POST"])
def accept_nomination(position_id, candidate_name):
    """
    POST /positions/{position_id}/nominations/{candidate_name}/accept
    Accept a candidate's nomination.
    """
    # UPDATE the existing nomination to set accepted = True
    with engine.connect() as conn:
        update_stmt = nominations_table.update().where(
            (nominations_table.c.position_id == position_id) &
            (nominations_table.c.username == candidate_name)
        ).values(
            accepted=True
        )
        result = conn.execute(update_stmt)
        conn.commit()
        
        # Check if nomination was found and updated
        if result.rowcount == 0:
            return jsonify({"error": "Could not find nomination for this candidate and position"}), 404

    accepted_nomination = {
        "position_id": position_id,
        "candidate_name": candidate_name,
        "is_accepted": True
    }

    return jsonify(accepted_nomination), 200


if __name__ == '__main__':
	app.run(host='0.0.0.0', port=80)