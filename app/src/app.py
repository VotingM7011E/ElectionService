from flask import Flask, jsonify, request
import random
import requests
import os
import uuid
from sqlalchemy import create_engine, MetaData

app = Flask(__name__)

# Database connection setup
app.config["DATABASE_URL"] = os.getenv("DATABASE_URL")
if not app.config["DATABASE_URL"]:
    raise RuntimeError("DATABASE_URL not set")

engine = create_engine(app.config["DATABASE_URL"])
metadata = MetaData()
metadata.reflect(bind=engine)  # Auto-load existing tables from database

# Get the positions table and nominations table
positions_table = metadata.tables['positions']
nominations_table = metadata.tables['nominations']

@app.route("/")
def hello_world():
    return "<p>Hello, World! This is the newest version!</p>"

        
def get_meeting_id(meeting_code):
    """Fetch meeting ID from meeting service using the meeting code"""
    # Step 1: Build the full DNS URL to the meeting-service in another namespace
    # Format: http://<service-name>.<namespace>.svc.cluster.local/<endpoint>
    base_url = "http://meeting-service.meeting-service-dev.svc.cluster.local"
    endpoint = f"/code/{meeting_code}"
    full_url = base_url + endpoint
    
    try:
        # Step 2: Make an HTTP GET request to the meeting-service API
        # timeout=5 means wait max 5 seconds for a response
        response = requests.get(full_url, timeout=5)
        
        # Step 3: Check if the request was successful (status code 200-299)
        # Raises an HTTPError if status code indicates failure (4xx or 5xx)
        response.raise_for_status()
        
        # Step 4: Parse the JSON response from the meeting-service
        # Assumes the response looks like: {"meeting_id": 123, "meeting_code": "ABC123", ...}
        meeting_data = response.json()
        
        # Step 5: Extract the meeting_id from the response data
        # Use .get() to safely access the key (returns None if key doesn't exist)
        meeting_id = meeting_data.get('meeting_id')
        
        # Step 6: Return the meeting_id to the caller
        return meeting_id
        
    except requests.exceptions.Timeout:
        # Step 7a: Handle case where the request takes too long
        print(f"Timeout: meeting-service did not respond within 5 seconds")
        return None
        
    except requests.exceptions.ConnectionError:
        # Step 7b: Handle case where we can't reach the meeting-service
        # This could mean DNS failed, service is down, or network issue
        print(f"Connection error: Could not reach meeting-service")
        return None
        
    except requests.exceptions.HTTPError as e:
        # Step 7c: Handle HTTP errors (404 Not Found, 500 Internal Server Error, etc.)
        print(f"HTTP error: {e.response.status_code} - {e}")
        return None
        
    except requests.exceptions.RequestException as e:
        # Step 7d: Catch-all for any other request-related errors
        print(f"Error fetching meeting_id: {e}")
        return None

def create_poll_in_voting_service(meeting_id, position_name, accepted_candidates):
    """
    Create a poll in the voting service for the accepted candidates.
    Returns the poll_id (UUID) if successful, None otherwise.
    """
    # Generate a unique poll_id
    poll_id = str(uuid.uuid4())
    
    # Build the voting service URL
    base_url = "http://voting-service.voting-service-dev.svc.cluster.local"
    endpoint = "/polls/"
    full_url = base_url + endpoint
    
    # Prepare the poll data
    poll_data = {
        "vote": {
            "meeting_id": meeting_id,
            "poll_id": poll_id,
            "pollType": "single",  # Single choice voting for elections
            "options": accepted_candidates
        }
    }
    
    try:
        # Make POST request to voting service
        response = requests.post(full_url, json=poll_data, timeout=5)
        response.raise_for_status()
        
        print(f"Successfully created poll {poll_id} for position '{position_name}'")
        return poll_id
        
    except requests.exceptions.Timeout:
        print(f"Timeout: voting-service did not respond within 5 seconds")
        return None
        
    except requests.exceptions.ConnectionError:
        print(f"Connection error: Could not reach voting-service")
        return None
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error from voting-service: {e.response.status_code} - {e}")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error creating poll in voting-service: {e}")
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
        "meeting_code": "ABC123",
        "position_name": "President"
    }
    """
    # Get data from the request body
    data = request.get_json()
    
    # Extract meeting_code and position_name from request
    meeting_code = data.get('meeting_code')
    position_name = data.get('position_name')
    
    # Validate required fields
    if not meeting_code or not position_name:
        return jsonify({"error": "meeting_code and position_name are required"}), 400
    
    # Fetch the meeting_id from meeting-service using the meeting_code
    meeting_id = get_meeting_id(meeting_code)
    
    # Check if meeting_id was successfully retrieved
    if meeting_id is None:
        return jsonify({"error": "Could not find meeting with the provided code"}), 404
    
    # Insert into PostgreSQL database
    with engine.connect() as conn:
        insert_stmt = positions_table.insert().values(
            meeting_id=meeting_id,
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
    GET /positions
    Retrieve all open positions.
    """
    with engine.connect() as conn:
        # Fetch ALL open positions
        select_stmt = positions_table.select().where(
            positions_table.c.is_open == True
        )
        rows = conn.execute(select_stmt).fetchall()
        
        # Convert rows to list of dictionaries
        open_positions = [
            {
                "position_id": row.position_id,
                "meeting_id": row.meeting_id,
                "position_name": row.position_name,
                "is_open": row.is_open,
                "poll_id": row.poll_id if hasattr(row, 'poll_id') else None
            }
            for row in rows
        ]

    return jsonify(open_positions), 200

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