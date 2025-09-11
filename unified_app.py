from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify, send_from_directory, session
import os
import json
from datetime import date, datetime
from werkzeug.utils import secure_filename
import threading
import time
import uuid
import zipfile
import io
import pandas as pd
import multiprocessing
import logging
from typing import Dict
import hashlib
import secrets

# Import the existing modules - these need to be copied from your LAweb app
try:
    from modern_analyzer_bridge import process_location_file  # Use modern analyzer
    from geo_utils import geo_cache, save_geo_cache, load_cache
    from csv_exporter import export_monthly_csv
    ANALYZER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import analyzer modules: {e}")
    print("Make sure to copy modern_analyzer_bridge.py, geo_utils.py, and csv_exporter.py from your LAweb app")
    ANALYZER_AVAILABLE = False

from functools import wraps

def require_login(f):
    """Decorator to require user login for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = secrets.token_hex(32)  # Generate a secure secret key
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSED_FOLDER'] = 'processed'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# User management functions
def load_users():
    users_file = 'config/users.json'
    try:
        with open(users_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Create empty users file if it doesn't exist
        os.makedirs('config', exist_ok=True)
        with open(users_file, 'w') as f:
            json.dump({}, f)
        return {}

def save_users(users):
    with open('config/users.json', 'w') as f:
        json.dump(users, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_user_config(username):
    """Load user-specific configuration, with migration from legacy config"""
    user_config_file = f"config/users/{username}/config.json"
    
    # Start with default config
    config = {
        'distance_threshold': 200,
        'probability_threshold': 0.1,
        'duration_threshold': 600,
        'last_start_date': '2024-01-01',
        'last_end_date': date.today().strftime('%Y-%m-%d'),
        'geoapify_key': '',
        'google_key': ''
    }
    
    # Try to load user's saved config
    if os.path.exists(user_config_file):
        try:
            with open(user_config_file, "r") as f:
                user_saved_config = json.load(f)
                config.update(user_saved_config)
        except Exception as e:
            print(f"Warning: Failed to load user config for {username}: {e}")
    else:
        # First time for this user - check if there's a legacy global config to migrate from
        if os.path.exists("config/unified_config.json"):
            try:
                with open("config/unified_config.json", "r") as f:
                    legacy_config = json.load(f)
                    # Copy non-API settings from legacy config
                    for key in ['distance_threshold', 'probability_threshold', 'duration_threshold', 
                               'last_start_date', 'last_end_date']:
                        if key in legacy_config:
                            config[key] = legacy_config[key]
                print(f"Migrated settings from legacy config for user {username}")
            except:
                pass
    
    # Load user's API keys from users.json (these override config file)
    users = load_users()
    if username in users:
        user_keys = users[username].get('api_keys', {})
        if user_keys.get('geoapify'):
            config['geoapify_key'] = user_keys['geoapify']
        if user_keys.get('google'):
            config['google_key'] = user_keys['google']
    
    return config

def save_user_config(username, config):
    """Save user-specific configuration"""
    user_config_dir = f"config/users/{username}"
    user_config_file = f"{user_config_dir}/config.json"
    
    # Create user config directory if it doesn't exist
    os.makedirs(user_config_dir, exist_ok=True)
    
    try:
        # Don't save API keys to config file (they're in users.json)
        config_to_save = {k: v for k, v in config.items() 
                         if k not in ['geoapify_key', 'google_key']}
        
        with open(user_config_file, "w") as f:
            json.dump(config_to_save, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save user config for {username}: {e}")

def load_config():
    """Load configuration - now user-aware but maintains backward compatibility"""
    if 'user' in session:
        return load_user_config(session['user'])
    else:
        # For non-authenticated requests or migration, load the old global config
        config_file = "config/unified_config.json"
        config = {}
        
        # Try to load existing unified config
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load unified config: {e}")
        
        # Merge settings from parser app
        parser_settings = "settings.json"
        if os.path.exists(parser_settings):
            try:
                with open(parser_settings, "r") as f:
                    parser_config = json.load(f)
                    config.setdefault('distance_threshold', parser_config.get('distance_threshold', 200))
                    config.setdefault('probability_threshold', parser_config.get('probability_threshold', 0.1))
                    config.setdefault('duration_threshold', parser_config.get('duration_threshold', 600))
                    config.setdefault('last_start_date', parser_config.get('from_date', ''))
                    config.setdefault('last_end_date', parser_config.get('to_date', ''))
            except Exception as e:
                print(f"Warning: Failed to merge parser settings: {e}")
        
        # Merge settings from LAweb app
        laweb_config = "config/web_config.json"
        if os.path.exists(laweb_config):
            try:
                with open(laweb_config, "r") as f:
                    laweb_settings = json.load(f)
                    config.setdefault('geoapify_key', laweb_settings.get('geoapify_key', ''))
                    config.setdefault('google_key', laweb_settings.get('google_key', ''))
                    if not config.get('last_start_date'):
                        config['last_start_date'] = laweb_settings.get('last_start_date', '')
                    if not config.get('last_end_date'):
                        config['last_end_date'] = laweb_settings.get('last_end_date', '')
            except Exception as e:
                print(f"Warning: Failed to merge LAweb settings: {e}")
        
        # Set defaults
        config.setdefault('distance_threshold', 200)
        config.setdefault('probability_threshold', 0.1)
        config.setdefault('duration_threshold', 600)
        config.setdefault('last_start_date', '2024-01-01')
        config.setdefault('last_end_date', date.today().strftime('%Y-%m-%d'))
        config.setdefault('geoapify_key', '')
        config.setdefault('google_key', '')
        
        return config
def load_user_geo_cache(username):
    """Load user-specific geocoding cache"""
    cache_file = f"config/users/{username}/geo_cache.json"
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_user_geo_cache(username, cache_data):
    """Save user-specific geocoding cache"""
    user_config_dir = f"config/users/{username}"
    cache_file = f"{user_config_dir}/geo_cache.json"
    
    os.makedirs(user_config_dir, exist_ok=True)
    
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)
    except Exception as e:
        print(f"Warning: Failed to save geo cache for {username}: {e}")

def get_cache_stats_for_user(username):
    """Get geocoding cache statistics for a specific user"""
    cache_file = f"config/users/{username}/geo_cache.json"
    
    try:
        if os.path.exists(cache_file):
            file_size = os.path.getsize(cache_file)
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                return {
                    'entries': len(cache_data),
                    'file_size_kb': round(file_size / 1024, 1)
                }
    except:
        pass
    
    return {'entries': 0, 'file_size_kb': 0}

def get_user_files_only(username):
    """Get files only for the specified user - CRITICAL FIX"""
    user_uploads_path = os.path.join(app.config['UPLOAD_FOLDER'], username)
    user_processed_path = os.path.join(app.config['PROCESSED_FOLDER'], username)
    
    files_info = {'master_files': [], 'parsed_files': []}
    
    # Ensure user directories exist
    os.makedirs(user_uploads_path, exist_ok=True)
    os.makedirs(user_processed_path, exist_ok=True)
    
    # Get master files from user's upload directory ONLY
    if os.path.exists(user_uploads_path):
        for filename in os.listdir(user_uploads_path):
            if filename.endswith('.json'):
                file_path = os.path.join(user_uploads_path, filename)
                file_stat = os.stat(file_path)
                files_info['master_files'].append({
                    'filename': filename,
                    'path': file_path,
                    'size': file_stat.st_size,
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    
    # Get parsed files from user's processed directory ONLY
    if os.path.exists(user_processed_path):
        for filename in os.listdir(user_processed_path):
            if filename.endswith('.json'):
                file_path = os.path.join(user_processed_path, filename)
                file_stat = os.stat(file_path)
                files_info['parsed_files'].append({
                    'filename': filename,
                    'path': file_path,
                    'size': file_stat.st_size,
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    
    return files_info


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Ensure directories exist
for folder in ['uploads', 'processed', 'outputs', 'config']:
    os.makedirs(folder, exist_ok=True)

# Global storage for unified analysis progress - now user-specific
def get_user_progress():
    """Get user-specific progress tracking"""
    if 'user' not in session:
        return {}
    if 'unified_progress' not in globals():
        globals()['unified_progress'] = {}
    if session['user'] not in unified_progress:
        unified_progress[session['user']] = {}
    return unified_progress[session['user']]

def set_user_progress(task_id, data):
    """Set user-specific progress"""
    if 'user' not in session:
        return
    user_progress = get_user_progress()
    user_progress[task_id] = data

# Initialize global progress tracking
unified_progress = {}

# Progress tracking for parser (extracted from parser_app.py)
parser_progress_store = {}

def update_progress(task_id: str, message: str, percentage: float = None):
    """Store progress update for web interface."""
    if task_id not in parser_progress_store:
        parser_progress_store[task_id] = {}
    
    parser_progress_store[task_id].update({
        'message': message,
        'percentage': percentage or 0,
        'timestamp': datetime.now().isoformat(),
        'diagnostics': parser_progress_store[task_id].get('diagnostics', [])
    })

def add_diagnostic(task_id: str, message: str, level: str = "INFO"):
    """Add diagnostic message to progress store only."""
    if task_id in parser_progress_store:
        diagnostics = parser_progress_store[task_id].get('diagnostics', [])
        diagnostics.append({
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'level': level,
            'message': message
        })
        # Keep only last 100 messages
        parser_progress_store[task_id]['diagnostics'] = diagnostics[-100:]

# Add these three helper functions right after your imports section
def generate_readable_filename(from_date, to_date, distance, probability, duration):
    """Generate human-readable filename for parsed files"""
    from_str = datetime.strptime(from_date, '%Y-%m-%d').strftime('%m-%d-%y')
    to_str = datetime.strptime(to_date, '%Y-%m-%d').strftime('%m-%d-%y')
    filename = f"{from_str}__{to_str}_parsed_{int(distance)}_{probability}_{int(duration)}.json"
    return filename

def save_parsed_with_proper_formatting(filepath, data):
    """Save JSON with proper formatting and line endings"""
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        if os.name == 'nt':  # Windows
            json_str = json_str.replace('\n', '\r\n')
        f.write(json_str)

def add_metadata_to_parsed(data, settings, stats):
    """Add metadata to parsed file for easy identification"""
    metadata = {
        "_metadata": {
            "version": "1.0",
            "parsedAt": datetime.now().isoformat(),
            "dateRange": {
                "from": settings['from_date'],
                "to": settings['to_date']
            },
            "filterSettings": {
                "distanceThreshold": settings['distance_threshold'],
                "probabilityThreshold": settings['probability_threshold'],
                "durationThreshold": settings['duration_threshold']
            },
            "statistics": stats,
            "isParsed": True
        }
    }
    
    if isinstance(data, list):
        return {"_metadata": metadata["_metadata"], "timelineObjects": data}
    else:
        return {**metadata, **data}

class LocationProcessor:
    """Production-ready location processor with optimized timeline handling."""
    
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.stats = {
            'total_entries': 0,
            'date_filtered': 0,
            'activities': 0,
            'visits': 0,
            'timeline_paths': 0,
            'final_count': 0
        }
    
    def log(self, message: str, level: str = "INFO"):
        """Log message to file and add to diagnostics."""
        print(f"[{level}] {message}")  # Console logging
        add_diagnostic(self.task_id, message, level)
    
    def progress(self, message: str, percentage: float = None):
        """Update progress."""
        update_progress(self.task_id, message, percentage)
        self.log(f"PROGRESS: {message}")
    
    def generate_standard_format(self, entries, settings):
        """Generate standard Google location history format for 3rd party compatibility
        
        Key principles:
        1. Keep ALL numeric values as strings (Google's original format)
        2. Return direct array, not wrapped in object
        3. Preserve exact field names and structure from Google exports
        """
        standard_entries = []
        
        for entry in entries:
            try:
                # Convert back to standard format
                standard_entry = {}
                
                # Copy basic timing exactly as-is (already strings in proper format)
                if 'startTime' in entry:
                    standard_entry['startTime'] = entry['startTime']
                if 'endTime' in entry:
                    standard_entry['endTime'] = entry['endTime']
                
                # Handle activity entries
                if 'activity' in entry:
                    activity = entry['activity']
                    standard_entry['activity'] = {
                        'start': activity.get('start', ''),
                        'end': activity.get('end', ''),
                        # CRITICAL: Keep as string, don't convert to int
                        'distanceMeters': str(activity.get('distanceMeters', '0')),
                        'topCandidate': {
                            'type': activity.get('topCandidate', {}).get('type', 'unknown'),
                            # CRITICAL: Keep as string, don't convert to float
                            'probability': str(activity.get('topCandidate', {}).get('probability', '0'))
                        },
                        # CRITICAL: Keep as string, don't convert to float
                        'probability': str(activity.get('probability', '0'))
                    }
                
                # Handle visit entries
                elif 'visit' in entry:
                    visit = entry['visit']
                    standard_entry['visit'] = {
                        'topCandidate': {
                            'placeLocation': visit['topCandidate'].get('placeLocation', ''),
                            'semanticType': visit['topCandidate'].get('semanticType', 'Unknown'),
                            # CRITICAL: Keep as string, don't convert to float
                            'probability': str(visit['topCandidate'].get('probability', '0'))
                        },
                        # CRITICAL: Keep as string, don't convert to float
                        'probability': str(visit.get('probability', '0'))
                    }
                    
                    # Add optional fields if present (preserve as-is)
                    if 'placeID' in visit['topCandidate']:
                        standard_entry['visit']['topCandidate']['placeID'] = visit['topCandidate']['placeID']
                
                # Handle timeline path entries
                elif 'timelinePath' in entry:
                    standard_entry['timelinePath'] = []
                    for point in entry['timelinePath']:
                        standard_point = {
                            'point': point.get('point', ''),
                            # CRITICAL: Keep as string
                            'durationMinutesOffsetFromStartTime': str(point.get('durationMinutesOffsetFromStartTime', '0')),
                            'mode': point.get('mode', 'unknown')
                        }
                        standard_entry['timelinePath'].append(standard_point)
                
                standard_entries.append(standard_entry)
                
            except Exception as e:
                self.log(f"Warning: Could not convert entry to standard format: {e}", "WARN")
                continue
        
        # OPTION 1: Return direct array (like one.json)
        # This is what most 3rd party tools expect
        return standard_entries
        
        # OPTION 2: Return wrapped format (like two.json structure)
        # Uncomment this line and comment the return above if tools expect wrapper
        # return {'timelineObjects': standard_entries}


    def parse_timestamp(self, timestamp_input):
        """Parse timestamp from any Google format."""
        if not timestamp_input:
            return None
        
        try:
            if isinstance(timestamp_input, str):
                return pd.to_datetime(timestamp_input, utc=True)
            elif isinstance(timestamp_input, (int, float)):
                timestamp_str = str(int(timestamp_input))
                if len(timestamp_str) == 13:  # milliseconds
                    return pd.to_datetime(timestamp_input, unit='ms', utc=True)
                elif len(timestamp_str) == 10:  # seconds
                    return pd.to_datetime(timestamp_input, unit='s', utc=True)
            return None
        except:
            return None
    
    def parse_coordinates(self, coord_input):
        """Parse coordinates from any Google format."""
        if not coord_input:
            return None
        
        try:
            # geo: string format
            if isinstance(coord_input, str):
                if coord_input.startswith('geo:'):
                    coords = coord_input.replace('geo:', '').split(',')
                    if len(coords) == 2:
                        lat, lon = float(coords[0]), float(coords[1])
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            return lat, lon
            
            # Object formats
            elif isinstance(coord_input, dict):
                # E7 format
                if 'latitudeE7' in coord_input and 'longitudeE7' in coord_input:
                    lat = float(coord_input['latitudeE7']) / 10000000
                    lon = float(coord_input['longitudeE7']) / 10000000
                    return lat, lon
                
                # Decimal degrees
                elif 'latitude' in coord_input and 'longitude' in coord_input:
                    lat = float(coord_input['latitude'])
                    lon = float(coord_input['longitude'])
                    return lat, lon
            
            return None
        except:
            return None
    
    @staticmethod
    def calculate_distance(coords1, coords2):
        """Calculate distance between two coordinate points in meters."""
        from math import radians, cos, sin, asin, sqrt
        
        lat1, lon1 = coords1
        lat2, lon2 = coords2
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371  # Earth radius in kilometers
        return c * r * 1000  # Convert to meters

    def extract_timestamp_fast(self, entry):
        """Fast timestamp extraction for date filtering."""
        try:
            # Direct timestamp
            if 'startTime' in entry:
                return pd.to_datetime(entry['startTime'], utc=True)
            
            # Activity/visit nested
            if 'activity' in entry and 'startTime' in entry['activity']:
                return pd.to_datetime(entry['activity']['startTime'], utc=True)
            if 'visit' in entry and 'startTime' in entry['visit']:
                return pd.to_datetime(entry['visit']['startTime'], utc=True)
            
            # Legacy format
            if 'timestampMs' in entry:
                return pd.to_datetime(int(entry['timestampMs']), unit='ms', utc=True)
            
            return None
        except:
            return None

    def fast_date_filter(self, entries, from_dt, to_dt):
        """Filter entries by date range - fast version based on working test."""
        self.progress(f"Date filtering {len(entries):,} entries...", 20)
        
        relevant_entries = []
        
        # Year pre-filtering for speed
        start_year = from_dt.year
        end_year = to_dt.year
        
        entries_checked = 0
        
        for entry in entries:
            entries_checked += 1
            
            # Get timestamp string for year check
            timestamp_str = None
            
            if 'startTime' in entry:
                timestamp_str = entry['startTime']
            elif 'activity' in entry and isinstance(entry['activity'], dict) and 'startTime' in entry['activity']:
                timestamp_str = entry['activity']['startTime']
            elif 'visit' in entry and isinstance(entry['visit'], dict) and 'startTime' in entry['visit']:
                timestamp_str = entry['visit']['startTime']
            
            if timestamp_str:
                # Quick year check first
                if len(timestamp_str) >= 4:
                    try:
                        year = int(timestamp_str[:4])
                        if year < start_year or year > end_year:
                            continue  # Skip entries outside year range
                    except:
                        pass
                
                # Full timestamp check for entries in the right year
                timestamp = self.extract_timestamp_fast(entry)
                if timestamp and from_dt <= timestamp < to_dt:
                    relevant_entries.append(entry)
            
            # Progress updates
            if entries_checked % 10000 == 0:
                progress_pct = 20 + (entries_checked / len(entries)) * 30
                self.progress(f"Date filtering: {len(relevant_entries):,} found from {entries_checked:,} checked", progress_pct)
        
        self.stats['date_filtered'] = len(relevant_entries)
        self.log(f"Date filtering complete: {len(relevant_entries):,} entries in date range")
        
        return relevant_entries

    def sample_points(self, points: list, max_points: int) -> list:
        """Sample points evenly, always preserving first and last points."""
        if len(points) <= max_points:
            return points
        
        if max_points < 2:
            return [points[0]]  # At least keep the first point
        
        sampled = [points[0]]  # Always keep first point
        
        if max_points > 2:
            # Calculate indices for middle points
            middle_count = max_points - 2
            if middle_count > 0:
                # Create evenly spaced indices between first and last
                step_size = (len(points) - 1) / (middle_count + 1)
                for i in range(1, middle_count + 1):
                    index = int(round(i * step_size))
                    if index < len(points) - 1:  # Don't duplicate the last point
                        sampled.append(points[index])
        
        # Always keep last point (unless it's the same as first)
        if len(points) > 1:
            sampled.append(points[-1])
        
        return sampled

    def process_entry(self, entry: dict, settings: dict):
        """Process a single entry based on its type."""
        try:
            # Determine entry type and extract data
            if 'activity' in entry:
                return self.process_activity(entry, settings)
            elif 'visit' in entry:
                return self.process_visit(entry, settings)
            elif 'timelinePath' in entry:
                return self.process_timeline_path(entry, settings)
            elif 'timestampMs' in entry:
                return self.process_legacy_location(entry, settings)
            else:
                return None
        except Exception as e:
            return None
    
    def process_activity(self, entry: dict, settings: dict):
        """Process activity entry."""
        try:
            activity = entry['activity']
            
            # Get coordinates
            start_coords = self.parse_coordinates(activity.get('start'))
            end_coords = self.parse_coordinates(activity.get('end'))
            if not start_coords or not end_coords:
                return None
            
            # Check distance threshold
            distance = float(activity.get('distanceMeters', 0))
            if distance < settings.get('distance_threshold', 200):
                return None
            
            self.stats['activities'] += 1
            return {
                'startTime': entry['startTime'],
                'endTime': entry['endTime'],
                'activity': {
                    'start': f"geo:{start_coords[0]:.6f},{start_coords[1]:.6f}",
                    'end': f"geo:{end_coords[0]:.6f},{end_coords[1]:.6f}",
                    'distanceMeters': str(int(distance)),
                    'topCandidate': activity.get('topCandidate', {}),
                    'probability': str(activity.get('probability', 0.0))
                }
            }
        except:
            return None
    
    def process_visit(self, entry: dict, settings: dict):
        """Process visit entry."""
        try:
            visit = entry['visit']
            
            # Get coordinates
            coords = None
            if 'topCandidate' in visit and 'placeLocation' in visit['topCandidate']:
                coords = self.parse_coordinates(visit['topCandidate']['placeLocation'])
            if not coords:
                return None
            
            # Check duration threshold
            start_dt = self.parse_timestamp(entry['startTime'])
            end_dt = self.parse_timestamp(entry['endTime'])
            if start_dt and end_dt:
                duration = (end_dt - start_dt).total_seconds()
                if duration < settings.get('duration_threshold', 600):
                    return None
            
            # Check probability threshold
            probability = float(visit.get('probability', 0.0))
            if probability < settings.get('probability_threshold', 0.1):
                return None
            
            # Preserve all original visit fields
            top_candidate = visit.get('topCandidate', {})
            result = {
                'startTime': entry['startTime'],
                'endTime': entry['endTime'],
                'visit': {
                    'topCandidate': {
                        'placeLocation': f"geo:{coords[0]:.6f},{coords[1]:.6f}",
                        'probability': str(top_candidate.get('probability', probability))
                    },
                    'probability': str(probability)
                }
            }
            
            # Add optional fields if they exist
            if 'placeID' in top_candidate:
                result['visit']['topCandidate']['placeID'] = top_candidate['placeID']
            if 'semanticType' in top_candidate:
                result['visit']['topCandidate']['semanticType'] = top_candidate['semanticType']
            
            self.stats['visits'] += 1
            return result
        except:
            return None
    
    # Add improved parser code 9_11
    def get_point_timestamp(self, entry_start_time, duration_offset_minutes):
        """Calculate the actual timestamp for a timeline point"""
        start_dt = self.parse_timestamp(entry_start_time)
        if not start_dt:
            return None
        offset_minutes = int(duration_offset_minutes) if duration_offset_minutes else 0
        return start_dt + pd.Timedelta(minutes=offset_minutes)

    def process_timeline_path(self, entry: dict, settings: dict):
        """Process timeline path entry with correct timestamp filtering for each point."""
        try:
            timeline_path = entry.get('timelinePath', [])
            if not timeline_path:
                return None
            
            distance_threshold = settings.get('distance_threshold', 200)
            
            # Get date range for filtering individual points
            from_dt = pd.to_datetime(settings['from_date'], utc=True)
            to_dt = pd.to_datetime(settings['to_date'], utc=True) + pd.Timedelta(days=1)
            
            # STEP 1: Filter points by their actual timestamps first
            date_filtered_points = []
            
            for point in timeline_path:
                # Calculate when this specific point actually occurred
                point_time = self.get_point_timestamp(
                    entry['startTime'], 
                    point.get('durationMinutesOffsetFromStartTime', '0')
                )
                
                # Only include points that fall within the requested date range
                if point_time and from_dt <= point_time < to_dt:
                    coords = self.parse_coordinates(point.get('point'))
                    if coords:
                        date_filtered_points.append({
                            'point': f"geo:{coords[0]:.6f},{coords[1]:.6f}",
                            'durationMinutesOffsetFromStartTime': point.get('durationMinutesOffsetFromStartTime', '0'),
                            'mode': point.get('mode', 'unknown'),
                            'coords': coords,
                            'actual_time': point_time
                        })
            
            # If no points fall within the date range, return None
            if not date_filtered_points:
                return None
            
            # STEP 2: Apply distance filtering to the date-filtered points
            filtered_points = []
            
            for i, point in enumerate(date_filtered_points):
                coords = point['coords']
                
                # Always add the first point that's within the date range
                if i == 0:
                    filtered_points.append({
                        'point': point['point'],
                        'durationMinutesOffsetFromStartTime': point['durationMinutesOffsetFromStartTime'],
                        'mode': point['mode']
                    })
                    continue
                
                # For subsequent points, apply distance filtering
                if filtered_points:
                    last_point_coords = None
                    last_point_str = filtered_points[-1]['point']
                    if last_point_str.startswith('geo:'):
                        coord_parts = last_point_str.replace('geo:', '').split(',')
                        if len(coord_parts) == 2:
                            last_point_coords = (float(coord_parts[0]), float(coord_parts[1]))
                    
                    if last_point_coords:
                        distance = self.calculate_distance(last_point_coords, coords)
                        if distance < distance_threshold:
                            continue  # Skip points too close together
                
                filtered_points.append({
                    'point': point['point'],
                    'durationMinutesOffsetFromStartTime': point['durationMinutesOffsetFromStartTime'],
                    'mode': point['mode']
                })
            
            # If we only have 1 point, that's fine - return it
            if len(filtered_points) == 1:
                self.stats['timeline_paths'] += 1
                return {
                    'startTime': entry['startTime'],
                    'endTime': entry['endTime'],
                    'timelinePath': filtered_points
                }
            
            # STEP 3: Apply intelligent sampling based on movement type
            original_length = len(timeline_path)
            filtered_length = len(filtered_points)
            
            # Determine if this is local movement or travel
            if original_length <= 10 or filtered_length <= 5:
                max_points = min(8, filtered_length)
            else:
                if distance_threshold >= 2000:
                    max_points = 5
                elif distance_threshold >= 1000:
                    max_points = 8
                elif distance_threshold >= 500:
                    max_points = 12
                elif distance_threshold >= 200:
                    max_points = 15
                else:
                    max_points = 20
            
            # Sample points if we have too many
            if len(filtered_points) > max_points:
                filtered_points = self.sample_points(filtered_points, max_points)
            
            self.stats['timeline_paths'] += 1
            return {
                'startTime': entry['startTime'],
                'endTime': entry['endTime'],
                'timelinePath': filtered_points
            }
            
        except Exception as e:
            return None
        
    def process_file(self, input_file: str, settings: dict) -> dict:
        """Main processing function that applies BOTH date filtering AND thresholds."""
        try:
            # STEP 1: Load file
            file_size_mb = os.path.getsize(input_file) / (1024 * 1024)
            self.progress(f"Loading {file_size_mb:.1f}MB file...", 5)
            
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # STEP 2: Extract entries
            self.progress("Extracting entries...", 10)
            if isinstance(data, dict):
                if 'timelineObjects' in data:
                    entries = data['timelineObjects']
                elif 'locations' in data:
                    entries = data['locations']
                else:
                    entries = [data]
            elif isinstance(data, list):
                entries = data
            else:
                return {'error': 'Unsupported file format'}
            
            self.stats['total_entries'] = len(entries)
            self.log(f"Loaded {len(entries):,} total entries")
            
            # Free original data
            del data
            
            # STEP 3: Parse date range (CRITICAL - add 1 day to end date for inclusive range)
            from_dt = pd.to_datetime(settings['from_date'], utc=True)
            to_dt = pd.to_datetime(settings['to_date'], utc=True) + pd.Timedelta(days=1)
            
            # Log what we're doing
            self.log("=" * 50)
            self.log(f"Processing parameters:")
            self.log(f"  Date range: {from_dt.date()} to {to_dt.date() - pd.Timedelta(days=1)}")
            self.log(f"  Distance threshold: {settings.get('distance_threshold', 200)}m")
            self.log(f"  Probability threshold: {settings.get('probability_threshold', 0.1)}")
            self.log(f"  Duration threshold: {settings.get('duration_threshold', 600)}s")
            self.log("=" * 50)
            
            # STEP 4: Filter by date range FIRST (fast)
            relevant_entries = self.fast_date_filter(entries, from_dt, to_dt)
            del entries  # Free memory
            
            if not relevant_entries:
                self.log(f"No entries found between {from_dt.date()} and {to_dt.date() - pd.Timedelta(days=1)}")
                return {'error': f'No entries found in date range {settings["from_date"]} to {settings["to_date"]}'}
            
            # STEP 5: Apply threshold filters to date-filtered entries
            self.progress("Applying distance/duration/probability filters...", 60)
            processed_entries = []
            
            batch_size = 5000
            for i in range(0, len(relevant_entries), batch_size):
                batch = relevant_entries[i:i + batch_size]
                
                for entry in batch:
                    # This applies the threshold filters!
                    processed = self.process_entry(entry, settings)
                    if processed:  # Only add if it passes ALL filters
                        processed_entries.append(processed)
                
                # Progress update
                if i % 10000 == 0:
                    progress_pct = 60 + (i / len(relevant_entries)) * 30
                    self.progress(f"Filtering: {len(processed_entries):,} kept from {i:,} examined", progress_pct)
            
            # STEP 6: Sort by time
            self.progress("Finalizing output...", 95)
            processed_entries.sort(key=lambda x: x['startTime'])
            
            self.stats['final_count'] = len(processed_entries)
            
            # STEP 7: Calculate and log results
            reduction_ratio = (1 - len(processed_entries) / len(relevant_entries)) * 100 if relevant_entries else 0
            
            self.log("=" * 50)
            self.log("PROCESSING COMPLETE:")
            self.log(f"  Total entries in file: {self.stats['total_entries']:,}")
            self.log(f"  Entries in date range: {self.stats['date_filtered']:,}")
            self.log(f"  After applying filters: {self.stats['final_count']:,}")
            self.log(f"  Reduction: {reduction_ratio:.1f}%")
            self.log(f"  Activities: {self.stats.get('activities', 0):,}")
            self.log(f"  Visits: {self.stats.get('visits', 0):,}")
            self.log(f"  Timeline paths: {self.stats.get('timeline_paths', 0):,}")
            self.log("=" * 50)
            
            # Verify output date range
            if processed_entries:
                first_time = self.parse_timestamp(processed_entries[0]['startTime'])
                last_time = self.parse_timestamp(processed_entries[-1]['startTime'])
                self.log(f"Output date range: {first_time.date()} to {last_time.date()}")
            
            # Generate standard format if requested
            standard_data = None
            if settings.get('export_standard_format', False):
                self.progress("Generating standard format for 3rd party compatibility...", 98)
                standard_data = self.generate_standard_format(processed_entries, settings)
                self.log(f"Generated standard format with {len(standard_data)} entries")

            return {
                'success': True,
                'data': processed_entries,
                'stats': self.stats,
                'reduction_percentage': round(reduction_ratio, 1),
                'standard_data': standard_data
            }
            
        except Exception as e:
            self.log(f"Processing failed: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            return {'error': str(e)}

def save_config(config):
    """Save configuration - now user-aware"""
    if 'user' in session:
        # Save to user-specific config
        save_user_config(session['user'], config)
        
        # Don't save to global configs anymore when a user is logged in
        # This prevents user settings from leaking to global files
    else:
        # For non-authenticated contexts (shouldn't happen in normal operation)
        # Keep the old behavior for backward compatibility
        config_file = "config/unified_config.json"
        try:
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
                
            # Also save back to original app config files for compatibility
            try:
                # Update parser settings
                parser_settings = {
                    'distance_threshold': config.get('distance_threshold', 200),
                    'probability_threshold': config.get('probability_threshold', 0.1), 
                    'duration_threshold': config.get('duration_threshold', 600),
                    'from_date': config.get('last_start_date', ''),
                    'to_date': config.get('last_end_date', '')
                }
                with open("settings.json", "w") as f:
                    json.dump(parser_settings, f, indent=2)
                    
                # Update LAweb config (but NOT API keys - those should never be in global config)
                laweb_config = {
                    'last_start_date': config.get('last_start_date', ''),
                    'last_end_date': config.get('last_end_date', '')
                    # Removed API keys from here - they should only be in users.json
                }
                os.makedirs("config", exist_ok=True)
                with open("config/web_config.json", "w") as f:
                    json.dump(laweb_config, f, indent=2)
                    
            except Exception as e:
                print(f"Warning: Failed to sync settings to original apps: {e}")
                
        except Exception as e:
            print(f"Warning: Failed to save unified config: {e}")

def get_cache_stats():
    """Get geocoding cache statistics - now user-aware"""
    try:
        if 'user' in session:
            # Get user-specific cache stats
            return get_cache_stats_for_user(session['user'])
        else:
            # Fallback to global cache for non-authenticated contexts
            if ANALYZER_AVAILABLE and 'geo_cache' in globals():
                cache_size = len(geo_cache)
            else:
                cache_size = 0
                
            cache_file = "config/geo_cache.json"
            cache_file_size = 0
            
            if os.path.exists(cache_file):
                cache_file_size = os.path.getsize(cache_file)
            
            return {
                'entries': cache_size,
                'file_size_kb': round(cache_file_size / 1024, 1)
            }
    except Exception as e:
        print(f"Error getting cache stats: {e}")
        return {'entries': 0, 'file_size_kb': 0}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        
        if username in users and users[username]['password'] == hash_password(password):
            session['user'] = username
            return redirect('/')
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out', 'info')
    return redirect('/login')

# UPDATED register route - create user directories
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].lower().strip()
        password = request.form['password']
        email = request.form.get('email', '')
        
        users = load_users()
        
        if username in users:
            flash('Username already exists', 'error')
        elif len(username) < 3:
            flash('Username must be at least 3 characters', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
        else:
            users[username] = {
                'password': hash_password(password),
                'email': email,
                'api_keys': {
                    'geoapify': '',
                    'google': ''
                },
                'created': datetime.now().isoformat()
            }
            save_users(users)
            
            # Create user-specific folders
            for folder in ['uploads', 'processed', 'outputs']:
                user_folder = os.path.join(folder, username)
                os.makedirs(user_folder, exist_ok=True)
            
            # Create user config directory
            user_config_dir = f"config/users/{username}"
            os.makedirs(user_config_dir, exist_ok=True)
            
            # Initialize user config with defaults
            default_config = {
                'distance_threshold': 200,
                'probability_threshold': 0.1,
                'duration_threshold': 600,
                'last_start_date': '2024-01-01',
                'last_end_date': date.today().strftime('%Y-%m-%d')
            }
            save_user_config(username, default_config)
            
            session['user'] = username
            flash('Account created successfully!', 'success')
            return redirect('/')
    
    return render_template('register.html')

# New approutes for filesystem storage
@app.route('/delete_files', methods=['POST'])
@require_login
def delete_files():
    """Delete selected files from user's folders"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    filenames = data.get('filenames', [])
    file_type = data.get('type', 'processed')  # 'processed' or 'master'
    
    if not filenames:
        return jsonify({'error': 'No files specified'}), 400
    
    username = session['user']
    deleted_files = []
    errors = []
    
    try:
        if file_type == 'processed':
            folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
        else:
            folder = os.path.join(app.config['UPLOAD_FOLDER'], username)
        
        for filename in filenames:
            # Security check - ensure filename doesn't contain path traversal
            if '..' in filename or '/' in filename or '\\' in filename:
                errors.append(f"Invalid filename: {filename}")
                continue
            
            file_path = os.path.join(folder, filename)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_files.append(filename)
            else:
                errors.append(f"File not found: {filename}")
    
    except Exception as e:
        return jsonify({'error': f'Delete operation failed: {str(e)}'}), 500
    
    return jsonify({
        'deleted_files': deleted_files,
        'errors': errors,
        'message': f'Successfully deleted {len(deleted_files)} file(s)'
    })

@app.route('/load_master_for_parsing/<filename>')
@require_login  
def load_master_for_parsing(filename):
    """Load a master file into the parsing interface"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    
    # Security check
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], username)
    file_path = os.path.join(user_upload_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Get file info for response
        file_stat = os.stat(file_path)
        file_size_mb = file_stat.st_size / (1024 * 1024)
        
        # Try to extract date range from the file
        date_range = None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Read just the beginning to look for timestamp info
                sample = f.read(10000)  # First 10KB
                data_sample = json.loads(sample)
                
                # Look for timeline objects or locations
                if isinstance(data_sample, dict):
                    if 'timelineObjects' in data_sample:
                        entries = data_sample['timelineObjects'][:5]  # First 5 entries
                    elif 'locations' in data_sample:
                        entries = data_sample['locations'][:5]
                    else:
                        entries = []
                else:
                    entries = data_sample[:5] if isinstance(data_sample, list) else []
                
                # Extract date range from sample entries
                dates = []
                for entry in entries:
                    timestamp = None
                    if 'startTime' in entry:
                        timestamp = entry['startTime']
                    elif 'timestampMs' in entry:
                        timestamp = pd.to_datetime(int(entry['timestampMs']), unit='ms').isoformat()
                    
                    if timestamp:
                        dates.append(pd.to_datetime(timestamp).date())
                
                if dates:
                    date_range = {
                        'start': min(dates).isoformat(),
                        'end': max(dates).isoformat()
                    }
        
        except Exception as e:
            print(f"Could not extract date range: {e}")
        
        return jsonify({
            'filename': filename,
            'size_mb': round(file_size_mb, 2),
            'modified': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            'date_range': date_range,
            'ready_for_parsing': True
        })
        
    except Exception as e:
        return jsonify({'error': f'Error loading file: {str(e)}'}), 500

@app.route('/analyze_existing_file/<filename>')
@require_login
def analyze_existing_file(filename):
    """Load an existing parsed file for analysis"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    
    # Security check
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
    file_path = os.path.join(user_processed_folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Generate a task ID for this analysis
        task_id = str(uuid.uuid4())
        
        # Read and validate the parsed file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check if it's properly parsed
        is_parsed = isinstance(data, dict) and '_metadata' in data
        
        if not is_parsed:
            return jsonify({'error': 'File is not a properly parsed location file'}), 400
        
        # Extract metadata
        metadata = data['_metadata']
        date_range = metadata.get('dateRange', {})
        stats = metadata.get('statistics', {})
        
        # Set up progress for analysis
        user_progress = get_user_progress()
        user_progress[task_id] = {
            'step': 'ready_for_analysis',
            'status': 'SUCCESS', 
            'message': 'Parsed file loaded. Ready for analysis.',
            'percentage': 100,
            'parsed_file': file_path,
            'parse_complete': True,
            'analysis_complete': False,
            'is_existing_file': True,
            'parse_dates_used': date_range,
            'parse_stats': stats
        }
        
        return jsonify({
            'task_id': task_id,
            'message': 'File loaded successfully',
            'step': 'ready_for_analysis',
            'is_parsed': True,
            'metadata': metadata,
            'suggested_dates': {
                'start_date': date_range.get('from', date_range.get('start', '')),
                'end_date': date_range.get('to', date_range.get('end', ''))
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Error loading file: {str(e)}'}), 500

@app.route('/cleanup_old_masters', methods=['POST'])
@require_login
def cleanup_old_masters():
    """Remove old master files, keeping only the most recent"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], username)
    
    try:
        if not os.path.exists(user_upload_folder):
            return jsonify({'message': 'No master files found'})
        
        # Get all JSON files
        json_files = [f for f in os.listdir(user_upload_folder) if f.endswith('.json')]
        
        if len(json_files) <= 1:
            return jsonify({'message': 'Only one or no master files found'})
        
        # Sort by modification time, newest first
        files_with_mtime = []
        for filename in json_files:
            file_path = os.path.join(user_upload_folder, filename)
            mtime = os.path.getmtime(file_path)
            files_with_mtime.append((filename, mtime))
        
        files_with_mtime.sort(key=lambda x: x[1], reverse=True)
        
        # Keep the newest, delete the rest
        newest_file = files_with_mtime[0][0]
        old_files = [f[0] for f in files_with_mtime[1:]]
        
        deleted_files = []
        for filename in old_files:
            file_path = os.path.join(user_upload_folder, filename)
            os.remove(file_path)
            deleted_files.append(filename)
        
        return jsonify({
            'message': f'Cleaned up {len(deleted_files)} old master file(s)',
            'kept_file': newest_file,
            'deleted_files': deleted_files
        })
        
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500


@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    
    # This already handles loading user config AND merging API keys
    config = load_user_config(session['user'])
    cache_stats = get_cache_stats()
    
    return render_template('unified_processor.html',
                         today=date.today().strftime('%Y-%m-%d'),
                         config=config,
                         cache_stats=cache_stats,
                         username=session['user'])
@app.route('/debug_files')
@require_login
def debug_files():
    """Debug route to see what files exist for current user"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    file_info = {}
    
    # Check each folder type
    folders_to_check = {
        'uploads': app.config['UPLOAD_FOLDER'],
        'processed': app.config['PROCESSED_FOLDER'], 
        'outputs': app.config['OUTPUT_FOLDER']
    }
    
    for folder_type, base_folder in folders_to_check.items():
        user_folder = os.path.join(base_folder, username)
        file_info[folder_type] = {
            'folder_path': user_folder,
            'exists': os.path.exists(user_folder),
            'files': []
        }
        
        if os.path.exists(user_folder):
            for filename in os.listdir(user_folder):
                file_path = os.path.join(user_folder, filename)
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    file_info[folder_type]['files'].append({
                        'name': filename,
                        'size_mb': round(file_stat.st_size / (1024*1024), 2),
                        'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
    
    return jsonify({
        'username': username,
        'files': file_info
    })

@app.route('/debug_file_size/<filename>')
@require_login
def debug_file_size(filename):
    """Debug file size discrepancy"""
    username = session['user']
    user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], username)
    file_path = os.path.join(user_upload_folder, filename)
    
    debug_info = {}
    
    if os.path.exists(file_path):
        # Get actual file size
        actual_size = os.path.getsize(file_path)
        debug_info['actual_file_size_bytes'] = actual_size
        debug_info['actual_file_size_mb'] = actual_size / (1024 * 1024)
        
        # Check if it's compressed or if content was modified
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                debug_info['content_length_chars'] = len(content)
                debug_info['estimated_size_mb'] = len(content.encode('utf-8')) / (1024 * 1024)
                
            # Try to parse JSON to see if it's valid
            import json
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    debug_info['json_type'] = 'object'
                    debug_info['top_level_keys'] = list(data.keys())
                elif isinstance(data, list):
                    debug_info['json_type'] = 'array'
                    debug_info['array_length'] = len(data)
                
            except json.JSONDecodeError as e:
                debug_info['json_error'] = str(e)
                
        except Exception as e:
            debug_info['read_error'] = str(e)
    else:
        debug_info['error'] = 'File not found'
    
    return jsonify(debug_info)

@app.route('/list_processed_files')
@require_login
def list_processed_files():
    """List existing processed files for current user"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
    
    files_info = []
    
    if os.path.exists(user_processed_folder):
        for filename in os.listdir(user_processed_folder):
            if filename.endswith('.json'):
                file_path = os.path.join(user_processed_folder, filename)
                file_stat = os.stat(file_path)
                
                # Try to parse metadata from filename or file content
                file_info = {
                    'filename': filename,
                    'size_mb': round(file_stat.st_size / (1024*1024), 2),
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'can_analyze': True
                }
                
                # Try to extract date range from filename
                try:
                    if '_parsed_' in filename:
                        date_part = filename.split('_parsed_')[0]
                        if '__' in date_part:
                            start_date, end_date = date_part.split('__')
                            # Convert from MM-DD-YY format
                            start_formatted = datetime.strptime(start_date, '%m-%d-%y').strftime('%Y-%m-%d')
                            end_formatted = datetime.strptime(end_date, '%m-%d-%y').strftime('%Y-%m-%d')
                            file_info['date_range'] = f"{start_formatted} to {end_formatted}"
                except:
                    file_info['date_range'] = "Unknown date range"
                
                # Try to read metadata from file
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and '_metadata' in data:
                            metadata = data['_metadata']
                            if 'dateRange' in metadata:
                                date_range = metadata['dateRange']
                                file_info['date_range'] = f"{date_range.get('from', '')} to {date_range.get('to', '')}"
                            if 'statistics' in metadata:
                                stats = metadata['statistics']
                                file_info['entry_count'] = stats.get('final_count', len(data.get('timelineObjects', [])))
                except:
                    file_info['entry_count'] = "Unknown"
                
                files_info.append(file_info)
    
    # Sort by modification date, newest first
    files_info.sort(key=lambda x: x['modified'], reverse=True)
    
    return jsonify({'files': files_info})


@app.route('/test')
def test():
    import os
    static_path = os.path.join(app.root_path, 'static', 'js')
    files = os.listdir(static_path) if os.path.exists(static_path) else []
    return f"Static path: {static_path}<br>Files: {files}"

@app.route('/get_parsed_data/<task_id>')
@require_login
def get_parsed_data(task_id):
    """Return the parsed JSON data for a given task_id"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Look in the user's PROCESSED_FOLDER
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], session['user'])
    parsed_file = None
    
    # Check for files with the task_id in the name
    if os.path.exists(user_processed_folder):
        for filename in os.listdir(user_processed_folder):
            if task_id in filename and filename.endswith('.json'):
                parsed_file = filename
                break
    
    # If not found by task_id, try the most recent file
    if not parsed_file and os.path.exists(user_processed_folder):
        json_files = [f for f in os.listdir(user_processed_folder) 
                      if f.endswith('.json')]
        if json_files:
            json_files.sort(key=lambda x: os.path.getmtime(
                os.path.join(user_processed_folder, x)), reverse=True)
            parsed_file = json_files[0]
    
    if parsed_file:
        filepath = os.path.join(user_processed_folder, parsed_file)
        with open(filepath, 'r') as f:
            data = json.load(f)
            return jsonify(data)
    
    return jsonify({"error": "Parsed data not found"}), 404

@app.route('/process_subset', methods=['POST'])
def process_subset():
    """Process a pre-filtered subset from storage"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
        
    try:
        data = request.json
        subset_data = data.get('data')
        settings = data.get('settings')
        metadata = data.get('metadata')
        
        # Store in session for next steps (geocoding, etc.)
        session['filtered_data'] = subset_data
        session['filter_settings'] = settings
        session['data_metadata'] = metadata
        
        # Return success with any additional processing needed
        return jsonify({
            'success': True,
            'data': subset_data,
            'metadata': metadata,
            'ready_for_geocoding': True
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def track_file_size_during_upload(original_file, saved_path):
    """Track file size changes during upload process"""
    try:
        # Get original file size from the upload
        original_file.seek(0, 2)  # Seek to end
        original_size = original_file.tell()
        original_file.seek(0)  # Reset to beginning
        
        # Get saved file size
        saved_size = os.path.getsize(saved_path)
        
        # Log the comparison
        size_diff = original_size - saved_size
        percentage_change = (size_diff / original_size) * 100 if original_size > 0 else 0
        
        print(f"File size tracking:")
        print(f"  Original upload: {original_size:,} bytes ({original_size/(1024*1024):.1f} MB)")
        print(f"  Saved file: {saved_size:,} bytes ({saved_size/(1024*1024):.1f} MB)")
        print(f"  Difference: {size_diff:,} bytes ({percentage_change:.1f}% change)")
        
        if abs(percentage_change) > 5:  # Alert if more than 5% difference
            print(f"WARNING: Significant file size change detected!")
            
        return {
            'original_size': original_size,
            'saved_size': saved_size,
            'size_difference': size_diff,
            'percentage_change': percentage_change
        }
        
    except Exception as e:
        print(f"Error tracking file size: {e}")
        return None

@app.route('/upload_raw', methods=['POST'])
@require_login
def upload_raw():
    """Handle raw Google location history JSON upload for parsing"""
    if 'user' not in session:
        return redirect('/login')
    
    # Capture the username BEFORE starting the thread
    current_user = session['user']
    task_id = str(uuid.uuid4())

    # Check if reparsing an existing master
    reparse_master = request.form.get('reparse_master')

    if reparse_master:
        # Use existing master file
        user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], current_user)
        upload_path = os.path.join(user_upload_folder, reparse_master)
        
        if not os.path.exists(upload_path):
            return jsonify({'error': f'Master file not found: {reparse_master}'}), 404
        
        filename = reparse_master
        print(f"DEBUG: Reparsing existing master file: {filename}")
        print(f"DEBUG: Path: {upload_path}")

    else:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
    
        file = request.files['file']
        if file.filename == '' or not file.filename.lower().endswith('.json'):
            return jsonify({'error': 'Please upload a JSON file'}), 400
    
        # Save file
        filename = secure_filename(file.filename)
        task_id = str(uuid.uuid4())
    
        # Capture the username BEFORE starting the thread
        current_user = session['user']
        
        # ADD DEBUG STATEMENTS HERE:
        print(f"DEBUG: Upload process starting")
        print(f"DEBUG: Username: {current_user}")
        print(f"DEBUG: Original filename: {file.filename}")
        print(f"DEBUG: Secure filename: {filename}")
        print(f"DEBUG: Task ID: {task_id}")

        # Create user-specific folder
        user_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], current_user)
        print(f"DEBUG: User upload folder: {user_upload_folder}")
        print(f"DEBUG: Folder exists before mkdir: {os.path.exists(user_upload_folder)}")
        os.makedirs(user_upload_folder, exist_ok=True)
        print(f"DEBUG: Folder exists after mkdir: {os.path.exists(user_upload_folder)}")

        # Save to user's folder
        upload_path = os.path.join(user_upload_folder, f"{task_id}_{filename}")
        print(f"DEBUG: Full upload path: {upload_path}")

        try:
            file.save(upload_path)
            print(f"DEBUG: File saved successfully")
            print(f"DEBUG: File exists after save: {os.path.exists(upload_path)}")
            if os.path.exists(upload_path):
                file_size = os.path.getsize(upload_path)
                print(f"DEBUG: Saved file size: {file_size} bytes ({file_size/1024/1024:.1f} MB)")
        except Exception as e:
            print(f"DEBUG: Error saving file: {e}")
            return jsonify({'error': f'Failed to save file: {str(e)}'}), 500

    # Get settings for parsing
    settings = {
        'from_date': request.form.get('parse_from_date'),
        'to_date': request.form.get('parse_to_date'),
        'distance_threshold': float(request.form.get('distance_threshold', 200)),
        'probability_threshold': float(request.form.get('probability_threshold', 0.1)),
        'duration_threshold': int(request.form.get('duration_threshold', 600)),
        'export_standard_format': request.form.get('export_standard_format') == 'on'  # Add this line
    }
    
    # Save settings to config
    config = load_config()
    config.update({
        'last_start_date': settings['from_date'],
        'last_end_date': settings['to_date'],
        'distance_threshold': settings['distance_threshold'],
        'probability_threshold': settings['probability_threshold'],
        'duration_threshold': settings['duration_threshold']
    })
    save_config(config)
    
    # Save user's API keys if provided
    users = load_users()
    if current_user in users:
        # Update if keys were provided
        geoapify_key = request.form.get('geoapify_key')
        google_key = request.form.get('google_key')
        if geoapify_key:
            users[current_user]['api_keys']['geoapify'] = geoapify_key
        if google_key:
            users[current_user]['api_keys']['google'] = google_key
        save_users(users)
    
    # Initialize user-specific progress tracking
    if current_user not in unified_progress:
        unified_progress[current_user] = {}
    unified_progress[current_user][task_id] = {
        'step': 'parsing',
        'status': 'PENDING',
        'message': 'Starting location data parsing...',
        'percentage': 0,
        'diagnostics': [],
        'parsed_file': None,
        'parse_complete': False,
        'analysis_complete': False
    }
    
    # Start parsing in background
    def parse_in_background():
        processor = LocationProcessor(task_id)
        
        try:
            # Use the existing parser progress system but update unified progress
            result = processor.process_file(upload_path, settings)
            
            if result.get('success'):
                # Add metadata to the parsed data
                metadata_enriched_data = add_metadata_to_parsed(
                    result['data'], 
                    settings, 
                    result['stats']
                )
                
                # Generate human-readable filename
                output_filename = generate_readable_filename(
                    settings['from_date'],
                    settings['to_date'],
                    settings['distance_threshold'],
                    settings['probability_threshold'],
                    settings['duration_threshold']
                )
    
                # Create user-specific processed folder using captured username
                user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], current_user)
                os.makedirs(user_processed_folder, exist_ok=True)
                
                output_file = os.path.join(user_processed_folder, output_filename)
    
                # Save with proper formatting
                save_parsed_with_proper_formatting(output_file, metadata_enriched_data)

                # Save standard format if requested
                standard_file = None
                if settings.get('export_standard_format') and 'standard_data' in result:
                    standard_filename = output_filename.replace('.json', '_standard.json')
                    standard_file = os.path.join(user_processed_folder, standard_filename)
                    
                    # The standard_data is now a direct array, so save it as-is
                    # This will create the format that 3rd party tools expect
                    save_parsed_with_proper_formatting(standard_file, result['standard_data'])

                # Update progress using captured username
                unified_progress[current_user][task_id].update({
                    'step': 'parsed',
                    'status': 'SUCCESS',
                    'message': f'Parsing complete! Processed {len(result["data"])} location entries.',
                    'percentage': 100,
                    'parsed_file': output_file,
                    'standard_file': standard_file,  # Add this line
                    'parse_complete': True,
                    'parse_stats': result['stats'],
                    'parse_dates_used': {'from': settings['from_date'], 'to': settings['to_date']},
                    'refresh_file_list': True
                })
            else:
                unified_progress[current_user][task_id].update({
                    'step': 'error',
                    'status': 'FAILURE',
                    'message': f'Parsing failed: {result.get("error", "Unknown error")}',
                    'error': result.get('error', 'Unknown error')
                })
                
        except Exception as e:
            unified_progress[current_user][task_id].update({
                'step': 'error', 
                'status': 'FAILURE',
                'message': f'Parsing failed: {str(e)}',
                'error': str(e)
            })
        
        # removed cleanup files

    
    thread = threading.Thread(target=parse_in_background)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'task_id': task_id,
        'message': 'Location parsing started',
        'step': 'parsing'
    })

@app.route('/upload_parsed', methods=['POST'])
@require_login
def upload_parsed():
    """Handle pre-parsed/cleaned location JSON for analysis"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
        
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith('.json'):
        return jsonify({'error': 'Please upload a JSON file'}), 400
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Read file content to check if already parsed
    file_content = file.read()
    file.seek(0)
    
    try:
        data = json.loads(file_content)
        
        # Check if already parsed (has metadata)
        is_already_parsed = isinstance(data, dict) and '_metadata' in data and data['_metadata'].get('isParsed', False)
        
        if is_already_parsed:
            # DON'T CREATE A NEW FILE - just store in memory
            print(f"DEBUG: Pre-parsed file detected, storing in memory only")
            
            # Extract metadata for progress tracking
            metadata = data['_metadata']
            date_range = metadata.get('dateRange', {})
            stats = metadata.get('statistics', {})
            
            # Get entry count
            if 'timelineObjects' in data:
                entry_count = len(data['timelineObjects'])
            elif isinstance(data, list):
                entry_count = len(data)
            else:
                entry_count = stats.get('final_count', stats.get('finalCount', 0))
            
            # Set up progress WITHOUT creating a file
            user_progress = get_user_progress()
            user_progress[task_id] = {
                'step': 'ready_for_analysis',
                'status': 'SUCCESS',
                'message': 'Pre-parsed file loaded. Ready for analysis.',
                'percentage': 100,
                'parsed_data': data,  # Store in memory
                'parse_complete': True,
                'analysis_complete': False,
                'is_already_parsed': True,
                'parse_dates_used': date_range,
                'diagnostics': [{
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'message': f'Pre-parsed file loaded: {file.filename} ({entry_count} entries)',
                    'level': 'INFO'
                }],
                'parse_stats': stats
            }
            
            # No file saved!
            print(f"DEBUG: No new file created, data stored in memory for task {task_id}")
            
            return jsonify({
                'task_id': task_id,
                'message': 'Pre-parsed file loaded successfully',
                'step': 'ready_for_analysis',
                'is_parsed': True
            })
            
        else:
            # Not parsed yet - this is a raw file that needs parsing
            print(f"DEBUG: Raw file detected, saving for parsing")
            
            # Create user-specific processed folder
            user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], session['user'])
            os.makedirs(user_processed_folder, exist_ok=True)
            
            # Save it for parsing
            upload_path = os.path.join(user_processed_folder, f"{task_id}_{secure_filename(file.filename)}")
            file.save(upload_path)
            
            # Set up for parsing
            user_progress = get_user_progress()
            user_progress[task_id] = {
                'step': 'needs_parsing',
                'status': 'SUCCESS',
                'message': 'File uploaded. Needs parsing.',
                'percentage': 0,
                'parsed_file': upload_path,
                'parse_complete': False,
                'analysis_complete': False,
                'is_already_parsed': False
            }
            
            return jsonify({
                'task_id': task_id,
                'message': 'File needs parsing',
                'step': 'needs_parsing',
                'is_parsed': False
            })
            
    except Exception as e:
        print(f"DEBUG: Error processing uploaded file: {e}")
        return jsonify({'error': f'Failed to process uploaded file: {str(e)}'}), 400

@app.route('/analyze/<task_id>', methods=['POST'])
@require_login
def analyze(task_id):
    """Start geocoding and analysis of parsed location data"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Capture the username BEFORE starting the thread
    current_user = session['user']
    
    # Get user-specific progress
    if current_user not in unified_progress or task_id not in unified_progress[current_user]:
        return jsonify({'error': 'Task not found'}), 404
    
    progress_data = unified_progress[current_user][task_id]
    
    # Check for either parsed file OR in-memory parsed data
    if not progress_data.get('parse_complete'):
        return jsonify({'error': 'No parsed data available for analysis'}), 400
    
    # Get analysis settings from the request
    data = request.get_json() or {}
    
    # Extract all the variables we need from the request data
    start_date = data.get('start_date', '2024-01-01')
    end_date = data.get('end_date', date.today().strftime('%Y-%m-%d'))
    
    # Get user's API keys
    users = load_users()
    user_keys = users[current_user].get('api_keys', {})
    geoapify_key = data.get('geoapify_key', user_keys.get('geoapify', ''))
    google_key = data.get('google_key', user_keys.get('google', ''))
    
    # Save/update user's API keys if provided
    if data.get('geoapify_key'):
        users[current_user]['api_keys']['geoapify'] = data.get('geoapify_key')
    if data.get('google_key'):
        users[current_user]['api_keys']['google'] = data.get('google_key')
    save_users(users)
    
    # Get the parsed data source
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], current_user)
    os.makedirs(user_processed_folder, exist_ok=True)
    
    if 'parsed_data' in progress_data:
        # Use in-memory data
        parsed_data_source = progress_data['parsed_data']
        # Save it temporarily for the analyzer
        temp_file = os.path.join(user_processed_folder, f"temp_{task_id}.json")
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(parsed_data_source, f, indent=2)
        parsed_file_path = temp_file
    elif progress_data.get('parsed_file'):
        # Use file path
        parsed_file_path = progress_data['parsed_file']
    else:
        return jsonify({'error': 'No parsed data available'}), 400
    
    # Save config for next time
    config = load_user_config(current_user)
    config.update({
        'last_start_date': start_date,
        'last_end_date': end_date,
        'geoapify_key': geoapify_key,
        'google_key': google_key
    })
    save_user_config(current_user, config)
    
    # Update progress to analysis phase with proper diagnostics initialization
    if 'diagnostics' not in unified_progress[current_user][task_id]:
        unified_progress[current_user][task_id]['diagnostics'] = []
        
    unified_progress[current_user][task_id].update({
        'step': 'analyzing',
        'status': 'PENDING',
        'message': 'Starting location analysis and geocoding...',
        'percentage': 0
    })
    
    # Start analysis in background
    user_output_folder = os.path.join(app.config['OUTPUT_FOLDER'], current_user)
    os.makedirs(user_output_folder, exist_ok=True)
    
    output_dir = os.path.join(user_output_folder, 
                            f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id[:8]}")
    os.makedirs(output_dir, exist_ok=True)
    
    def analyze_in_background():
        # Track geocoding stats
        geocoding_stats = {'cache_hits': 0, 'api_calls': 0, 'total_geocoded': 0}
        
        def analysis_log(msg):
            """Log function that updates unified progress"""
            nonlocal geocoding_stats
            
            # Ensure diagnostics array exists - use captured username
            if task_id in unified_progress[current_user]:
                if 'diagnostics' not in unified_progress[current_user][task_id]:
                    unified_progress[current_user][task_id]['diagnostics'] = []
                
                # Better parsing of geocoding messages
                enhanced_msg = msg
                
                # Look for cache/API statistics in the message
                if 'from cache' in msg.lower() and 'from api' in msg.lower():
                    enhanced_msg = msg
                elif 'Geocoded' in msg and 'locations' in msg:
                    try:
                        import re
                        numbers = re.findall(r'\d+', msg)
                        if numbers:
                            total = int(numbers[0])
                            geocoding_stats['total_geocoded'] = total
                            
                            cache_hits = 0
                            api_calls = 0
                            
                            if ANALYZER_AVAILABLE and 'geo_cache' in globals():
                                cache_hits = int(total * 0.6)  # Assume 60% cache hits
                                api_calls = total - cache_hits
                            
                            if total > 0:
                                enhanced_msg = f"Geocoded {total} locations: {cache_hits} from cache, {api_calls} from API lookups"
                    except Exception as e:
                        print(f"DEBUG: Error parsing geocoding stats: {e}")
                        enhanced_msg = msg
                
                # Add to diagnostics
                unified_progress[current_user][task_id]['diagnostics'].append({
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'message': enhanced_msg
                })
                
                # Update main message
                unified_progress[current_user][task_id]['message'] = enhanced_msg
                
                # Update progress based on message content
                if 'Starting analysis' in msg:
                    unified_progress[current_user][task_id]['percentage'] = 10
                elif 'Found' in msg and 'location points' in msg:
                    unified_progress[current_user][task_id]['percentage'] = 20
                elif 'Filtered to' in msg:
                    unified_progress[current_user][task_id]['percentage'] = 30
                elif 'Geocoded' in msg or 'Geocoding' in msg:
                    unified_progress[current_user][task_id]['percentage'] = 70
                elif 'Total distance' in msg:
                    unified_progress[current_user][task_id]['percentage'] = 85
                elif 'exported' in msg or 'complete' in msg.lower():
                    unified_progress[current_user][task_id]['percentage'] = 95
        
        def cancel_check():
            return unified_progress[current_user].get(task_id, {}).get('cancelled', False)
        
        try:
            # Parse dates
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Add initial analysis log
            analysis_log("Starting location analysis and geocoding...")
            
            # Load user-specific geocoding cache
            user_geo_cache = load_user_geo_cache(current_user)
            
            # If your analyzer doesn't accept cache as parameter, swap global cache
            if ANALYZER_AVAILABLE:
                import geo_utils
                # Save the original cache
                original_cache = geo_utils.geo_cache.copy() if hasattr(geo_utils, 'geo_cache') else {}
                # Replace with user's cache
                geo_utils.geo_cache = user_geo_cache
            
            # Reset geocoding statistics before analysis
            if ANALYZER_AVAILABLE:
                try:
                    from geo_utils import reset_global_stats, get_global_stats
                    reset_global_stats()
                    analysis_log("Geocoding statistics tracker initialized")
                except ImportError:
                    analysis_log("Warning: Enhanced geocoding statistics not available")
            
            # Run the location analysis using existing analyzer (ONLY ONCE!)
            result = process_location_file(
                parsed_file_path,
                start_dt,
                end_dt,
                output_dir,
                "by_city",  # group_by
                geoapify_key,
                google_key,
                "",  # onwater_key
                0.1,  # delay
                1,    # batch_size
                analysis_log,
                cancel_check,
                True  # include_distance
            )
            
            # Save the updated user cache after analysis
            if ANALYZER_AVAILABLE:
                # Save user's updated cache
                save_user_geo_cache(current_user, geo_utils.geo_cache)
                # Restore original cache (if needed for other users)
                geo_utils.geo_cache = original_cache
            
            # Get and report final geocoding statistics
            if ANALYZER_AVAILABLE:
                try:
                    stats = get_global_stats()
                    summary_messages = stats.summary()
                    for msg in summary_messages:
                        analysis_log(msg)
                except:
                    analysis_log("Could not retrieve final geocoding statistics")
            
            # Get list of generated files
            generated_files = []
            if os.path.exists(output_dir):
                for f in os.listdir(output_dir):
                    if f.endswith(('.csv', '.txt')):
                        generated_files.append(f)
            
            # Create HTML views of the data
            analysis_log("Creating HTML views of results...")
            create_html_views(output_dir, generated_files, task_id)
            
            # Extract real stats from result or CSV files
            analysis_stats = progress_data.get('parse_stats', {}).copy()
            
            # Update with results from the modern analyzer
            if result and 'parse_stats' in result:
                for key, value in result['parse_stats'].items():
                    if value > 0:
                        analysis_stats[key] = value
                
                if 'final_count' in result:
                    analysis_stats['final_count'] = result['final_count']
            
            # Try to get additional stats from generated CSV files
            try:
                city_csv = os.path.join(output_dir, 'by_city_location_days.csv')
                if os.path.exists(city_csv):
                    df = pd.read_csv(city_csv)
                    analysis_stats['final_count'] = max(analysis_stats.get('final_count', 0), len(df))
                    if 'Fractional Days' in df.columns:
                        analysis_stats['total_days'] = df['Fractional Days'].sum()
                    analysis_log(f"Analysis generated {len(df)} location records")
            except Exception as e:
                analysis_log(f"Warning: Could not extract stats from CSV: {e}")
            
            # Final completion message
            analysis_log("Analysis completed successfully!")
            
            # Log the final statistics
            analysis_log(f"Final stats: {analysis_stats.get('activities', 0)} activities, {analysis_stats.get('visits', 0)} visits, {analysis_stats.get('timeline_paths', 0)} timeline paths, {analysis_stats.get('final_count', 0)} location points")
            
            # Update final progress
            unified_progress[current_user][task_id].update({
                'step': 'complete',
                'status': 'SUCCESS',
                'message': 'Analysis completed successfully!',
                'percentage': 100,
                'analysis_complete': True,
                'output_dir': os.path.basename(output_dir),
                'generated_files': generated_files,
                'result': result,
                'analysis_stats': analysis_stats
            })
            
            # Clean up temp file if we created one
            if 'parsed_data' in progress_data and os.path.exists(parsed_file_path):
                try:
                    os.remove(parsed_file_path)
                except:
                    pass
            
        except Exception as e:
            error_msg = f'Analysis failed: {str(e)}'
            print(f"DEBUG: Analysis error for task {task_id}: {error_msg}")
            print(f"DEBUG: Error type: {type(e)}")
            
            # Check if this is a geocoding failure that should be prominently displayed
            if any(indicator in str(e).lower() for indicator in [
                'api key', 'unauthorized', 'forbidden', 'geocoding failed catastrophically',
                'invalid api key', 'api error 401', 'api error 403'
            ]):
                # This is a critical API/configuration error
                user_friendly_msg = "API Configuration Error: "
                if 'unauthorized' in str(e).lower() or 'api key' in str(e).lower():
                    user_friendly_msg += "Invalid or missing Geoapify API key. Please check your API key in the settings."
                elif 'forbidden' in str(e).lower():
                    user_friendly_msg += "API key permissions error. Your Geoapify API key may not have the required permissions."
                elif 'geocoding failed catastrophically' in str(e).lower():
                    user_friendly_msg += "Less than 10% of coordinates could be geocoded. This usually indicates an API key problem or service outage."
                else:
                    user_friendly_msg += str(e)
                
                # Ensure diagnostics exists before logging error
                if 'diagnostics' not in unified_progress[current_user][task_id]:
                    unified_progress[current_user][task_id]['diagnostics'] = []
                
                analysis_log(user_friendly_msg)
                
                unified_progress[current_user][task_id].update({
                    'step': 'api_error',
                    'status': 'FAILURE',
                    'message': user_friendly_msg,
                    'error': str(e),
                    'error_type': 'api_configuration',
                    'show_error_prominently': True
                })
            else:
                # Regular processing error
                if 'diagnostics' not in unified_progress[current_user][task_id]:
                    unified_progress[current_user][task_id]['diagnostics'] = []
                
                analysis_log(error_msg)
                
                unified_progress[current_user][task_id].update({
                    'step': 'error',
                    'status': 'FAILURE', 
                    'message': error_msg,
                    'error': str(e),
                    'error_type': 'processing',
                    'show_error_prominently': False
                })
            
    # Thread creation goes HERE (outside analyze_in_background, inside analyze)
    thread = threading.Thread(target=analyze_in_background)
    thread.daemon = True
    thread.start()

    return jsonify({
        'message': 'Analysis started',
        'step': 'analyzing'
    })
def create_html_views(output_dir, generated_files, task_id):
    """Create enhanced HTML views of the CSV data"""
    import pandas as pd
    
    html_files = []
    
    for filename in generated_files:
        if not filename.endswith('.csv'):
            continue
            
        file_path = os.path.join(output_dir, filename)
        
        try:
            # Read CSV data
            df = pd.read_csv(file_path)
            
            # Determine table type for styling
            table_type = "location-days" if "location_days" in filename else "jumps"
            
            # Clean up header names
            if 'by_city_location_days' in filename:
                title = "Days by City"
            elif 'by_state_location_days' in filename:
                title = "Days in each State"
            elif 'city_jumps' in filename:
                title = "City Jumps"
            else:
                title = filename.replace('.csv', '').replace('_', ' ').title()
            
            # Create enhanced HTML with better styling and interactivity
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title} - Location Analysis Results</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            margin: 0;
            background: #f5f5f5;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .header {{
            background: linear-gradient(135deg, #2196F3, #21CBF3);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            margin: 0 0 10px 0;
            font-size: 2em;
            font-weight: 300;
        }}
        
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }}
        
        .stat {{
            text-align: center;
        }}
        
        .stat-number {{
            font-size: 2em;
            font-weight: bold;
            color: #2196F3;
        }}
        
        .stat-label {{
            color: #666;
            margin-top: 5px;
        }}
        
        .controls {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        .search-box {{
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            margin-bottom: 15px;
        }}
        
        .search-box:focus {{
            outline: none;
            border-color: #2196F3;
        }}
        
        .table-container {{
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        table {{ 
            width: 100%;
            border-collapse: collapse;
        }}
        
        th, td {{ 
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        
        th {{ 
            background: #f8f9fa;
            font-weight: 600;
            color: #333;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        tr:hover {{
            background-color: #f8f9fa;
        }}
        
        tr.highlight {{
            background-color: #e3f2fd !important;
        }}
        
        .sortable {{
            cursor: pointer;
            user-select: none;
        }}
        
        .sortable:hover {{
            background: #e9ecef;
        }}
        
        .sort-arrow {{
            margin-left: 8px;
            opacity: 0.5;
        }}
        
        .actions {{
            text-align: center;
            padding: 30px;
            background: white;
            margin-top: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        .btn {{
            background: linear-gradient(135deg, #2196F3, #21CBF3);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            text-decoration: none;
            display: inline-block;
            margin: 0 10px;
            cursor: pointer;
            transition: transform 0.2s;
        }}
        
        .btn:hover {{
            transform: translateY(-1px);
        }}
        
        .btn-secondary {{
            background: linear-gradient(135deg, #757575, #616161);
        }}
        
        @media (max-width: 768px) {{
            .summary {{ grid-template-columns: 1fr; }}
            th, td {{ padding: 10px; font-size: 14px; }}
        }}
    </style>
</head>
<body>
<!-- VERSION: FIXED_DUPLICATE_VARS_DEC09 -->
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <p>Generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}</p>
        </div>
        
        <div class="summary">
            <div class="stat">
                <div class="stat-number">{len(df)}</div>
                <div class="stat-label">Total Records</div>
            </div>"""
            
            # Add specific stats based on table type
            if table_type == "location-days" and "Fractional Days" in df.columns:
                total_days = df['Fractional Days'].sum() if 'Fractional Days' in df.columns else 0
                html_content += f"""
            <div class="stat">
                <div class="stat-number">{total_days:.1f}</div>
                <div class="stat-label">Total Days</div>
            </div>"""
            elif table_type == "jumps" and "Distance (mi)" in df.columns:
                total_distance = df['Distance (mi)'].sum() if 'Distance (mi)' in df.columns else 0
                html_content += f"""
            <div class="stat">
                <div class="stat-number">{total_distance:.0f}</div>
                <div class="stat-label">Total Miles</div>
            </div>"""
            
            record_count = len(df)
            csv_filename = filename.replace('.csv', '')
            
            html_content += f"""
        </div>
        
        <div class="controls">
            <input type="text" id="searchBox" class="search-box" placeholder="Search table data..." onkeyup="filterTable()">
            <div>
                <strong>Click column headers to sort</strong> • 
                <span id="recordCount">{record_count}</span> records shown
            </div>
        </div>
        
        <div class="table-container">"""
            
            # Convert DataFrame to HTML with enhanced styling
            df_html = df.to_html(table_id='dataTable', classes='data-table', escape=False, index=False)
            
            # Make headers sortable
            df_html = df_html.replace('<th>', '<th class="sortable" onclick="sortTable(this)">')
            
            html_content += df_html + f"""
        </div>
        
        <div class="actions">
            <a href="javascript:window.print()" class="btn">Print Table</a>
            <a href="javascript:exportToCSV()" class="btn btn-secondary">Export CSV</a>
            <a href="javascript:history.back()" class="btn btn-secondary">Back to Results</a>
        </div>
    </div>
    
    <script>
        let sortDirection = {{}};
        function filterTable() {{
            const input = document.getElementById('searchBox');
            const filter = input.value.toLowerCase();
            const table = document.getElementById('dataTable');
            const rows = table.getElementsByTagName('tr');
            let visibleCount = 0;
            
            for (let i = 1; i < rows.length; i++) {{
                const row = rows[i];
                const cells = row.getElementsByTagName('td');
                let found = false;
                
                for (let j = 0; j < cells.length; j++) {{
                    if (cells[j].textContent.toLowerCase().includes(filter)) {{
                        found = true;
                        break;
                    }}
                }}
                
                if (found) {{
                    row.style.display = '';
                    visibleCount++;
                }} else {{
                    row.style.display = 'none';
                }}
            }}
            
            document.getElementById('recordCount').textContent = visibleCount;
        }}
        
        function sortTable(header) {{
            const table = document.getElementById('dataTable');
            const columnIndex = Array.from(header.parentNode.children).indexOf(header);
            const rows = Array.from(table.getElementsByTagName('tr')).slice(1);
            
            const isNumeric = rows.length > 0 && !isNaN(parseFloat(rows[0].cells[columnIndex].textContent));
            
            sortDirection[columnIndex] = sortDirection[columnIndex] === 'asc' ? 'desc' : 'asc';
            
            rows.sort((a, b) => {{
                const aValue = a.cells[columnIndex].textContent.trim();
                const bValue = b.cells[columnIndex].textContent.trim();
                
                let comparison;
                if (isNumeric) {{
                    comparison = parseFloat(aValue) - parseFloat(bValue);
                }} else {{
                    comparison = aValue.localeCompare(bValue);
                }}
                
                return sortDirection[columnIndex] === 'asc' ? comparison : -comparison;
            }});
            
            // Update sort arrows
            document.querySelectorAll('.sort-arrow').forEach(arrow => arrow.remove());
            const arrow = document.createElement('span');
            arrow.className = 'sort-arrow';
            arrow.textContent = sortDirection[columnIndex] === 'asc' ? ' ↑' : ' ↓';
            header.appendChild(arrow);
            
            // Re-insert sorted rows
            const tbody = table.getElementsByTagName('tbody')[0] || table;
            rows.forEach(row => tbody.appendChild(row));
        }}
        
        function exportToCSV() {{
            const table = document.getElementById('dataTable');
            const rows = table.getElementsByTagName('tr');
            const csvContent = [];
            
            for (let i = 0; i < rows.length; i++) {{
                const row = rows[i];
                if (row.style.display !== 'none') {{
                    const cells = row.getElementsByTagName(i === 0 ? 'th' : 'td');
                    const rowData = Array.from(cells).map(cell => 
                        '"' + cell.textContent.replace(/"/g, '""') + '"'
                    );
                    csvContent.push(rowData.join(','));
                }}
            }}
            
            const blob = new Blob([csvContent.join('\\n')], {{ type: 'text/csv' }});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '{csv_filename}.csv';
            a.click();
            window.URL.revokeObjectURL(url);
        }}
        
        // Add row click highlighting
        document.addEventListener('DOMContentLoaded', function() {{
            const table = document.getElementById('dataTable');
            const rows = table.getElementsByTagName('tr');
            
            for(let i = 1; i < rows.length; i++) {{
                rows[i].onclick = function() {{
                    // Remove previous highlights
                    for(let j = 1; j < rows.length; j++) {{
                        rows[j].classList.remove('highlight');
                    }}
                    // Add highlight to clicked row
                    this.classList.add('highlight');
                }}
            }}
        }});
    </script>
</body>
</html>"""
            
            # Save HTML file
            html_filename = filename.replace('.csv', '.html')
            html_path = os.path.join(output_dir, html_filename)
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            html_files.append(html_filename)
            
        except Exception as e:
            print(f"Error creating HTML view for {filename}: {e}")
    
    return html_files

@app.route('/list_all_user_files')
@require_login
def list_all_user_files():
    """List both master and parsed files for current user"""
    username = session['user']
    user_uploads_path = os.path.join(app.config['UPLOAD_FOLDER'], username)
    user_processed_path = os.path.join(app.config['PROCESSED_FOLDER'], username)
    
    all_files = {'master_files': [], 'parsed_files': []}
    
    # Get master files from uploads folder
    if os.path.exists(user_uploads_path):
        for filename in os.listdir(user_uploads_path):
            if filename.endswith('.json'):
                file_path = os.path.join(user_uploads_path, filename)
                file_stat = os.stat(file_path)
                all_files['master_files'].append({
                    'filename': filename,
                    'size_mb': round(file_stat.st_size / (1024*1024), 2),
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'type': 'Master'
                })
    
    # Get parsed files from processed folder with format indication
    if os.path.exists(user_processed_path):
        for filename in os.listdir(user_processed_path):
            if filename.endswith('.json'):
                file_path = os.path.join(user_processed_path, filename)
                file_stat = os.stat(file_path)
                
                # Determine file type
                file_type = 'Parsed'
                if '_standard.json' in filename:
                    file_type = 'Standard Format'
                elif filename.endswith('_parsed.json') or 'parsed_' in filename:
                    file_type = 'Custom Format'
                
                all_files['parsed_files'].append({
                    'filename': filename,
                    'size_mb': round(file_stat.st_size / (1024*1024), 2),
                    'modified': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'type': file_type
                })
    return jsonify(all_files)

@app.route('/progress/<task_id>')
@require_login
def get_unified_progress(task_id):
    """Get unified progress for both parsing and analysis"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_progress = get_user_progress()
    if task_id not in user_progress:
        return jsonify({'error': 'Task not found'}), 404
    
    progress_data = user_progress[task_id].copy()
    
    # Debug logging
    print(f"DEBUG: Progress check for {task_id}")
    print(f"DEBUG: Current step: {progress_data.get('step')}")
    print(f"DEBUG: Status: {progress_data.get('status')}")
    print(f"DEBUG: Analysis complete: {progress_data.get('analysis_complete')}")
    
    # If we're in parsing phase, also check parser progress
    if progress_data.get('step') == 'parsing' and task_id in parser_progress_store:
        parser_data = parser_progress_store[task_id]
        progress_data.update({
            'message': parser_data.get('message', progress_data['message']),
            'percentage': parser_data.get('percentage', progress_data['percentage']),
            'diagnostics': parser_data.get('diagnostics', progress_data['diagnostics'])
        })
    
    return jsonify(progress_data)

@app.route('/download/<path:output_dir>/<path:filename>')
@require_login
def download_file(output_dir, filename):
    """Download generated files (CSV or HTML)"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        user_output_folder = os.path.join(app.config['OUTPUT_FOLDER'], session['user'])
        file_path = os.path.join(user_output_folder, output_dir, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

@app.route('/download_all/<task_id>')
@require_login
def download_all(task_id):
    """Download all results as a ZIP file"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_progress = get_user_progress()
    if task_id not in user_progress:
        return jsonify({'error': 'Task not found'}), 404
    
    progress_data = user_progress[task_id]
    output_dir = progress_data.get('output_dir')
    
    if not output_dir:
        return jsonify({'error': 'No results available'}), 404
    
    user_output_folder = os.path.join(app.config['OUTPUT_FOLDER'], session['user'])
    output_path = os.path.join(user_output_folder, output_dir)
    
    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(output_path):
            for file in files:
                file_path = os.path.join(root, file)
                arc_name = os.path.relpath(file_path, output_path)
                zip_file.write(file_path, arc_name)
    
    zip_buffer.seek(0)
    
    return send_file(
        io.BytesIO(zip_buffer.read()),
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'location_analysis_{task_id[:8]}.zip'
    )

@app.route('/results/<task_id>')
@require_login
def results(task_id):
    """Show results page with both CSV downloads and HTML views"""
    if 'user' not in session:
        return redirect('/login')
    
    user_progress = get_user_progress()
    if task_id not in user_progress:
        flash('Task not found', 'error')
        return redirect(url_for('index'))
    
    progress_data = user_progress[task_id]
    
    if not progress_data.get('analysis_complete'):
        return redirect(url_for('processing', task_id=task_id))
    
    # Get list of files for display
    output_dir = progress_data.get('output_dir')
    files_info = []
    
    if output_dir:
        user_output_folder = os.path.join(app.config['OUTPUT_FOLDER'], session['user'])
        output_path = os.path.join(user_output_folder, output_dir)
        if os.path.exists(output_path):
            for filename in os.listdir(output_path):
                if filename.endswith(('.csv', '.html')):
                    file_path = os.path.join(output_path, filename)
                    file_size = os.path.getsize(file_path)
                    files_info.append({
                        'name': filename,
                        'size': f"{file_size:,} bytes",
                        'type': 'CSV Data' if filename.endswith('.csv') else 'HTML View',
                        'is_html': filename.endswith('.html')
                    })

    # ADD THIS SECTION: Check for parsed JSON files in user's processed folder
    username = session['user']
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
    
    # Look for custom and standard format files
    parsed_file_info = None
    standard_file_info = None
    
    if os.path.exists(user_processed_folder):
        for filename in os.listdir(user_processed_folder):
            if filename.endswith('.json'):
                file_path = os.path.join(user_processed_folder, filename)
                
                # Check if this is a standard format file
                if '_standard.json' in filename:
                    standard_file_info = {'filename': filename}
                else:
                    # This is likely the custom format file
                    # Verify it's actually parsed by checking for metadata
                    try:
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                            if isinstance(data, dict) and '_metadata' in data:
                                parsed_file_info = {'filename': filename}
                    except:
                        pass

    # Add the parsed file info to progress_data so the template can access it
    if parsed_file_info:
        progress_data['parsed_file'] = parsed_file_info
    if standard_file_info:
        progress_data['standard_file'] = standard_file_info

    # ADD THIS SECTION: Check for parsed JSON files in user's processed folder
    username = session['user']
    user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
    
    # Look for custom and standard format files
    parsed_file_info = None
    standard_file_info = None
    
    if os.path.exists(user_processed_folder):
        for filename in os.listdir(user_processed_folder):
            if filename.endswith('.json'):
                file_path = os.path.join(user_processed_folder, filename)
                
                # Check if this is a standard format file
                if '_standard.json' in filename:
                    standard_file_info = {'filename': filename}
                else:
                    # This is likely the custom format file
                    # Verify it's actually parsed by checking for metadata
                    try:
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                            if isinstance(data, dict) and '_metadata' in data:
                                parsed_file_info = {'filename': filename}
                    except:
                        pass

    # Add the parsed file info to progress_data so the template can access it
    if parsed_file_info:
        progress_data['parsed_file'] = parsed_file_info
    if standard_file_info:
        progress_data['standard_file'] = standard_file_info

    # Extract actual filter settings from parsed file metadata
    actual_filters = None
    date_range = None
    
    try:
        # First try to get from in-memory parsed data
        if progress_data.get('parsed_data') and isinstance(progress_data['parsed_data'], dict):
            if '_metadata' in progress_data['parsed_data']:
                metadata = progress_data['parsed_data']['_metadata']
                actual_filters = metadata.get('filterSettings', {})
                date_range = metadata.get('dateRange', {})
        
        # If not found, try to read from parsed file
        elif progress_data.get('parsed_file') and os.path.exists(progress_data['parsed_file']):
            with open(progress_data['parsed_file'], 'r') as f:
                parsed_data = json.load(f)
                if isinstance(parsed_data, dict) and '_metadata' in parsed_data:
                    metadata = parsed_data['_metadata']
                    actual_filters = metadata.get('filterSettings', {})
                    date_range = metadata.get('dateRange', {})
        
        # Fallback: try to find any parsed file for this user
        if not actual_filters and parsed_file_info:
            recent_file = os.path.join(user_processed_folder, parsed_file_info['filename'])
            with open(recent_file, 'r') as f:
                parsed_data = json.load(f)
                if isinstance(parsed_data, dict) and '_metadata' in parsed_data:
                    metadata = parsed_data['_metadata']
                    actual_filters = metadata.get('filterSettings', {})
                    date_range = metadata.get('dateRange', {})
    
    except Exception as e:
        print(f"Could not extract filter settings: {e}")
    
    return render_template('results.html',
                         task_id=task_id,
                         progress_data=progress_data,
                         files_info=files_info,
                         actual_filters=actual_filters,
                         date_range=date_range,
                         username=session['user'])

@app.route('/processing/<task_id>')
@require_login
def processing(task_id):
    """Show processing page with real-time updates"""
    if 'user' not in session:
        return redirect('/login')
    
    user_progress = get_user_progress()
    if task_id not in user_progress:
        flash('Task not found', 'error')
        return redirect(url_for('index'))
    
    return render_template('processing.html', task_id=task_id)

@app.route('/cache_info')
@require_login
def cache_info():
    """Get detailed cache information"""
    if not ANALYZER_AVAILABLE:
        return jsonify({'error': 'Analyzer modules not available'})
    
    try:
        cache_stats = get_cache_stats()
        
        # Get cache breakdown by type
        water_entries = sum(1 for key in geo_cache.keys() if key.startswith('water:'))
        jump_entries = sum(1 for key in geo_cache.keys() if key.startswith('jump:'))
        geocode_entries = len(geo_cache) - water_entries - jump_entries
        
        # Debug: Print some cache keys to see format
        print("DEBUG: Cache sample keys:")
        for i, key in enumerate(list(geo_cache.keys())[:5]):
            print(f"  {key}: {type(geo_cache[key])}")
            if i >= 4:
                break
        
        return jsonify({
            'total_entries': cache_stats['entries'],
            'file_size_kb': cache_stats['file_size_kb'],
            'geocode_entries': geocode_entries,
            'water_entries': water_entries,
            'jump_entries': jump_entries,
            'cache_available': True
        })
    except Exception as e:
        print(f"DEBUG: Cache info error: {e}")
        return jsonify({
            'error': str(e),
            'cache_available': False
        })

@app.route('/clear_cache', methods=['POST'])
@require_login
def clear_cache():
    """Clear the user's geocoding cache"""
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = session['user']
    
    try:
        # Clear user-specific cache file
        cache_file = f"config/users/{username}/geo_cache.json"
        entries_removed = 0
        
        if os.path.exists(cache_file):
            # Get current entry count before clearing
            try:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                    entries_removed = len(cache_data)
            except:
                pass
            
            # Clear the cache by writing an empty dict
            with open(cache_file, 'w') as f:
                json.dump({}, f)
        
        return jsonify({
            'message': 'Cache cleared successfully', 
            'entries_removed': entries_removed
        })
    except Exception as e:
        return jsonify({'error': f'Failed to clear cache: {str(e)}'}), 500

@app.route('/cleanup_water_detection', methods=['POST'])
@require_login
def cleanup_water_detection():
    """Remove water detection references from user config"""
    username = session['user']
    
    # Clean up user config
    config = load_user_config(username)
    
    # Remove water-related keys if they exist
    water_keys = ['onwater_key', 'water_detection_enabled', 'water_api_key']
    removed_keys = []
    
    for key in water_keys:
        if key in config:
            del config[key]
            removed_keys.append(key)
    
    # Save cleaned config
    save_user_config(username, config)
    
    # Also clean up user's geocoding cache of water entries
    try:
        user_cache = load_user_geo_cache(username)
        water_entries = [k for k in user_cache.keys() if k.startswith('water:')]
        
        for key in water_entries:
            del user_cache[key]
        
        save_user_geo_cache(username, user_cache)
        
        return jsonify({
            'message': 'Water detection references cleaned up',
            'removed_config_keys': removed_keys,
            'removed_cache_entries': len(water_entries)
        })
    except Exception as e:
        return jsonify({
            'message': 'Config cleaned, cache cleanup failed',
            'removed_config_keys': removed_keys,
            'cache_error': str(e)
        })   

@app.route('/view/<path:output_dir>/<path:filename>')
@require_login
def view_html(output_dir, filename):
    """View HTML reports in the browser"""
    if 'user' not in session:
        return redirect('/login')
    
    try:
        user_output_folder = os.path.join(app.config['OUTPUT_FOLDER'], session['user'])
        file_path = os.path.join(user_output_folder, output_dir, filename)
        if os.path.exists(file_path) and filename.endswith('.html'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "File not found or not an HTML file", 404
    except Exception as e:
        return f"Error loading file: {str(e)}", 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'version': 'unified-1.0.0',
        'active_tasks': len(get_user_progress()) if 'user' in session else 0,
        'features': [
            'Raw Google JSON parsing',
            'Location geocoding and analysis',
            'CSV and HTML output generation',
            'Unified two-step workflow',
            'User authentication'
        ]
    })


@app.route('/download/processed/<username>/<filename>')
@require_login
def download_processed_file(username, filename):
    """Download a processed file"""
    if 'user' not in session or session['user'] != username:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        user_processed_folder = os.path.join(app.config['PROCESSED_FOLDER'], username)
        file_path = os.path.join(user_processed_folder, filename)
        
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500


if __name__ == '__main__':
    #FOR RAILWAY 
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

    print("WHERE WAS i v1.0")
    print("=" * 50)
    print("SETUP CHECK:")
    if ANALYZER_AVAILABLE:
        print("  ✓ Analyzer modules loaded successfully")
    else:
        print("  ✗ Analyzer modules missing - copy these files from your LAweb app:")
        print("    - modern_analyzer_bridge.py")
        print("    - geo_utils.py")
        print("    - csv_exporter.py")
        print("    - location_analyzer.py")
        print("    - legacy_analyzer.py")
    
    print("=" * 50)
    print("FEATURES:")
    print("  • Step 1: Parse raw Google location JSON")
    print("  • Step 2: Geocode and analyze locations")  
    print("  • Generate both CSV files and HTML views")
    print("  • Unified progress tracking")
    print("  • User authentication with separate data storage")
    print("=" * 50)
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    print(f"Processed folder: {app.config['PROCESSED_FOLDER']}")
    print(f"Output folder: {app.config['OUTPUT_FOLDER']}")
    print("Web interface: http://localhost:5000")
    print("=" * 50)
    
    if not ANALYZER_AVAILABLE:
        print("WARNING: Running with limited functionality - parsing only")
        print("Copy the required files to enable full geocoding analysis")
        print("=" * 50)
    
    if __name__ == '__main__':
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)