"""
AniHonYomi Backup Manager

Author: MorningStarGG
Version: 1.0
Github: https://github.com/MorningStarGG/AniHonYomi
Website: https://www.twitch.tv/MorningStarGG

This tool provides utilities for working with Tachiyomi manga reader backup files (.tachibk),
with special integration for AniList. It allows users to:

- Import manga libraries from AniList into Tachiyomi/Mihon backup format
- Convert between backup files and JSON for easy editing
- Merge multiple backup files with duplicate handling
- Clean up backups by removing duplicate entries
- Find and report potential duplicates across backups
- Generate and work with protobuf schemas for various Tachiyomi forks

The tool supports both public and authenticated AniList API access, allowing
users to import both public and private manga lists.

Usage Examples:
----------------

AniList Import:
    # Import public AniList manga list to Tachiyomi backup
    python tachiyomi_backup_manager.py anilist --anilist <username> --output <backup.tachibk>
    
    # Import private AniList manga list with authentication
    python tachiyomi_backup_manager.py anilist --auth --output <backup.tachibk>
    
    # Import only specific status lists (reading, completed, etc.)
    python tachiyomi_backup_manager.py anilist --anilist <username> --lists CURRENT,COMPLETED --output <backup.tachibk>
    
    # Add new manga from AniList to existing backup (skip duplicates)
    python tachiyomi_backup_manager.py anilist --anilist <username> --compare <existing.tachibk> --output <updated.tachibk>
    
    # Export AniList manga data to JSON for reference
    python tachiyomi_backup_manager.py anilist --anilist <username> --export-json <anilist_data.json>

Backup Conversion:
    # Convert backup file to human-readable JSON
    python tachiyomi_backup_manager.py decode --input <backup.tachibk> --output <backup.json>
    
    # Convert JSON back to backup format
    python tachiyomi_backup_manager.py encode --input <backup.json> --output <backup.tachibk>

Backup Merging:
    # Merge multiple backups with different strategies
    python tachiyomi_backup_manager.py merge --input <backup1.tachibk> <backup2.tachibk> --output <merged.tachibk>
    
    # Keep first occurrences when merging (don't replace duplicates)
    python tachiyomi_backup_manager.py merge --input <backup1.tachibk> <backup2.tachibk> --mode keep_first --output <merged.tachibk>
    
    # Keep both occurrences when merging (retain duplicates)
    python tachiyomi_backup_manager.py merge --input <backup1.tachibk> <backup2.tachibk> --mode keep_both --output <merged.tachibk>
    
    # Generate detailed report of merge operation
    python tachiyomi_backup_manager.py merge --input <backup1.tachibk> <backup2.tachibk> --report <merge_report.md> --output <merged.tachibk>

Backup Cleanup:
    # Remove duplicate manga entries from a backup
    python tachiyomi_backup_manager.py cleanup --input <backup.tachibk> --output <cleaned.tachibk>
    
    # Keep last occurrence instead of first when removing duplicates
    python tachiyomi_backup_manager.py cleanup --input <backup.tachibk> --mode keep_last --output <cleaned.tachibk>
    
    # Generate detailed report of cleanup operation
    python tachiyomi_backup_manager.py cleanup --input <backup.tachibk> --report <cleanup_report.md> --output <cleaned.tachibk>

Duplicate Finding:
    # Find potential duplicates within a backup using AniList data
    python tachiyomi_backup_manager.py find-duplicates --backup <backup.tachibk> --anilist-json <anilist_data.json> --output <duplicate_report.md>

Protobuf Schema:
    # Generate protobuf schema for a specific Tachiyomi fork
    python tachiyomi_backup_manager.py schema --fork mihon
    
    # Generate schemas for all supported forks
    python tachiyomi_backup_manager.py schema --dump-all

Supported Tachiyomi forks:
    - mihon: mihonapp/mihon (default)
    - sy: jobobby04/TachiyomiSY
    - j2k: Jays2Kings/tachiyomiJ2K
    - yokai: null2264/yokai

For full command details, run:
    python tachiyomi_backup_manager.py <command> --help
"""

import gzip
import re
import varint
import json
import os
import requests
import webbrowser
import argparse
import fuzzywuzzy
from base64 import b64decode, b64encode
from datetime import datetime
from pathlib import Path
from struct import pack, unpack
from subprocess import run
from google.protobuf.json_format import Parse, ParseError, MessageToDict

# Constants
ANILIST_API = 'https://graphql.anilist.co'
FORKS = {
    'mihon': 'mihonapp/mihon',
    'sy': 'jobobby04/TachiyomiSY',
    'j2k': 'Jays2Kings/tachiyomiJ2K',
    'yokai': 'null2264/yokai',
}

# Regular expressions for schema parsing
PROTONUMBER_RE = r'(?:^\s*(?!\/\/\s*)@ProtoNumber\((?P<number>\d+)\)\s*|data class \w+\(|^)va[rl]\s+(?P<name>\w+):\s+(?:(?:(?:List|Set)<(?P<list>\w+)>)|(?P<type>\w+))(?P<optional>\?|(:?\s+=))?'
CLASS_RE = r'^(?:data )?class (?P<name>\w+)\((?P<defs>(?:[^)(]+|\((?:[^)(]+|\([^)(]*\))*\))*)\)'
DATA_TYPES = {
    'String': 'string',
    'Int': 'int32',
    'Long': 'int64',
    'Boolean': 'bool',
    'Float': 'float',
    'Char': 'string',
}

# Setup logging
def log(message, source="main"):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{source}] {message}")

# Utility to get user input
def input_with_default(prompt, default=None):
    user_input = input(f"[{datetime.now().strftime('%H:%M:%S')}][main]: {prompt}")
    if not user_input and default is not None:
        return default
    return user_input

# Anilist GraphQL queries
def query_manga_list():
    return '''
    query ($userID: Int) {
      MediaListCollection(userId: $userID, type: MANGA) { 
        lists {
          status
          entries {
            status
            score(format: POINT_10)
            progress
            progressVolumes
            notes
            private
            startedAt { year month day }
            completedAt { year month day }
            media {
              id
              idMal
              title {
                english
                romaji
                native
              }
              description
              format
              status
              chapters
              volumes
              coverImage { medium large }
              synonyms
              isAdult
              countryOfOrigin
              source
            }
          }
        }
      }
    }
    '''

def query_user_id(username):
    return {
        'query': '''
        query ($username: String) {
          User(name: $username) {
            id
          }
        }
        ''',
        'variables': {
            'username': username
        }
    }

def query_authenticated_user():
    return {
        'query': '''
        query {
          Viewer {
            id
            name
          }
        }
        '''
    }

# Anilist Authentication and API functions
def setup_anilist_config(config_file):
    """Setup Anilist API configuration."""
    anilist_client = ""
    anilist_secret = ""
    redirect_url = "https://anilist.co/api/v2/oauth/pin"
    use_oauth = False

    if not os.path.exists(config_file):
        log("No config file found. Setting up new configuration.")
        while not anilist_client:
            anilist_client = input_with_default("Enter your Anilist Client ID: ")
        while not anilist_secret:
            anilist_secret = input_with_default("Enter your Anilist Client Secret: ")

        config_data = {
            "aniclient": anilist_client,
            "anisecret": anilist_secret,
            "redirectUrl": redirect_url
        }

        os.makedirs(os.path.dirname(os.path.abspath(config_file)), exist_ok=True)
        with open(config_file, "w", encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log(f"Configuration saved to {config_file}")
    
    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)
        anilist_client = config_data.get('aniclient', '')
        anilist_secret = config_data.get('anisecret', '')
        redirect_url = config_data.get('redirectUrl', redirect_url)
        if anilist_client and anilist_secret:
            use_oauth = True
    except Exception as e:
        log(f"Error loading config file: {e}")
        use_oauth = False
    
    return use_oauth, anilist_client, anilist_secret, redirect_url

def request_anilist_auth_code(client_id, redirect_url):
    """Request authorization code from Anilist."""
    log("Login to Anilist in your browser and authorize the application")
    auth_url = f"https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&redirect_uri={redirect_url}&response_type=code"
    
    webbrowser.open(auth_url)
    
    code = input_with_default("Paste the authorization code from the browser: ")
    return code

