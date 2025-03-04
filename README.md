# AniHonYomi Backup Tool

Anilist importer for Tachiyomi, Suwayomi, and Mihon including backup merger, cleanup, and duplicate finder.

## Features

- Create Tachiyomi backup files from Anilist manga lists
- Convert backup files to/from JSON for easy editing
- Find and remove duplicate manga entries
- Merge multiple backup files
- Compare backups to avoid adding duplicates
- Generate detailed reports for all operations
- Support for different Tachiyomi forks (mihon, sy, j2k, yokai)

## Installation

### Prerequisites

- Python 3.6+
- Required Python packages:
  - gzip
  - varint
  - requests
  - fuzzywuzzy (recommended for better duplicate detection)
  - google-protobuf

Install the required packages:

```cmd
pip install requests varint google-protobuf fuzzywuzzy
```

You'll also need the Protocol Buffers compiler (protoc) to generate the schema:
- Download from: https://github.com/protocolbuffers/protobuf/releases/latest

## Usage

The script provides several commands for different operations:

```cmd
python AniHonYomi.py <command> [options]
```

### Global Options

- `--fork`: Tachiyomi fork schema to use (default: mihon)
  - Available options: mihon, sy, j2k, yokai

## Commands

### 1. anilist - Create backup from Anilist

Creates a Tachiyomi backup file using data from your Anilist manga list.

```cmd
python AniHonYomi.py anilist [options]
```

**Options:**
- `--anilist`, `-a`: Anilist username (for public lists)
- `--auth`: Use Anilist authentication (for private lists)
- `--config`: Path to Anilist configuration file (default: anilistConfig.json)
- `--output`, `-o`: Output file path (default: tachiyomi_backup.tachibk)
- `--lists`, `-l`: Comma-separated list of statuses to include (default: all)
  - Available statuses: CURRENT, PLANNING, COMPLETED, DROPPED, PAUSED, REPEATING
- `--compare`, `-c`: Path to existing backup file to compare against (skip existing manga)
- `--export-json`, `-e`: Path to export Anilist manga details as JSON

**Anilist authenication (for private lists)**

