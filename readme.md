# GPS Location Analyzer (UAPP3)

A comprehensive, modern web-based tool for analyzing Google Location History data with real-time interface and detailed travel analytics. This multi-user application processes Google Location History JSON files to generate insights about travel patterns, time spent in locations, and movement analysis. Could be useful if you wanted to know how much time you spent in each state for tax reporting for example.

## 🌟 Key Features

- **Mobile Location Data Optimized**: Specifically designed for Google's mobile location-history.json export
- **Multi-User Web Interface**: Support for multiple users with individual file management
- **Smart Header System**: Parsed files include embedded metadata with date ranges and compression settings
- **Real-Time Progress Tracking**: Live feedback during file processing with detailed status updates
- **Intelligent Data Processing**: Handles both raw mobile exports and pre-processed JSON files with headers
- **Advanced Location Analytics**: City & country detection, time tracking, movement analysis
- **Smart Caching System**: Geoapify API results cached locally for performance and cost optimization
- **Multiple Export Formats**: CSV files and detailed summary reports
- **File Management System**: Upload, process, and manage location files per user with metadata tracking
- **Configurable Noise Filtering**: GPS accuracy filtering with settings stored in file headers

## 📁 Project Structure

```
UAPP3/
├── unified_app.py          # Main Flask application
├── config/                 # Configuration files
│   └── web_config.json    # API keys and settings
├── templates/              # HTML templates
├── static/                 # CSS, JS, and assets
├── uploads/                # User-uploaded files (per user directories)
├── processed/              # Processed output files (per user directories)
├── outputs/                # Generated analysis reports
└── documents/              # Documentation and manuals
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Geoapify API key (free at [geoapify.com](https://geoapify.com))
- Google Location History data from the NEW mobile exporter (not Google Takeout)

### Installation

1. **Clone or download the project**:
   ```bash
   cd UAPP3
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API access**:
   Create `config/web_config.json`:
   ```json
   {
     "geoapify_key": "your_api_key_here",
     "last_start_date": "2024-01-01",
     "last_end_date": "2024-12-31"
   }
   ```

4. **Run the application**:
   ```bash
   python unified_app.py
   ```

5. **Open your browser**: Navigate to `http://localhost:5000`

## 📊 Data Processing Workflow

### Input Data Requirements

**CRITICAL**: This application requires location data from Google's **NEW mobile exporter**, not Google Takeout. The mobile export provides cleaner, more structured data.

### Supported File Types

1. **Raw Google JSON**: Direct export from Google mobile app
2. **Pre-processed JSON**: Files cleaned by companion preprocessing tools
3. **Master Files**: Large, unparsed location history files

### Processing Pipeline

1. **File Upload**: Users upload location history files via web interface
2. **Data Validation**: System validates file format and structure
3. **Intelligent Processing**: 
   - Detects if file needs preprocessing
   - Applies noise filtering for GPS accuracy
   - Performs geocoding with smart caching
4. **Analysis Generation**:
   - Time spent by location analysis
   - Movement pattern detection
   - Distance calculations
   - City and country identification
5. **Export Generation**: Multiple output formats for different use cases

## 🗂️ File Management System

### User File Organization

Each user gets dedicated directories:
- `uploads/[username]/` - Original uploaded files
- `processed/[username]/` - Cleaned and processed files
- `outputs/[username]/` - Generated analysis reports

### Master File Handling

- **Storage**: Master files (large unparsed files) are stored on disk
- **Naming Convention**: `MASTER_xxxx.json` for easy identification
- **Cache Management**: Browser cache used for active sessions only
- **Disk vs Cache**: Processed files available in both locations for optimal performance

## 📈 Analysis Outputs

### Generated Reports

1. **city_jumps.csv**: Movement between cities with distances and timing
2. **by_city_location_days.csv**: Time spent in each city with detailed breakdown
3. **by_state_location_days.csv**: Time spent by state/country
4. **analysis_summary.txt**: Executive summary with key insights and top destinations

### Real-Time Analytics

- **Progress Indicators**: Live updates during processing
- **Processing Statistics**: Data points processed, cache hit rates
- **Error Reporting**: Detailed feedback on any processing issues

## ⚙️ Configuration Options

### User Settings

- **Date Range Selection**: Analyze specific time periods
- **Processing Preferences**: Choose between speed and accuracy
- **Output Formats**: Select desired export formats
- **API Usage Limits**: Configure geocoding API usage