def get_anilist_access_token(client_id, client_secret, redirect_url, code):
    """Exchange authorization code for access token."""
    log("Requesting access token from Anilist")
    try:
        response = requests.post(
            "https://anilist.co/api/v2/oauth/token",
            json={
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_url,
                'code': code
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            access_token = data.get('access_token')
            if access_token:
                log("Successfully obtained access token")
                return access_token
        
        log(f"Failed to get access token: {response.status_code} {response.text}")
    except Exception as e:
        log(f"Error requesting access token: {e}")
    
    return None

def get_anilist_authenticated_user_id(access_token):
    """Get authenticated user ID using access token."""
    log("Getting authenticated user ID")
    try:
        response = requests.post(
            ANILIST_API,
            json=query_authenticated_user(),
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('data') and data['data'].get('Viewer'):
                user_id = data['data']['Viewer']['id']
                username = data['data']['Viewer']['name']
                log(f"Authenticated as: {username} (ID: {user_id})")
                return user_id
        
        log(f"Failed to get authenticated user: {response.status_code}")
    except Exception as e:
        log(f"Error fetching authenticated user: {e}")
    
    return None

def get_anilist_user_id(username):
    """Get user ID for a specific Anilist username."""
    log(f"Getting user ID for Anilist username: {username}")
    try:
        response = requests.post(ANILIST_API, json=query_user_id(username))
        if response.status_code == 200:
            data = response.json()
            if data.get('data') and data['data'].get('User'):
                user_id = data['data']['User']['id']
                log(f"Found user ID: {user_id}")
                return user_id
            else:
                log(f"User not found: {username}")
        else:
            log(f"API error: {response.status_code}")
    except Exception as e:
        log(f"Error fetching user ID: {e}")
    
    return None

def get_anilist_manga_list(user_id, access_token=None):
    """Fetch manga list from Anilist for the given user ID."""
    log(f"Fetching manga list for user ID: {user_id}")
    query = {
        'query': query_manga_list(),
        'variables': {
            'userID': user_id
        }
    }
    
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    
    try:
        response = requests.post(ANILIST_API, json=query, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            log(f"API error: {response.status_code} {response.text}")
    except Exception as e:
        log(f"Error fetching manga list: {e}")
    
    return None

# Protobuf schema generation
def fetch_schema(fork):
    files = []
    log(f"Fetching schema from {fork}")
    git = requests.get(
        f'https://api.github.com/repos/{fork}/contents/app/src/main/java/eu/kanade/tachiyomi/data/backup/models'
    ).json()
    
    for entry in git:
        if entry.get('type') == 'file':
            files.append((entry.get('name'), entry.get('download_url')))
        elif entry.get('type') == 'dir':
            for sub_entry in requests.get(entry.get('url')).json():
                if sub_entry.get('type') == 'file':
                    files.append((sub_entry.get('name'), sub_entry.get('download_url')))
    return files

def parse_model(model):
    data = requests.get(model).text
    message = []
    for name in re.finditer(CLASS_RE, data, re.MULTILINE):
        message.append('message {name} {{'.format(name=name.group('name')))
        for field in re.finditer(PROTONUMBER_RE, name.group('defs'), re.MULTILINE):
            message.append(
                '  {repeated} {type} {name} = {number};'.format(
                    repeated='repeated'
                    if field.group('list')
                    else 'optional'
                    if field.group('optional')
                    else 'required',
                    type=DATA_TYPES.get(
                        field.group('type'),
                        DATA_TYPES.get(
                            field.group('list'),
                            field.group('list') or field.group('type'),
                        ),
                    ),
                    name=field.group('name'),
                    number=field.group('number') or 1
                    if not name.group('name').startswith('Broken')
                    else int(field.group('number')) + 1,
                )
            )
        message.append('}\n')
    return message

def generate_protobuf_schema(fork='mihon', output_file='schema.proto'):
    # Hard-coded exceptions to make parsing easier
    schema = '''syntax = "proto2";

enum UpdateStrategy {
  ALWAYS_UPDATE = 0;
  ONLY_FETCH_ONCE = 1;
}

message PreferenceValue {
  required string type = 1;
  required bytes truevalue = 2;
}

'''.splitlines()
    
    log(f"Fetching schema from {fork}")
    for i in fetch_schema(FORKS[fork]):
        log(f"Parsing {i[0]}")
        schema.append(f'// {i[0]}')
        schema.extend(parse_model(i[1]))
    
    log(f"Writing schema to {output_file}")
    with open(output_file, 'wt') as f:
        f.write('\n'.join(schema))
    
    return output_file

def ensure_protobuf_module(fork='mihon'):
    schema_file = f'schema-{fork}.proto'
    try:
        # Try to import the module
        from schema_pb2 import Backup
        log("Protobuf module found")
        return True
    except (ImportError, ModuleNotFoundError):
        log("Protobuf module not found, generating schema...")
        generate_protobuf_schema(fork, schema_file)
        
        try:
            log("Compiling protobuf schema...")
            run(['protoc', '--python_out=.', '--pyi_out=.', schema_file])
            from schema_pb2 import Backup
            return True
        except Exception as e:
            log(f"Error compiling protobuf schema: {e}")
            log("Please install protoc: https://github.com/protocolbuffers/protobuf/releases/latest")
            return False

# Safely set attributes on protobuf objects
def safe_set_attribute(obj, attr_name, value):
    """Safely set attribute on a protobuf object."""
    if hasattr(obj, attr_name):
        try:
            # Handle repeated fields (lists)
            attr = getattr(obj, attr_name)
            if hasattr(attr, 'append'):
                # It's a repeated field
                if isinstance(value, list):
                    for item in value:
                        attr.append(item)
                else:
                    attr.append(value)
            else:
                # Regular field
                setattr(obj, attr_name, value)
            return True
        except Exception as e:
            log(f"Warning: Could not set {attr_name} to {value}: {e}")
    return False

# Functions for reading/writing backup files
def read_backup(input_file):
    """Read a backup file and return its content."""
    log(f"Reading backup file: {input_file}")
    if input_file.endswith('.tachibk') or input_file.endswith('.proto.gz'):
        with gzip.open(input_file, 'rb') as zip_file:
            backup_data = zip_file.read()
    else:
        with open(input_file, 'rb') as file:
            backup_data = file.read()
    return backup_data

def parse_backup(backup_data):
    """Parse backup data into a Backup object."""
    from schema_pb2 import Backup
    message = Backup()
    message.ParseFromString(backup_data)
    return message

def backup_to_dict(backup):
    """Convert a Backup object to a dictionary."""
    return MessageToDict(backup)

def dict_to_backup(backup_dict):
    """Convert a dictionary to a Backup object."""
    from schema_pb2 import Backup
    return Parse(json.dumps(backup_dict), Backup())

def write_backup(backup, output_file):
    """Write a Backup object to a file."""
    log(f"Writing backup to: {output_file}")
    backup_data = backup.SerializeToString()
    
    if output_file.endswith('.tachibk') or output_file.endswith('.proto.gz'):
        with gzip.open(output_file, 'wb') as zip_file:
            zip_file.write(backup_data)
        log(f"Compressed backup written to {output_file}")
    else:
        with open(output_file, 'wb') as file:
            file.write(backup_data)
        log(f"Uncompressed backup written to {output_file}")

def write_json(backup, output_file, convert_preferences=False):
    """Write a Backup object to a JSON file."""
    log(f"Writing JSON to: {output_file}")
    message_dict = MessageToDict(backup)
    
    if convert_preferences:
        log("Converting preferences to readable format...")
        # Implementation for preference conversion would go here
    
    with open(output_file, 'wt', encoding='utf-8') as file:
        json.dump(message_dict, file, indent=2, ensure_ascii=False)
    log(f"JSON written to {output_file}")

# Preference handling functions
def readable_preference(preference_value):
    """Convert a preference value to human-readable format."""
    true_value = preference_value['value']['truevalue']
    preference_type = preference_value['value']['type'].split('.')[-1].removesuffix('PreferenceValue')
    
    try:
        if preference_type == 'Boolean':
            return bool(varint.decode_bytes(b64decode(true_value)[1:]))
        elif preference_type in ['Int', 'Long']:
            return varint.decode_bytes(b64decode(true_value)[1:])
        elif preference_type == 'Float':
            return unpack('f', b64decode(true_value)[1:])[0]
        elif preference_type == 'String':
            return b64decode(true_value)[2:].decode('utf-8')
        elif preference_type == 'StringSet':
            bar = list(b64decode(true_value))
            new_list = []
            for byte in bar:
                if byte == bar[0]:
                    new_list.append([])
                    continue
                new_list[-1].append(byte)
            for index, entry in enumerate(new_list):
                new_list[index] = bytes(entry[1:]).decode('utf-8')
            return new_list
        else:
            return true_value
    except Exception as e:
        log(f"Error converting preference: {e}")
        return true_value

def bytes_preference(preference_value):
    """Convert a human-readable preference value back to bytes format."""
    true_value = preference_value['value']['truevalue']
    preference_type = preference_value['value']['type'].split('.')[-1].removesuffix('PreferenceValue')
    
    try:
        if preference_type == 'Boolean':
            return b64encode(b'\x08' + int(true_value).to_bytes()).decode()
        elif preference_type in ['Int', 'Long']:
            return b64encode(b'\x08' + varint.encode(true_value)).decode()
        elif preference_type == 'Float':
            return b64encode(b'\r' + pack('f', true_value)).decode()
        elif preference_type == 'String':
            return b64encode(b'\n' + len(true_value).to_bytes() + true_value.encode()).decode()
        elif preference_type == 'StringSet':
            new_bytes = b''
            for val in true_value:
                new_bytes += b'\n' + len(val).to_bytes() + val.encode()
            return b64encode(new_bytes).decode()
        else:
            return true_value
    except Exception as e:
        log(f"Error converting preference: {e}")
        return true_value

# Tachiyomi backup manipulation functions
def convert_manga_to_tachiyomi_format(manga_items):
    """Convert Anilist manga items to Tachiyomi backup format"""
    from schema_pb2 import Backup
    
    # Create a new backup
    backup = Backup()
    
    # Map Anilist status to Tachiyomi status
    status_map = {
        "CURRENT": 1,      # READING
        "PLANNING": 2,     # PLAN_TO_READ
        "COMPLETED": 3,    # COMPLETED
        "DROPPED": 4,      # DROPPED
        "PAUSED": 5,       # ON_HOLD
        "REPEATING": 1     # Map to READING
    }
    
    for item in manga_items:
        # Add a new manga entry to the backup
        manga = backup.backupManga.add()
        
        # Set manga source info
        media = item['media']
        safe_set_attribute(manga, 'source', 6902)  # This is the ID for Mangadex, can also be swapped for 0 as a placeholder
        
        # Set manga title - prefer English title, fallback to romaji
        title = media['title']['english'] if media['title']['english'] else media['title']['romaji']
        safe_set_attribute(manga, 'title', title)
            
        # Create URL for Anilist
        url = f"https://anilist.co/manga/{media['id']}"
        safe_set_attribute(manga, 'url', url)
        
        # Set author field - Anilist doesn't provide this directly
        safe_set_attribute(manga, 'author', "")
        
        # Add synonyms as genre tags
        for synonym in media.get('synonyms', []):
            if synonym and hasattr(manga, 'genre') and hasattr(manga.genre, 'append'):
                manga.genre.append(synonym)
        
        # Set status from Anilist to Tachiyomi status
        anilist_status = item.get('status', 'PLANNING')
        tachi_status = status_map.get(anilist_status, 2)  # Default to PLAN_TO_READ
        safe_set_attribute(manga, 'status', tachi_status)
        
        # Set chapter progress
        progress = item.get('progress', 0)
        if progress > 0:
            safe_set_attribute(manga, 'lastRead', float(progress))
        
        # Add chapters if available (not directly available from Anilist)
        total_chapters = media.get('chapters', 0)
        if total_chapters and total_chapters > 0 and progress > 0:
            # This approach doesn't rely on hardcoded class names
            try:
                # Check if we have a chapters attribute
                if hasattr(manga, 'chapters'):
                    for i in range(1, progress + 1):
                        # Create a new chapter
                        chapter = manga.chapters.add()
                        
                        # Set chapter properties
                        safe_set_attribute(chapter, 'url', f"{url}/chapter/{i}")
                        safe_set_attribute(chapter, 'name', f"Chapter {i}")
                        safe_set_attribute(chapter, 'chapterNumber', float(i))
                        safe_set_attribute(chapter, 'read', True)
                        safe_set_attribute(chapter, 'lastPageRead', 1)  # Mark as read
            except Exception as e:
                log(f"Warning: Could not add chapter info for {title}: {e}")
    
    return backup

def create_tachiyomi_backup(anilist_data, output_file, status_filter='all'):
    """Create a Tachiyomi backup file from Anilist data with optional status filtering"""
    # Extract manga entries from Anilist data
    manga_items = []
    if anilist_data and 'data' in anilist_data and 'MediaListCollection' in anilist_data['data']:
        lists = anilist_data['data']['MediaListCollection']['lists']
        for list_item in lists:
            list_status = list_item['status']
            
            # Filter by status if specified
            if status_filter != 'all':
                status_filters = status_filter.split(',')
                if list_status not in status_filters:
                    log(f"Skipping list with status: {list_status} (not in filter)")
                    continue
            
            log(f"Including list with status: {list_status}")
            manga_items.extend(list_item['entries'])
    
    log(f"Found {len(manga_items)} manga entries after filtering")
    
    # Convert to Tachiyomi format
    backup = convert_manga_to_tachiyomi_format(manga_items)
    
    # Write to file
    write_backup(backup, output_file)
    
    return output_file

def export_anilist_manga_data(anilist_data, output_file, status_filter='all'):
    """
    Exports detailed manga information from Anilist to a JSON file.
    
    Args:
        anilist_data: The manga data from Anilist
        output_file: Path to save the JSON data
        status_filter: Optional filter for manga status
    """
    manga_details = []
    
    if anilist_data and 'data' in anilist_data and 'MediaListCollection' in anilist_data['data']:
        lists = anilist_data['data']['MediaListCollection']['lists']
        
        for list_item in lists:
            list_status = list_item['status']
            
            # Filter by status if specified
            if status_filter != 'all':
                status_filters = status_filter.split(',')
                if list_status not in status_filters:
                    log(f"Skipping list with status: {list_status} (not in filter)")
                    continue
            
            log(f"Processing list with status: {list_status}")
            
            for entry in list_item['entries']:
                media = entry['media']
                
                # Extract all relevant title information
                manga_info = {
                    'anilist_id': media['id'],
                    'mal_id': media.get('idMal'),
                    'titles': {
                        'english': media['title'].get('english'),
                        'romaji': media['title'].get('romaji'),
                        'native': media['title'].get('native')
                    },
                    'synonyms': media.get('synonyms', []),
                    'status': entry.get('status'),
                    'progress': entry.get('progress', 0),
                    'score': entry.get('score'),
                    'format': media.get('format'),
                    'chapters': media.get('chapters'),
                    'volumes': media.get('volumes')
                }
                
                manga_details.append(manga_info)
    
    log(f"Exporting information for {len(manga_details)} manga to {output_file}")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    
    # Write to JSON file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(manga_details, f, ensure_ascii=False, indent=2)
    
    return manga_details


def find_potential_duplicates(backup_file, anilist_json_file, output_report):
    """
    Finds potential duplicates within a Tachiyomi backup.
    Uses AniList JSON data ONLY to enhance duplicate detection through alternative titles,
    but ensures that all reported duplicates actually exist in the backup.
    
    Args:
        backup_file: Path to Tachiyomi backup file
        anilist_json_file: Path to AniList JSON data file
        output_report: Path to save the duplicate report
    """
    log(f"Finding potential duplicates in {backup_file} using titles from {anilist_json_file}")
    
    # Read backup file
    try:
        backup_data = read_backup(backup_file)
        backup = parse_backup(backup_data)
    except Exception as e:
        log(f"Error reading backup file: {e}")
        return False
    
    # Read AniList JSON data
    try:
        with open(anilist_json_file, 'r', encoding='utf-8') as f:
            anilist_manga = json.load(f)
    except Exception as e:
        log(f"Error reading AniList JSON file: {e}")
        return False
    
    # Define normalization function
    def normalize_title(title):
        if not title:
            return ""
        # Convert to lowercase and remove ALL non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', title.lower())
    
    # Extract titles from backup
    backup_manga = []
    for idx, manga in enumerate(backup.backupManga):
        title = getattr(manga, 'title', '').strip()
        source = getattr(manga, 'source', 'Unknown')
        url = getattr(manga, 'url', '')
        
        # Extract ID from URL if possible
        url_id = None
        if url:
            if 'anilist.co/manga/' in url:
                try:
                    url_id = int(url.split('anilist.co/manga/')[1].split('/')[0])
                except:
                    pass
            elif 'myanimelist.net/manga/' in url:
                try:
                    url_id = int(url.split('myanimelist.net/manga/')[1].split('/')[0])
                except:
                    pass
        
        if title:  # Only process entries with titles
            backup_manga.append({
                'index': idx,
                'title': title,
                'normalized_title': normalize_title(title),
                'source': source,
                'url': url,
                'url_id': url_id
            })
    
    log(f"Found {len(backup_manga)} manga in backup")
    
    # Create dictionaries for alternative title mapping from AniList
    anilist_id_map = {}
    title_to_anilist = {}
    
    # Build AniList title mapping (used only for enhanced matching)
    for manga in anilist_manga:
        anilist_id = manga.get('anilist_id')
        
        if anilist_id:
            anilist_id_map[anilist_id] = manga
        
        # Collect all possible titles for this manga
        all_titles = []
        
        # Add main titles
        for title_type, title in manga['titles'].items():
            if title:
                all_titles.append(title)
                norm_title = normalize_title(title)
                if norm_title:
                    title_to_anilist[norm_title] = manga
        
        # Add synonyms
        for synonym in manga.get('synonyms', []):
            if synonym:
                all_titles.append(synonym)
                norm_synonym = normalize_title(synonym)
                if norm_synonym:
                    title_to_anilist[norm_synonym] = manga
    
    # Now find potential duplicates ONLY within the backup
    duplicate_groups = []
    processed_indices = set()
    
    for idx, manga in enumerate(backup_manga):
        if idx in processed_indices:
            continue
            
        # Find all potential duplicates of this manga
        matched_entries = [manga]  # Always include the current manga
        processed_indices.add(idx)
        
        # Get enhanced title info from AniList if available
        enhanced_titles = set([manga['normalized_title']])
        matched_anilist = None
        
        # Try to find AniList entry by URL ID
        if manga['url_id'] and 'anilist.co/manga/' in manga['url']:
            if manga['url_id'] in anilist_id_map:
                matched_anilist = anilist_id_map[manga['url_id']]
        
        # If no match by URL ID, try by title
        if not matched_anilist and manga['normalized_title'] in title_to_anilist:
            matched_anilist = title_to_anilist[manga['normalized_title']]
        
        # If we have a match from AniList, add all its alternative titles
        if matched_anilist:
            # Add all possible normalized titles from AniList
            for title_type, title in matched_anilist['titles'].items():
                if title:
                    enhanced_titles.add(normalize_title(title))
            
            for synonym in matched_anilist.get('synonyms', []):
                if synonym:
                    enhanced_titles.add(normalize_title(synonym))
        
        # Now look for duplicates in the backup using these enhanced titles
        for compare_idx, compare_manga in enumerate(backup_manga):
            if compare_idx == idx or compare_idx in processed_indices:
                continue
            
            # Check if this is a duplicate based on normalized title
            if compare_manga['normalized_title'] in enhanced_titles:
                matched_entries.append(compare_manga)
                processed_indices.add(compare_idx)
                continue
            
            # If titles don't match but URLs contain same ID, it's a duplicate
            if manga['url_id'] and compare_manga['url_id']:
                if manga['url_id'] == compare_manga['url_id']:
                    matched_entries.append(compare_manga)
                    processed_indices.add(compare_idx)
                    continue
            
            # Use fuzzy matching as a last resort (only between backup entries)
            if fuzz.ratio(manga['title'], compare_manga['title']) > 90:  # Increased threshold
                matched_entries.append(compare_manga)
                processed_indices.add(compare_idx)
        
        # Only add as a duplicate group if we found more than one entry
        if len(matched_entries) > 1:
            duplicate_groups.append({
                'anilist_manga': matched_anilist,  # For reference only
                'match_type': "Similar Title" if not matched_anilist else "AniList Match",
                'backup_matches': matched_entries
            })
    
    log(f"Found {len(duplicate_groups)} potential duplicate groups")
    
    # Generate report
    with open(output_report, 'w', encoding='utf-8') as f:
        f.write("# Potential Duplicate Manga Report\n\n")
        f.write(f"Analyzing backup file: {backup_file}\n")
        f.write(f"With AniList data from: {anilist_json_file}\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write(f"## Summary\n\n")
        f.write(f"- Total manga in backup: {len(backup_manga)}\n")
        f.write(f"- Potential duplicate groups found: {len(duplicate_groups)}\n")
        
        if duplicate_groups:
            total_dupes = sum(len(group['backup_matches']) for group in duplicate_groups) - len(duplicate_groups)
            f.write(f"- Total potential duplicate entries: {total_dupes}\n\n")
        
            f.write("## Potential Duplicates\n\n")
            
            for idx, duplicate in enumerate(duplicate_groups, 1):
                anilist_item = duplicate['anilist_manga']
                match_type = duplicate['match_type']
                matches = duplicate['backup_matches']
                
                # Get a representative title for the group
                main_title = matches[0]['title']
                
                # Add AniList info if available (for reference only)
                if anilist_item:
                    f.write(f"### {idx}. {match_type}: {main_title}\n\n")
                    
                    f.write("**AniList Reference Info:**\n")
                    f.write(f"- ID: {anilist_item['anilist_id']}\n")
                    if anilist_item.get('mal_id'):
                        f.write(f"- MyAnimeList ID: {anilist_item['mal_id']}\n")
                    
                    f.write("\n**Known AniList Titles:**\n")
                    for title_type, title in anilist_item['titles'].items():
                        if title:
                            f.write(f"- {title_type.capitalize()}: {title}\n")
                    
                    if anilist_item.get('synonyms'):
                        f.write("\n**Alternative Titles:**\n")
                        for synonym in anilist_item['synonyms']:
                            if synonym:
                                f.write(f"- {synonym}\n")
                else:
                    # No AniList data, just use the title
                    f.write(f"### {idx}. Similar Title Match: {main_title}\n\n")
                
                f.write("\n**Matching entries in backup:**\n\n")
                
                # Write matching backup entries
                for m_idx, backup_match in enumerate(matches, 1):
                    f.write(f"{m_idx}. **{backup_match['title']}**\n")
                    f.write(f"   - Source: {backup_match['source']}\n")
                    if backup_match['url']:
                        f.write(f"   - URL: {backup_match['url']}\n")
                    f.write("\n")
                
                f.write("---\n\n")
        else:
            f.write("\n**No duplicates found.**\n")
    
    log(f"Duplicate report written to: {output_report}")
    return True

# Add fuzzy matching for better title comparisons
def setup_fuzzy_matching():
    """Ensures the fuzzywuzzy library is available"""
    try:
        global fuzz
        from fuzzywuzzy import fuzz
        log("Fuzzy matching library loaded")
        return True
    except ImportError:
        log("Fuzzy matching library not available - install with: pip install fuzzywuzzy")
        log("Using basic matching only")
        
        # Create a simple fallback if fuzzywuzzy is not available
        class SimpleFuzz:
            @staticmethod
            def ratio(s1, s2):
                # Simple matching ratio based on common substrings
                # Returns a value between 0-100
                if not s1 or not s2:
                    return 0
                
                # Use a simple Jaccard similarity
                set1 = set(s1.split())
                set2 = set(s2.split())
                
                intersection = len(set1.intersection(set2))
                union = len(set1.union(set2))
                
                if union == 0:
                    return 0
                
                return (intersection / union) * 100
        
        global fuzz
        fuzz = SimpleFuzz()
        return False

# New functions for removing duplicates inside backups

def cleanup_backup(input_file, output_file, mode='keep_first', report_file=None):
    """Clean up a backup file by removing duplicate manga entries.
    
    Args:
        input_file: Input backup file (.tachibk, .proto.gz, or .json)
        output_file: Output cleaned backup file
        mode: Cleanup mode ('keep_first' or 'keep_last')
             - keep_first: Keep the first occurrence of each manga title
             - keep_last: Keep the last occurrence of each manga title
        report_file: Optional path to write a report of removed duplicates
    """
    log(f"Cleaning up backup file: {input_file} using mode: {mode}")
    
    try:
        # Read the backup file
        if input_file.lower().endswith('.json'):
            with open(input_file, 'r', encoding='utf-8') as file:
                backup_dict = json.load(file)
            backup = dict_to_backup(backup_dict)
        else:
            backup_data = read_backup(input_file)
            backup = parse_backup(backup_data)
        
        # Dictionary to track unique manga by title
        manga_dict = {}
        duplicates_found = 0
        
        # Keep track of removed duplicates for reporting
        removed_duplicates = []
        kept_entries = []
        
        # Process each manga entry
        for idx, manga in enumerate(backup.backupManga):
            title = getattr(manga, 'title', 'Unknown')
            source = getattr(manga, 'source', 'Unknown')
            url = getattr(manga, 'url', 'Not available')
            
            manga_info = {
                'title': title,
                'source': source,
                'url': url,
                'index': idx
            }
            
            if title in manga_dict:
                duplicates_found += 1
                log(f"Found duplicate: {title}")
                
                if mode == 'keep_last':
                    # Replace the existing entry with this one
                    # First, add the current one to removed list
                    removed_duplicates.append(manga_dict[title])
                    # Then replace with new one
                    manga_dict[title] = manga_info
                    kept_entries.append(manga_info)
                else:  # keep_first
                    # Keep the first entry, add this one to removed list
                    removed_duplicates.append(manga_info)
            else:
                # Add new unique entry
                manga_dict[title] = manga_info
                kept_entries.append(manga_info)
        
        # Create a new backup with unique entries
        from schema_pb2 import Backup
        cleaned_backup = Backup()
        
        # Add all unique manga to the cleaned backup
        for entry in kept_entries:
            manga = backup.backupManga[entry['index']]
            cleaned_backup.backupManga.append(manga)
        
        # Copy other elements from original backup
        if hasattr(backup, 'backupPreferences') and backup.backupPreferences:
            cleaned_backup.backupPreferences.extend(backup.backupPreferences)
        
        if hasattr(backup, 'backupSourcePreferences') and backup.backupSourcePreferences:
            cleaned_backup.backupSourcePreferences.extend(backup.backupSourcePreferences)
        
        if hasattr(backup, 'backupExtensions') and backup.backupExtensions:
            cleaned_backup.backupExtensions.extend(backup.backupExtensions)
        
        # Write the cleaned backup
        write_backup(cleaned_backup, output_file)
        
        # Generate report file if specified
        if report_file:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(f"# Tachiyomi Backup Cleanup Report\n\n")
                f.write(f"- Original file: {input_file}\n")
                f.write(f"- Cleaned file: {output_file}\n")
                f.write(f"- Mode: {mode}\n")
                f.write(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write(f"## Summary\n\n")
                f.write(f"- Original manga entries: {len(backup.backupManga)}\n")
                f.write(f"- Duplicate entries removed: {duplicates_found}\n")
                f.write(f"- Final manga entries: {len(cleaned_backup.backupManga)}\n\n")
                
                f.write(f"## Removed Duplicate Entries\n\n")
                if not removed_duplicates:
                    f.write("No duplicates found.\n\n")
                else:
                    for idx, entry in enumerate(removed_duplicates):
                        f.write(f"{idx+1}. **{entry['title']}**\n")
                        f.write(f"   - Source: {entry['source']}\n")
                        f.write(f"   - URL: {entry['url']}\n\n")
                
                f.write(f"## Kept Entries\n\n")
                for idx, entry in enumerate(kept_entries):
                    f.write(f"{idx+1}. **{entry['title']}**\n")
                    f.write(f"   - Source: {entry['source']}\n")
                    f.write(f"   - URL: {entry['url']}\n\n")
            
            log(f"Report generated at: {report_file}")
        
        log(f"Cleanup complete. Found and removed {duplicates_found} duplicates.")
        log(f"Original backup had {len(backup.backupManga)} manga entries.")
        log(f"Cleaned backup has {len(cleaned_backup.backupManga)} manga entries.")
        
        return True
    
    except Exception as e:
        log(f"Error cleaning up backup: {e}")
        return False

# New functions for merging backups
def merge_backups(input_files, output_file, mode='replace', report_file=None):
    """Merge multiple backup files into one.
    
    Args:
        input_files: List of input backup files (.tachibk, .proto.gz, or .json)
        output_file: Output file path
        mode: Merge mode ('replace', 'keep_first', or 'keep_both')
             - replace: Replace entries with the same title
             - keep_first: Keep the first entry if duplicate title is found
             - keep_both: Keep both entries even if they have the same title
        report_file: Optional path to write a report of merged entries
    """
    if not input_files:
        log("No input files provided for merging")
        return False
    
    log(f"Merging {len(input_files)} backup files using mode: {mode}")
    
    # Create an empty backup to start
    from schema_pb2 import Backup
    merged_backup = Backup()
    
    # Dictionary to track manga by title for duplicate handling
    manga_dict = {}
    
    # Keep track of merge operations for reporting
    added_entries = []  # New entries added
    replaced_entries = []  # Entries that replaced others
    skipped_entries = []  # Entries skipped due to keep_first
    duplicate_entries = []  # Entries kept as duplicates
    
    # Track which file each entry came from
    file_tracking = {}
    
    # Process each input file
    for file_idx, input_file in enumerate(input_files):
        log(f"Processing file: {input_file}")
        try:
            # Handle different file types based on extension
            if input_file.lower().endswith('.json'):
                # For JSON files
                log(f"Detected JSON file: {input_file}")
                with open(input_file, 'r', encoding='utf-8') as file:
                    backup_dict = json.load(file)
                backup = dict_to_backup(backup_dict)
            else:
                # For .tachibk or .proto.gz files
                log(f"Detected backup file: {input_file}")
                backup_data = read_backup(input_file)
                backup = parse_backup(backup_data)
            
            # Add manga entries based on merge mode
            for manga_idx, manga in enumerate(backup.backupManga):
                # Use title as the key for merging
                title = getattr(manga, 'title', 'Unknown')
                source = getattr(manga, 'source', 'Unknown')
                url = getattr(manga, 'url', 'Not available')
                
                manga_info = {
                    'title': title,
                    'source': source,
                    'url': url,
                    'file': input_file,
                    'file_idx': file_idx,
                    'manga_idx': manga_idx
                }
                
                if title in manga_dict:
                    if mode == 'replace':
                        # Record the replaced entry
                        replaced_entries.append({
                            'old': manga_dict[title],
                            'new': manga_info
                        })
                        
                        manga_dict[title] = manga_info
                        file_tracking[f"{file_idx}_{manga_idx}"] = manga
                        log(f"Replaced manga: {title}")
                    elif mode == 'keep_first':
                        log(f"Keeping first occurrence of manga: {title}")
                        # Record the skipped entry
                        skipped_entries.append({
                            'kept': manga_dict[title],
                            'skipped': manga_info
                        })
                    elif mode == 'keep_both':
                        # Add as a new entry
                        unique_key = f"{title}_duplicate_{len([k for k in manga_dict.keys() if k.startswith(title)])}"
                        manga_dict[unique_key] = manga_info
                        file_tracking[f"{file_idx}_{manga_idx}"] = manga
                        
                        # Record the duplicate entry
                        duplicate_entries.append({
                            'original': manga_dict[title],
                            'duplicate': manga_info,
                            'new_key': unique_key
                        })
                        log(f"Keeping duplicate manga: {title} (as {unique_key})")
                else:
                    manga_dict[title] = manga_info
                    file_tracking[f"{file_idx}_{manga_idx}"] = manga
                    
                    # Record the added entry
                    added_entries.append(manga_info)
                    log(f"Added manga: {title}")
            
            # Add other backup elements (preferences, extensions, etc.)
            # Note: This simple implementation prioritizes the last file's elements
            if hasattr(backup, 'backupPreferences') and backup.backupPreferences:
                merged_backup.ClearField('backupPreferences')
                merged_backup.backupPreferences.extend(backup.backupPreferences)
            
            if hasattr(backup, 'backupSourcePreferences') and backup.backupSourcePreferences:
                merged_backup.ClearField('backupSourcePreferences')
                merged_backup.backupSourcePreferences.extend(backup.backupSourcePreferences)
            
            if hasattr(backup, 'backupExtensions') and backup.backupExtensions:
                merged_backup.ClearField('backupExtensions')
                merged_backup.backupExtensions.extend(backup.backupExtensions)
                
        except Exception as e:
            log(f"Error processing file {input_file}: {e}", "error")
            # Continue with other files even if one fails
    
    # Add all manga to the merged backup
    merged_backup.ClearField('backupManga')
    for key, info in manga_dict.items():
        file_idx = info['file_idx']
        manga_idx = info['manga_idx']
        manga = file_tracking[f"{file_idx}_{manga_idx}"]
        merged_backup.backupManga.append(manga)
    
    log(f"Merged backup contains {len(merged_backup.backupManga)} manga entries")
    
    # Generate report file if specified
    if report_file:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"# Tachiyomi Backup Merge Report\n\n")
            f.write(f"- Output file: {output_file}\n")
            f.write(f"- Merge mode: {mode}\n")
            f.write(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"## Input Files\n\n")
            for idx, file in enumerate(input_files):
                f.write(f"{idx+1}. {file}\n")
            f.write("\n")
            
            f.write(f"## Summary\n\n")
            f.write(f"- Total manga entries in merged backup: {len(merged_backup.backupManga)}\n")
            f.write(f"- New entries added: {len(added_entries)}\n")
            f.write(f"- Entries replaced: {len(replaced_entries)}\n")
            f.write(f"- Entries kept as duplicates: {len(duplicate_entries)}\n")
            f.write(f"- Entries skipped: {len(skipped_entries)}\n\n")
            
            if added_entries:
                f.write(f"## New Entries Added\n\n")
                for idx, entry in enumerate(added_entries):
                    f.write(f"{idx+1}. **{entry['title']}**\n")
                    f.write(f"   - Source: {entry['source']}\n")
                    f.write(f"   - URL: {entry['url']}\n")
                    f.write(f"   - From file: {entry['file']}\n\n")
            
            if replaced_entries:
                f.write(f"## Replaced Entries\n\n")
                for idx, entry in enumerate(replaced_entries):
                    f.write(f"{idx+1}. **{entry['new']['title']}**\n")
                    f.write(f"   - **Original**:\n")
                    f.write(f"     - Source: {entry['old']['source']}\n")
                    f.write(f"     - URL: {entry['old']['url']}\n")
                    f.write(f"     - From file: {entry['old']['file']}\n")
                    f.write(f"   - **Replaced with**:\n")
                    f.write(f"     - Source: {entry['new']['source']}\n")
                    f.write(f"     - URL: {entry['new']['url']}\n")
                    f.write(f"     - From file: {entry['new']['file']}\n\n")
            
            if duplicate_entries:
                f.write(f"## Duplicate Entries Kept\n\n")
                for idx, entry in enumerate(duplicate_entries):
                    f.write(f"{idx+1}. **{entry['original']['title']}**\n")
                    f.write(f"   - **Original**:\n")
                    f.write(f"     - Source: {entry['original']['source']}\n")
                    f.write(f"     - URL: {entry['original']['url']}\n")
                    f.write(f"     - From file: {entry['original']['file']}\n")
                    f.write(f"   - **Duplicate (stored as {entry['new_key']})**:\n")
                    f.write(f"     - Source: {entry['duplicate']['source']}\n")
                    f.write(f"     - URL: {entry['duplicate']['url']}\n")
                    f.write(f"     - From file: {entry['duplicate']['file']}\n\n")
            
            if skipped_entries:
                f.write(f"## Skipped Entries\n\n")
                for idx, entry in enumerate(skipped_entries):
                    f.write(f"{idx+1}. **{entry['skipped']['title']}**\n")
                    f.write(f"   - **Kept**:\n")
                    f.write(f"     - Source: {entry['kept']['source']}\n")
                    f.write(f"     - URL: {entry['kept']['url']}\n")
                    f.write(f"     - From file: {entry['kept']['file']}\n")
                    f.write(f"   - **Skipped**:\n")
                    f.write(f"     - Source: {entry['skipped']['source']}\n")
                    f.write(f"     - URL: {entry['skipped']['url']}\n")
                    f.write(f"     - From file: {entry['skipped']['file']}\n\n")
        
        log(f"Report generated at: {report_file}")
    
    # Write the merged backup
    write_backup(merged_backup, output_file)
    log(f"Merged backup written to {output_file}")
    
    return True

def create_tachiyomi_backup_with_compare(anilist_data, output_file, status_filter='all', compare_backup=None):
    """Create a Tachiyomi backup file from Anilist data with comparison to existing backup"""
    
    # Load comparison backup if provided
    existing_manga_titles = set()
    existing_manga_urls = set()  # Add URL tracking
    merged_backup = None
    
    # Define an ultra-aggressive normalization function that removes ALL non-alphanumeric characters
    def normalize_title_for_comparison(title):
        if not title:
            return ""
        # Convert to lowercase and remove ALL non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', title.lower())
    
    if compare_backup:
        log(f"Comparing with existing backup: {compare_backup}")
        try:
            # Read the existing backup
            backup_data = read_backup(compare_backup)
            existing_backup = parse_backup(backup_data)
            
            # Create new backup starting with everything from existing backup
            from schema_pb2 import Backup
            merged_backup = Backup()
            
            # Copy all manga entries from existing backup
            for manga in existing_backup.backupManga:
                merged_backup.backupManga.append(manga)
                
                # Extract identifiers for duplicate detection
                title = getattr(manga, 'title', '').strip()
                url = getattr(manga, 'url', '').strip()
                
                # Store ultra-normalized version of title for comparison
                if title:
                    existing_manga_titles.add(normalize_title_for_comparison(title))
                
                # Extract AniList ID from URL if it exists
                if url and 'anilist.co/manga/' in url:
                    try:
                        anilist_id = url.split('anilist.co/manga/')[1].split('/')[0]
                        existing_manga_urls.add(f"anilist:{anilist_id}")
                    except:
                        pass
            
            # Copy other elements (preferences, extensions, etc.)
            if hasattr(existing_backup, 'backupPreferences') and existing_backup.backupPreferences:
                merged_backup.backupPreferences.extend(existing_backup.backupPreferences)
            
            if hasattr(existing_backup, 'backupSourcePreferences') and existing_backup.backupSourcePreferences:
                merged_backup.backupSourcePreferences.extend(existing_backup.backupSourcePreferences)
            
            if hasattr(existing_backup, 'backupExtensions') and existing_backup.backupExtensions:
                merged_backup.backupExtensions.extend(existing_backup.backupExtensions)
            
            log(f"Copied {len(existing_manga_titles)} manga titles from existing backup")
            
        except Exception as e:
            log(f"Error reading comparison backup: {e}")
            log("Proceeding without comparison")
            existing_manga_titles = set()
            existing_manga_urls = set()
            merged_backup = None
    
    # Extract manga entries from Anilist data
    manga_items = []
    skipped_items = []
    if anilist_data and 'data' in anilist_data and 'MediaListCollection' in anilist_data['data']:
        lists = anilist_data['data']['MediaListCollection']['lists']
        for list_item in lists:
            list_status = list_item['status']
            
            # Filter by status if specified
            if status_filter != 'all':
                status_filters = status_filter.split(',')
                if list_status not in status_filters:
                    log(f"Skipping list with status: {list_status} (not in filter)")
                    continue
            
            log(f"Processing list with status: {list_status}")
            
            for entry in list_item['entries']:
                media = entry['media']
                anilist_id = str(media['id'])
                
                # Get the title - prefer English, fallback to romaji
                title = media['title']['english'] if media['title']['english'] else media['title']['romaji']
                
                # Ultra normalize the title for comparison
                norm_title = normalize_title_for_comparison(title)
                
                # Check if manga already exists in backup using multiple methods
                is_duplicate = False
                
                # Method 1: Compare ultra-normalized title
                if norm_title in existing_manga_titles:
                    is_duplicate = True
                    
                # Method 2: Check for AniList ID
                if f"anilist:{anilist_id}" in existing_manga_urls:
                    is_duplicate = True
                
                # Method 3: Check for alternative titles (synonyms) with ultra-normalization
                for synonym in media.get('synonyms', []):
                    if synonym:
                        norm_synonym = normalize_title_for_comparison(synonym)
                        if norm_synonym in existing_manga_titles:
                            is_duplicate = True
                            break
                
                # Also check native and romaji titles if available
                for title_type in ['romaji', 'native']:
                    if media['title'].get(title_type):
                        alt_title = media['title'][title_type]
                        norm_alt_title = normalize_title_for_comparison(alt_title)
                        if norm_alt_title in existing_manga_titles:
                            is_duplicate = True
                            break
                
                if compare_backup and is_duplicate:
                    log(f"Skipping existing manga: {title} (ID: {anilist_id})")
                    skipped_items.append({
                        'title': title,
                        'id': anilist_id,
                        'status': list_status,
                        'reason': 'Already exists in backup'
                    })
                    continue
                
                manga_items.append(entry)
    
    log(f"Found {len(manga_items)} new manga entries after filtering")
    if skipped_items:
        log(f"Skipped {len(skipped_items)} manga entries already in backup")
    
    # Convert Anilist manga to Tachiyomi format
    new_manga_backup = convert_manga_to_tachiyomi_format(manga_items)
    
    # If we have an existing backup, add new manga to it
    if merged_backup:
        # Add all new manga from Anilist to the merged backup
        for manga in new_manga_backup.backupManga:
            merged_backup.backupManga.append(manga)
        
        log(f"Added {len(new_manga_backup.backupManga)} new manga to existing backup")
        final_backup = merged_backup
    else:
        # No existing backup, just use the new one
        final_backup = new_manga_backup
    
    # Write to file
    write_backup(final_backup, output_file)
    
    # Generate a report of skipped manga if needed
    if skipped_items and len(skipped_items) > 0:
    # Sort skipped items alphabetically by title
        skipped_items.sort(key=lambda x: x['title'].lower())
        
        report_file = f"{os.path.splitext(output_file)[0]}_skipped.md"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"# Skipped Manga Report\n\n")
            f.write(f"The following manga were skipped because they already exist in the comparison backup:\n\n")
            for item in skipped_items:
                f.write(f"- **{item['title']}** (Status: {item['status']})\n")
        log(f"Skipped manga report written to {report_file}")
    
    return output_file

# Updated read_backup function to handle both backup files and raw data
def read_backup(input_file):
    """Read a backup file and return its content.
    
    This function handles .tachibk and .proto.gz files (with gzip compression)
    as well as raw binary files.
    
    Args:
        input_file: Path to the backup file
        
    Returns:
        bytes: The raw backup data
    """
    log(f"Reading backup file: {input_file}")
    
    try:
        if input_file.lower().endswith('.tachibk') or input_file.lower().endswith('.proto.gz'):
            # Handle compressed backup files
            with gzip.open(input_file, 'rb') as zip_file:
                backup_data = zip_file.read()
                log(f"Read compressed backup: {len(backup_data)} bytes")
                return backup_data
        else:
            # Handle raw backup data files
            with open(input_file, 'rb') as file:
                backup_data = file.read()
                log(f"Read uncompressed backup: {len(backup_data)} bytes")
                return backup_data
    except Exception as e:
        log(f"Error reading backup file {input_file}: {e}", "error")
        raise

# Helper functions for JSON conversion
def dict_to_backup(backup_dict):
    """Convert a dictionary to a Backup object.
    
    Args:
        backup_dict: Dictionary representing a backup
        
    Returns:
        Backup: The converted Backup object
    """
    from schema_pb2 import Backup
    from google.protobuf.json_format import Parse
    
    try:
        # Convert the dictionary to a JSON string
        json_str = json.dumps(backup_dict)
        
        # Parse the JSON string into a Backup object
        backup = Backup()
        Parse(json_str, backup)
        
        return backup
    except Exception as e:
        log(f"Error converting dictionary to Backup: {e}", "error")
        raise

def main():
    # Set up fuzzy matching
    setup_fuzzy_matching()
    
    # Create argument parser with enhanced description and epilog
    parser = argparse.ArgumentParser(
        description='''
Tachiyomi Backup Tool - Create, manipulate, and manage backup files for Tachiyomi manga reader

This tool allows you to:
- Create Tachiyomi backup files from your Anilist manga list
- Find and remove duplicate manga entries in your backups
- Merge multiple backup files while handling duplicates
- Convert backup files to/from JSON for easy editing
- Compare backups to avoid adding duplicates
''',
        epilog='''
Examples:
  # Create backup from Anilist
  python tachiyomi_backup_tool.py anilist --anilist username
  
  # Create backup from private Anilist list
  python tachiyomi_backup_tool.py anilist --auth
  
  # Clean up duplicate entries in backup
  python tachiyomi_backup_tool.py cleanup --input backup.tachibk
  
  # Merge multiple backups
  python tachiyomi_backup_tool.py merge --input backup1.tachibk backup2.tachibk
  
For more detailed help on a specific command:
  python tachiyomi_backup_tool.py <command> --help
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Create subparsers for different operations
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Anilist command
    anilist_parser = subparsers.add_parser('anilist', 
        help='Create backup from Anilist manga list',
        description='Create a Tachiyomi backup file from your Anilist manga list. Can access both public and private lists.',
        epilog='''
Examples:
  # Create backup from public Anilist profile
  python tachiyomi_backup_tool.py anilist --anilist username
  
  # Create backup from private Anilist profile
  python tachiyomi_backup_tool.py anilist --auth
  
  # Only include CURRENT and COMPLETED manga
  python tachiyomi_backup_tool.py anilist --anilist username --lists CURRENT,COMPLETED
  
  # Export Anilist data to JSON for later use
  python tachiyomi_backup_tool.py anilist --anilist username --export-json anilist_data.json
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    anilist_parser.add_argument('--anilist', '-a', type=str, 
                          help='Anilist username (for public lists)')
    anilist_parser.add_argument('--auth', action='store_true', 
                          help='Use Anilist authentication for private lists (requires client ID and secret)')
    anilist_parser.add_argument('--config', type=str, default='anilistConfig.json', 
                          help='Path to Anilist configuration file (default: anilistConfig.json)')
    anilist_parser.add_argument('--output', '-o', type=str, default='tachiyomi_backup.tachibk', 
                          help='Output file path (default: tachiyomi_backup.tachibk)')
    anilist_parser.add_argument('--lists', '-l', type=str, default='all',
                          help='Comma-separated list of statuses to include (CURRENT,PLANNING,COMPLETED,DROPPED,PAUSED,REPEATING) or "all"')
    anilist_parser.add_argument('--compare', '-c', type=str, 
                          help='Path to existing backup file to compare against (skip existing manga)')
    anilist_parser.add_argument('--export-json', '-e', type=str,
                          help='Path to export Anilist manga details as JSON (useful for duplicate finding)')
    
    # Decode command
    decode_parser = subparsers.add_parser('decode', 
        help='Decode a backup file to JSON for viewing or editing',
        description='Convert a Tachiyomi backup file (.tachibk or .proto.gz) to JSON format for easy viewing and editing.',
        epilog='''
Examples:
  # Convert backup to JSON
  python tachiyomi_backup_tool.py decode --input my_backup.tachibk --output my_backup.json
  
  # Make preferences human-readable
  python tachiyomi_backup_tool.py decode --input my_backup.tachibk --convert-preferences
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    decode_parser.add_argument('--input', '-i', type=str, required=True, 
                          help='Input backup file (.tachibk or .proto.gz)')
    decode_parser.add_argument('--output', '-o', type=str, default='output.json', 
                          help='Output JSON file (default: output.json)')
    decode_parser.add_argument('--convert-preferences', action='store_true', 
                          help='Convert preferences to human-readable format')
    
    # Encode command
    encode_parser = subparsers.add_parser('encode', 
        help='Encode a JSON file to backup format',
        description='Convert a JSON file to Tachiyomi backup format (.tachibk or .proto.gz).',
        epilog='''
Example:
  # Convert edited JSON back to backup format
  python tachiyomi_backup_tool.py encode --input edited_backup.json --output new_backup.tachibk
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    encode_parser.add_argument('--input', '-i', type=str, required=True, 
                          help='Input JSON file')
    encode_parser.add_argument('--output', '-o', type=str, default='output.tachibk', 
                          help='Output backup file (default: output.tachibk)')
    
    # Merge command
    merge_parser = subparsers.add_parser('merge', 
        help='Merge multiple backup files into one',
        description='''
Combine multiple Tachiyomi backup files into a single file.

IMPORTANT NOTES:
- Settings (preferences, extensions) are taken from the LAST file in your input list
- Merge behavior for duplicate manga entries depends on the selected mode
- Order of input files matters! Use --mode to control how duplicates are handled
''',
        epilog='''
Examples:
  # Merge multiple backups, replacing duplicates
  python tachiyomi_backup_tool.py merge --input backup1.tachibk backup2.tachibk
  
  # Use the first backup as "master" (keep its entries for any duplicates)
  python tachiyomi_backup_tool.py merge --input master.tachibk other1.tachibk --mode keep_first
  
  # Use the last backup as "master" for both settings and manga entries
  python tachiyomi_backup_tool.py merge --input other1.tachibk master.tachibk --mode replace
  
  # Keep all entries even if duplicates exist
  python tachiyomi_backup_tool.py merge --input backup1.tachibk backup2.tachibk --mode keep_both
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    merge_parser.add_argument('--input', '-i', type=str, required=True, nargs='+', 
                         help='Input backup files (.tachibk, .proto.gz, or .json)')
    merge_parser.add_argument('--output', '-o', type=str, default='merged.tachibk', 
                         help='Output merged backup file (default: merged.tachibk)')
    merge_parser.add_argument('--mode', type=str, choices=['replace', 'keep_first', 'keep_both'], default='replace',
                         help='''
Merge mode for handling duplicates:
  replace: Replace entries with the same title (last file wins)
  keep_first: Keep the first entry if duplicate title is found
  keep_both: Keep both entries even if they have the same title
(default: replace)''')
    merge_parser.add_argument('--report', '-r', type=str, 
                         help='Generate a detailed report of the merge operations')

    # Cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', 
        help='Clean up a backup file by removing duplicates',
        description='''
Remove duplicate manga entries from a Tachiyomi backup file.

The tool identifies duplicates based on exact title matching and keeps either the first
or last occurrence of each manga title based on the selected mode.
''',
        epilog='''
Examples:
  # Clean up backup, keeping first occurrence of duplicates
  python tachiyomi_backup_tool.py cleanup --input backup.tachibk
  
  # Clean up backup, keeping last occurrence of duplicates
  python tachiyomi_backup_tool.py cleanup --input backup.tachibk --mode keep_last
  
  # Generate a report of removed duplicates
  python tachiyomi_backup_tool.py cleanup --input backup.tachibk --report cleanup_report.md
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    cleanup_parser.add_argument('--input', '-i', type=str, required=True, 
                        help='Input backup file (.tachibk, .proto.gz, or .json)')
    cleanup_parser.add_argument('--output', '-o', type=str, default='cleaned.tachibk', 
                        help='Output cleaned backup file (default: cleaned.tachibk)')
    cleanup_parser.add_argument('--mode', type=str, choices=['keep_first', 'keep_last'], default='keep_first',
                        help='''
Cleanup mode:
  keep_first: Keep the first occurrence of each manga title (default)
  keep_last: Keep the last occurrence of each manga title''')
    cleanup_parser.add_argument('--report', '-r', type=str, 
                        help='Generate a detailed report of the cleanup operations')
    
    # Schema command
    schema_parser = subparsers.add_parser('schema', 
        help='Generate protobuf schema for parsing backups',
        description='''
Generate the protobuf schema required for parsing Tachiyomi backup files.

This command creates the necessary .proto file based on the chosen Tachiyomi fork.
You need to have protoc (Protocol Buffers compiler) installed for this to work.
''',
        epilog='''
Examples:
  # Generate schema for mihon fork
  python tachiyomi_backup_tool.py schema
  
  # Generate schema for TachiyomiSY fork
  python tachiyomi_backup_tool.py schema --fork sy
  
  # Generate schemas for all supported forks
  python tachiyomi_backup_tool.py schema --dump-all
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    schema_parser.add_argument('--fork', type=str, default='mihon', choices=FORKS.keys(),
                          help=f'Tachiyomi fork schema to use (default: mihon)')
    schema_parser.add_argument('--dump-all', action='store_true', 
                          help='Generate schemas for all forks')
    
    # New find-duplicates command
    dupe_parser = subparsers.add_parser('find-duplicates', 
        help='Find potential duplicates in a backup file',
        description='''
Analyze a Tachiyomi backup file to find potential duplicate manga entries.

This command performs sophisticated duplicate detection using multiple methods:
- Title matching with normalization
- Fuzzy title matching for similar titles
- Alternative titles from AniList data
- URL and ID-based matching

IMPORTANT: This command only identifies potential duplicates and creates a report.
It doesn't modify your backup file. Use the 'cleanup' command to remove duplicates.
''',
        epilog='''
Example:
  # Find potential duplicates using Anilist data for enhanced matching
  python tachiyomi_backup_tool.py find-duplicates --backup my_backup.tachibk --anilist-json anilist_data.json
  
  # Then review the report before cleaning up:
  python tachiyomi_backup_tool.py cleanup --input my_backup.tachibk --output cleaned.tachibk
''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    dupe_parser.add_argument('--backup', '-b', type=str, required=True, 
                       help='Path to Tachiyomi backup file')
    dupe_parser.add_argument('--anilist-json', '-a', type=str, required=True,
                       help='Path to Anilist JSON data file (created with --export-json)')
    dupe_parser.add_argument('--output', '-o', type=str, default='duplicate_report.md',
                       help='Path to save the duplicate report (default: duplicate_report.md)')
    
    # Common arguments for all commands
    parser.add_argument('--fork', type=str, default='mihon', choices=FORKS.keys(),
                      help=f'Tachiyomi fork schema to use (default: mihon)')
    
    args = parser.parse_args()
    
    # Handle commands
    if args.command == 'anilist':
        # Create backup from Anilist
        # Ensure we have the protobuf module
        if not ensure_protobuf_module(args.fork):
            return
        
        # Handle authentication or public API
        user_id = None
        access_token = None
        
        if args.auth:
            # Use authentication
            use_oauth, client_id, client_secret, redirect_url = setup_anilist_config(args.config)
            
            if use_oauth:
                auth_code = request_anilist_auth_code(client_id, redirect_url)
                access_token = get_anilist_access_token(client_id, client_secret, redirect_url, auth_code)
                
                if access_token:
                    user_id = get_anilist_authenticated_user_id(access_token)
                    if not user_id:
                        log("Could not get authenticated user ID")
                        return
                else:
                    log("Authentication failed")
                    return
            else:
                log("OAuth configuration is incomplete or invalid")
                return
        elif args.anilist:
            # Use public API with username
            user_id = get_anilist_user_id(args.anilist)
            if not user_id:
                log("Could not find Anilist user. Please check the username.")
                return
        else:
            log("Please provide either --anilist <username> or --auth flag")
            return
        
        # Fetch manga list
        manga_data = get_anilist_manga_list(user_id, access_token)
        if not manga_data:
            log("Could not fetch manga list from Anilist.")
            return
        
        # Export Anilist data to JSON if requested
        if args.export_json:
            export_anilist_manga_data(manga_data, args.export_json, args.lists)
            log(f"Anilist manga data exported to {args.export_json}")
        
        # Create backup with status filtering and comparison
        log(f"Creating Tachiyomi backup for user ID: {user_id} with status filter: {args.lists}")
        if args.compare:
            backup_file = create_tachiyomi_backup_with_compare(manga_data, args.output, args.lists, args.compare)
        else:
            backup_file = create_tachiyomi_backup(manga_data, args.output, args.lists)
        
        print(f"\nSuccess! Tachiyomi backup created at: {backup_file}")
        print(f"You can now import this file into your Tachiyomi/Mihon app.")
        
    elif args.command == 'decode':
        # Decode backup file to JSON
        if not ensure_protobuf_module(args.fork):
            return
        
        try:
            backup_data = read_backup(args.input)
            backup = parse_backup(backup_data)
            write_json(backup, args.output, args.convert_preferences)
            print(f"Backup successfully decoded to {args.output}")
        except Exception as e:
            log(f"Error decoding backup: {e}")
            
    elif args.command == 'encode':
        # Encode JSON to backup file
        if not ensure_protobuf_module(args.fork):
            return
        
        try:
            # Read JSON file
            with open(args.input, 'r', encoding='utf-8') as file:
                backup_dict = json.load(file)
            
            # Convert to Backup object
            backup = dict_to_backup(backup_dict)
            
            # Write backup file
            write_backup(backup, args.output)
            print(f"JSON successfully encoded to {args.output}")
        except Exception as e:
            log(f"Error encoding JSON: {e}")
            
    elif args.command == 'merge':
        # Merge multiple backup files
        if not ensure_protobuf_module(args.fork):
            return
        
        # Default report file name if not specified
        report_file = args.report
        if not report_file and args.output:
            # Generate report file name based on output file
            base_name = os.path.splitext(args.output)[0]
            report_file = f"{base_name}_merge_report.md"
        
        if merge_backups(args.input, args.output, args.mode, report_file):
            print(f"Backup files successfully merged to {args.output}")
            if report_file:
                print(f"Merge report generated at {report_file}")
        else:
            log("Failed to merge backup files")

    elif args.command == 'cleanup':
        # Clean up a backup file
        if not ensure_protobuf_module(args.fork):
            return
        
        # Default report file name if not specified
        report_file = args.report
        if not report_file and args.output:
            # Generate report file name based on output file
            base_name = os.path.splitext(args.output)[0]
            report_file = f"{base_name}_cleanup_report.md"
        
        if cleanup_backup(args.input, args.output, args.mode, report_file):
            print(f"Backup file successfully cleaned up and saved to {args.output}")
            if report_file:
                print(f"Cleanup report generated at {report_file}")
        else:
            log("Failed to clean up backup file")
            
    elif args.command == 'schema':
        # Generate protobuf schema
        if args.dump_all:
            log("Generating schemas for all forks")
            for fork in FORKS:
                generate_protobuf_schema(fork, f'schema-{fork}.proto')
        else:
            generate_protobuf_schema(args.fork, f'schema-{args.fork}.proto')
            log(f"Schema generated for {args.fork}")
    
    elif args.command == 'find-duplicates':
        log("Finding potential duplicates")
        # Ensure we have the protobuf module
        if not ensure_protobuf_module(args.fork):
            return
        
        if find_potential_duplicates(args.backup, args.anilist_json, args.output):
            print(f"\nSuccess! Duplicate analysis report created at: {args.output}")
        else:
            print("\nFailed to analyze duplicates. Check logs for details.")
    
    else:
        # No command specified, print help
        parser.print_help()

if __name__ == "__main__":
    main()
