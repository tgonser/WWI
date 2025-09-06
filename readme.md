# Unified Location Data Processor

A web-based tool for parsing and analyzing Google location history data with geocoding capabilities.

## What This Does

- **Parse** raw Google location history JSON files into manageable date ranges
- **Geocode** location coordinates into readable addresses (cities, states, countries)
- **Analyze** movement patterns, visits, and travel distances
- **Export** results as CSV files and interactive HTML reports
- **Store** processed data locally for quick access

## Setup Requirements

### Required Files
Copy these files from your existing LAweb application:
- `modern_analyzer_bridge.py`
- `geo_utils.py` 
- `csv_exporter.py`
- `location_analyzer.py`
- `legacy_analyzer.py`

### Python Dependencies
```bash
pip install flask pandas requests werkzeug
```

### API Keys Required
- **Geoapify API key** (for geocoding) - Get from https://geoapify.com
- **Google Geocoding API key** (optional backup) - Get from Google Cloud Console

## How to Run

1. Start the server:
   ```bash
   python unified_app.py
   ```

2. Open browser to: `http://localhost:5000`

3. Create an account (first time only)

4. Upload your Google location history JSON file

## User Workflow

### Step 1: Upload Master File
- Upload your raw `location-history.json` from Google Takeout
- This becomes your "master file" for creating date ranges

### Step 2: Parse Date Ranges  
- Select date range to parse (e.g., "2024-01-01" to "2024-12-31")
- Set filtering thresholds:
  - **Distance**: Minimum meters between points (default: 200m)
  - **Duration**: Minimum seconds at a location (default: 600s) 
  - **Probability**: Minimum confidence for visits (default: 0.1)

### Step 3: Analyze Parsed Data
- Add your API keys in settings
- Choose analysis date range
- System geocodes coordinates and generates reports

### Step 4: View Results
- Download CSV files (by city, by state, travel logs)
- View interactive HTML reports
- Export all results as ZIP file

## File Management

The application creates separate folders per user:
- `uploads/[username]/` - Master files
- `processed/[username]/` - Parsed date ranges  
- `outputs/[username]/` - Analysis results

## Security Notes

- Each user has isolated data storage
- API keys are stored per-user account
- No data sharing between users
- Local browser storage for quick file access

## Troubleshooting

### Missing Modules Error
If you see "Could not import analyzer modules", copy the required files from your LAweb application.

### Geocoding Failures  
- Check API key validity in user settings
- Verify API key has geocoding permissions
- Check API usage limits

### Large File Processing
- Files over 100MB may take several minutes to parse
- Monitor progress in the processing screen
- Browser may appear unresponsive during large file uploads

## Technical Details

- **Backend**: Python Flask server
- **Frontend**: HTML/JavaScript with browser storage
- **Data Format**: JSON with metadata for tracking
- **Geocoding**: Cached results to minimize API calls
- **Storage**: User-specific folders + browser IndexedDB

## Output Files

### CSV Reports
- `by_city_location_days.csv` - Days spent in each city
- `by_state_location_days.csv` - Days spent in each state  
- `city_jumps.csv` - Travel between cities with distances

### HTML Reports
- Interactive sortable tables
- Search functionality
- Export capabilities
- Print-friendly formatting

## Configuration

Settings are stored per-user and include:
- API keys (Geoapify, Google)
- Default filter thresholds
- Last used date ranges
- Geocoding cache (per user)

---

For technical support or questions about the location data format, refer to Google Takeout documentation.