### Advanced Configuration

- **Cache Management**: Control cache size and retention
- **Batch Processing**: Configure processing batch sizes
- **Error Handling**: Set retry limits and timeout values

## 🔧 Technical Details

### Tech Stack

- **Backend**: Python 3.8+ with Flask web framework
- **Frontend**: Modern responsive web interface with real-time updates
- **APIs**: Geoapify for geocoding services with intelligent caching
- **Data Processing**: Async processing for large datasets with noise filtering
- **Storage**: Local file system with organized user directories

### Performance Optimizations

- **Intelligent Caching**: Geoapify API results cached to avoid duplicate calls
- **Async Processing**: Non-blocking operations for better user experience
- **Memory Management**: Efficient handling of large location datasets
- **Progressive Loading**: Files processed in chunks for memory efficiency

### Privacy & Security

- **Local Processing**: All data processed locally on your machine
- **No Data Transmission**: Location data never leaves your system (except for geocoding)
- **API Key Security**: Keys stored in local configuration files
- **User Isolation**: Each user's data kept completely separate

## 🐛 Known Issues & Solutions

### Current Issues (September 2025)

1. **File Size Discrepancy**: 
   - **Issue**: Master file shows different sizes in browser cache (36.5MB) vs disk (52.9MB)
   - **Status**: Under investigation
   - **Workaround**: Use disk-based files for accurate size reporting

2. **JavaScript Control Popup**:
   - **Issue**: Unwanted "Saved Location Data" popup appears sporadically after analysis
   - **Status**: Debugging in progress
   - **Action Needed**: Identify trigger and remove control

3. **Remove Button Functionality**:
   - **Issue**: 'Remove' button in Master File box is non-functional
   - **Expected**: Should delete the master file
   - **Status**: Requires implementation

4. **File Management Logic**:
   - **Issue**: Inconsistency between disk storage and browser cache file display
   - **Proposed Solution**: Implement unified file management system with disk-first approach

### Troubleshooting Guide

#### API Issues
- **Symptom**: Geocoding failures
- **Solution**: Verify Geoapify API key in `config/web_config.json`
- **Check**: API quota and rate limits

#### Data Source Problems
- **Symptom**: Processing errors or poor results
- **Solution**: Ensure using NEW mobile exporter data, not Google Takeout
- **Verify**: JSON structure matches expected format

#### Performance Issues
- **Symptom**: Slow processing or timeouts
- **Solution**: Check cache utilization and API response times
- **Monitor**: Progress tracking for bottleneck identification

#### File Management Issues
- **Symptom**: Files not appearing or incorrect sizes
- **Solution**: Check file permissions and disk space
- **Verify**: User directory structure is correct

## 🛠️ Development & Maintenance

### Adding New Features

1. **Analysis Modules**: Extend processing capabilities in main application
2. **Web Interface**: Update templates and static files for new functionality
3. **Progress Tracking**: Ensure new features include real-time feedback
4. **File Management**: Consider impact on user file organization

### Code Style Guidelines

- Follow PEP 8 for Python code
- Use async/await for API operations
- Implement comprehensive error handling
- Add detailed logging for debugging
- Document complex analysis functions

### Testing Approach

- Test with various dataset sizes
- Verify API integrations work correctly
- Check file upload and processing workflows
- Validate output file generation and formats

## 📞 Support & Troubleshooting

### Getting Help

1. **Check this README** for common issues and solutions
2. **Review log files** in the application directory
3. **Verify configuration** settings and API keys
4. **Test with small datasets** before processing large files

### Reporting Issues

When reporting problems, include:
- Error messages or unexpected behavior
- File sizes and types being processed
- Browser and operating system information
- Steps to reproduce the issue

## 🔄 Future Enhancements

### Planned Improvements

1. **Enhanced File Management**: Unified disk-based file system
2. **Advanced Analytics**: Machine learning for pattern recognition
3. **Export Options**: Additional output formats (KML, GPX)
4. **User Interface**: Improved progress tracking and error handling
5. **API Integrations**: Additional geocoding service options
6. **Performance**: Further optimization for large datasets

### Contribution Guidelines

- Follow existing code structure and patterns
- Test with various location dataset sizes
- Maintain user privacy and security focus
- Document any new API integrations
- Ensure multi-user compatibility

---

*This application processes Google Location History data locally with a focus on privacy, performance, and detailed travel analytics while supporting multiple users in a web-based environment.*