Go to Anilist [**Settings** -> **Developer**](https://anilist.co/settings/developer), and click **Create client**.
  - Type whatever in **Name** field, and use ``https://anilist.co/api/v2/oauth/pin`` as **Redirect URL**.
  - Get information from created client and input them in **anilistConfig.json** inside the script root folder.
  - File must contain these lines. *Replace lines with appropriate values*:
```json
{
    "aniclient": "ID",
    "anisecret": "Secret",
    "redirectUrl": "https://anilist.co/api/v2/oauth/pin"
}
```

**Examples:**
```cmd
# Create backup from public Anilist profile
python AniHonYomi.py anilist --anilist username --output my_backup.tachibk

# Create backup from private Anilist profile
python AniHonYomi.py anilist --auth --output my_backup.tachibk

# Only include CURRENT and COMPLETED manga
python AniHonYomi.py anilist --anilist username --lists CURRENT,COMPLETED

# Create backup avoiding duplicates from existing backup
python AniHonYomi.py anilist --anilist username --compare existing_backup.tachibk
```

### 2. decode - Convert backup to JSON

Decodes a Tachiyomi backup file to JSON format for easy inspection or editing.

```cmd
python AniHonYomi.py decode [options]
```

**Options:**
- `--input`, `-i`: Input backup file (.tachibk or .proto.gz) [required]
- `--output`, `-o`: Output JSON file (default: output.json)
- `--convert-preferences`: Convert preferences to human-readable format

**Example:**
```cmd
python AniHonYomi.py decode --input my_backup.tachibk --output decoded.json
```

### 3. encode - Convert JSON to backup

Encodes a JSON file back to Tachiyomi backup format.

```cmd
python AniHonYomi.py encode [options]
```

**Options:**
- `--input`, `-i`: Input JSON file [required]
- `--output`, `-o`: Output backup file (default: output.tachibk)

**Example:**
```cmd
python AniHonYomi.py encode --input edited.json --output new_backup.tachibk
```

### 4. merge - Merge multiple backups

Combines multiple Tachiyomi backup files into a single file. The last file being merged takes priority in user settings merging.

```cmd
python AniHonYomi.py merge [options]
```

**Options:**
- `--input`, `-i`: Input backup files (.tachibk, .proto.gz, or .json) [required, can specify multiple]
- `--output`, `-o`: Output merged backup file (default: merged.tachibk)
- `--mode`: Merge mode for handling duplicates (default: replace)
  - `replace`: Replace entries with the same title
  - `keep_first`: Keep the first entry if duplicate title is found
  - `keep_both`: Keep both entries even if they have the same title
- `--report`, `-r`: Generate a detailed report of the merge operations

**Examples:**
```cmd
# Merge multiple backups, replacing duplicates
python AniHonYomi.py merge --input backup1.tachibk backup2.tachibk --output merged.tachibk

# Merge using master backup (prioritize entries from master.tachibk)
python AniHonYomi.py merge --input master.tachibk other1.tachibk --mode keep_first

# Merge keeping all entries (even duplicates)
python AniHonYomi.py merge --input backup1.tachibk backup2.tachibk --mode keep_both --report merge_report.md
```

### 5. cleanup - Remove duplicate manga entries

Cleans up a backup file by removing duplicate manga entries.

```cmd
python AniHonYomi.py cleanup [options]
```

**Options:**
- `--input`, `-i`: Input backup file (.tachibk, .proto.gz, or .json) [required]
- `--output`, `-o`: Output cleaned backup file (default: cleaned.tachibk)
- `--mode`: Cleanup mode (default: keep_first)
  - `keep_first`: Keep the first occurrence of each manga title
  - `keep_last`: Keep the last occurrence of each manga title
- `--report`, `-r`: Generate a detailed report of the cleanup operations

**Examples:**
```cmd
# Clean up backup, keeping first occurrence of duplicates
python AniHonYomi.py cleanup --input backup.tachibk --output cleaned.tachibk

# Clean up backup, keeping last occurrence of duplicates with report
python AniHonYomi.py cleanup --input backup.tachibk --mode keep_last --report cleanup_report.md
```

### 6. find-duplicates - Find potential duplicate manga

Analyzes a backup file to find potential duplicate manga entries using sophisticated matching.

```cmd
python AniHonYomi.py find-duplicates [options]
```

**Options:**
- `--backup`, `-b`: Path to Tachiyomi backup file [required]
- `--anilist-json`, `-a`: Path to Anilist JSON data file (created with --export-json) [required]
- `--output`, `-o`: Path to save the duplicate report (default: duplicate_report.md)

**Example:**
```cmd
python AniHonYomi.py find-duplicates --backup my_backup.tachibk --anilist-json anilist_data.json
```

### 7. schema - Generate protobuf schema

Generates the protobuf schema required for parsing Tachiyomi backup files.

```cmd
python AniHonYomi.py schema [options]
```

**Options:**
- `--fork`: Tachiyomi fork schema to use (default: mihon)
- `--dump-all`: Generate schemas for all forks

**Examples:**
```cmd
# Generate schema for mihon fork
python AniHonYomi.py schema

# Generate schemas for all supported forks
python AniHonYomi.py schema --dump-all
```

## Workflow Examples

### Complete Anilist to Tachiyomi Workflow

1. Export Anilist data to JSON:
```cmd
python AniHonYomi.py anilist --anilist username --export-json anilist_data.json
```

2. Find duplicates in an existing backup:
```cmd
python AniHonYomi.py find-duplicates --backup existing.tachibk --anilist-json anilist_data.json
```

3. Create a new backup from Anilist avoiding duplicates:
```cmd
python AniHonYomi.py anilist --anilist username --compare existing.tachibk --output new_from_anilist.tachibk
```

4. Merge with existing backup:
```cmd
python AniHonYomi.py merge --input existing.tachibk new_from_anilist.tachibk --output merged.tachibk --report merge_report.md
```

### Clean and Combine Multiple Backups

1. Clean up individual backups:
```cmd
python AniHonYomi.py cleanup --input backup1.tachibk --output clean1.tachibk
python AniHonYomi.py cleanup --input backup2.tachibk --output clean2.tachibk
```

2. Merge cleaned backups:
```cmd
python AniHonYomi.py merge --input clean1.tachibk clean2.tachibk --output final.tachibk --mode replace
```

## Notes on Duplicate Detection

- The `cleanup` command identifies duplicates based on exact title matching
- The `find-duplicates` command uses more sophisticated methods including:
  - Fuzzy title matching
  - Alternative titles matching
  - URL and ID-based matching
- For best results with duplicate detection, first export your Anilist data using `--export-json`

## Common Issues

- **Schema Generation Errors**: Make sure you have protoc installed and in your PATH
- **Anilist Authentication Issues**: Ensure you have created a Developer API client on Anilist website
- **Duplicate Detection False Positives**: Use the `find-duplicates` command before cleanup to review potential duplicates
- **Manga Not Transferred Correctly**: Check duplicate detection settings and compare manga lists manually if needed

## License

This tool is provided as-is under the GPL-3.0 license for personal use and is not affiliated with Anilist, Tachiyomi, Mihon, Suwayomi or any other related projects/forks.

**AI Disclaimer:** Parts of this was made with various AI tools to speed development time.