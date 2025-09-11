// Simplified file management - replaces complex browser storage
// Uses only disk-based operations via existing Flask routes

// Simple file management functions
async function showAllSavedData() {
    const modal = document.getElementById('dataManagerModal');
    if (modal) {
        modal.style.display = 'block';
        
        // Default to files tab
        switchTab('originals');
        
        // Load files using the server route that gets both master and parsed files
        await loadServerFiles();
    }
}



async function loadServerFiles() {
    console.log('=== loadServerFiles called ===');
    
    try {
        console.log('Fetching /list_all_user_files...');
        const response = await fetch('/list_all_user_files');
        console.log('Response status:', response.status);
        
        const data = await response.json();
        console.log('Server response data:', data);
        
        console.log('Calling displayAllUserFiles with data...');
        displayAllUserFiles(data);
        console.log('displayAllUserFiles completed');

       
    } catch (error) {
        console.error('Error in loadServerFiles:', error);
        document.getElementById('originalFilesList').innerHTML = 
            '<p style="text-align: center; color: #999;">Error loading files</p>';
    }
}

function displayAllUserFiles(data) {
    const listDiv = document.getElementById('originalFilesList');
    if (!listDiv) return;
    
    // FORCE remove any existing styles that cause scroll issues
    listDiv.style.maxHeight = 'none';
    listDiv.style.overflow = 'visible';
    listDiv.className = '';
    
    // Also fix parent modal container
    const modalBody = listDiv.closest('.modal-body');
    if (modalBody) {
        modalBody.style.maxHeight = 'none';
        modalBody.style.overflow = 'visible';
    }
    
    const totalFiles = (data.master_files?.length || 0) + (data.parsed_files?.length || 0);
    
    if (totalFiles === 0) {
        listDiv.innerHTML = `
            <div style="text-align: center; color: #666; padding: 40px;">
                <h4>No files yet</h4>
                <p>Upload a Google location file to get started.</p>
            </div>
        `;
        return;
    }
    
    let html = `<div style="background: #f8f9fa; padding: 15px; margin-bottom: 20px; border-radius: 8px;">
                    <h4 style="margin: 0; color: #000;">Your Location Files</h4>
                </div>`;
    // ADD THIS SECTION HERE:
    html += `<h4 style="color: #dc3545; margin: 20px 0 10px 0;">Master Files</h4>`;

    if (data.master_files && data.master_files.length > 0) {
    // ADD THE MASTER FILE DISPLAY CODE HERE (from the duplicate section you deleted)
    const latestMaster = data.master_files.sort((a, b) => 
        new Date(b.modified) - new Date(a.modified))[0];
    
    html += `
        <div style="background: #f8f9fa; border: 2px solid #dc3545; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; margin-bottom: 10px;">
                <h4 style="margin: 0; color: #dc3545;">Master File Loaded: ${latestMaster.filename}</h4>
                <button onclick="parseFromMaster('${latestMaster.filename}')" style="margin-left: auto; padding: 5px 10px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">Parse New Range</button>
                <button onclick="replaceMasterFile()" style="margin-left: 10px; padding: 5px 10px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">Replace</button>
            </div>
            <div style="color: #666; font-size: 14px;">
                Size: ${latestMaster.size_mb} MB | Modified: ${latestMaster.modified}
            </div>
        </div>
    `;
} else {
    // Only ONE else block
    html += `
        <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin-bottom: 20px; border-radius: 8px; color: #856404;">
            <h5 style="margin: 0 0 10px 0;">No Master File Loaded</h5>
            <p style="margin: 0 0 10px 0;">Upload a raw Google location-history.json file to get started.</p>
            <button onclick="document.getElementById('raw-file').click()" style="padding: 8px 16px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">
                Upload Master File
            </button>
        </div>
    `;
}

    // PARSED FILES SECTION - ONE scroll area with buttons OUTSIDE
    if (data.parsed_files && data.parsed_files.length > 0) {
        html += `<h4 style="color: #28a745; margin: 20px 0 10px 0;">Parsed Files (${data.parsed_files.length})</h4>`;
        
        // Start container for table + buttons
        html += `<div style="border: 1px solid #dee2e6; border-radius: 8px;">`;
        
        // SCROLLABLE table area only
        html += `
            <div style="max-height: 250px; overflow-y: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="background: #f8f9fa; position: sticky; top: 0;">
                        <tr>
                            <th style="padding: 8px; text-align: left; border-bottom: 1px solid #dee2e6;">Select</th>
                            <th style="padding: 8px; text-align: left; border-bottom: 1px solid #dee2e6;">Name</th>
                            <th style="padding: 8px; text-align: left; border-bottom: 1px solid #dee2e6;">Size</th>
                            <th style="padding: 8px; text-align: left; border-bottom: 1px solid #dee2e6;">Modified</th>
                        </tr>
                    </thead>
                    <tbody>`;
        
        data.parsed_files.forEach(file => {
            html += `
                <tr>
                    <td style="padding: 8px; text-align: center;">
                        <input type="checkbox" value="${file.filename}" class="parsed-file-checkbox">
                    </td>
                    <td style="padding: 8px;">${file.filename.replace('parsed_', '').replace('.json', '')}</td>
                    <td style="padding: 8px;">${file.size_mb} MB</td>
                    <td style="padding: 8px;">${file.modified.split(' ')[0]}</td>
                </tr>`;
        });
        
        // Close table and scrollable area
        html += `
                    </tbody>
                </table>
            </div>`;
        
        // FIXED BUTTONS - outside scroll area but inside container
        html += `
            <div style="background: #f8f9fa; padding: 15px; border-top: 1px solid #dee2e6; display: flex; gap: 15px;">
                <button onclick="analyzeSelectedFile()" style="padding: 8px 16px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                    Analyze
                </button>
                <button onclick="deleteSelectedFiles()" style="padding: 8px 16px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                    Delete
                </button>
            </div>`;
        
        // Close container
        html += `</div>`;
    }
    
    listDiv.innerHTML = html;
}

// Add the missing helper functions:
async function analyzeSelectedFile() {
    const checkboxes = document.querySelectorAll('.parsed-file-checkbox:checked');
    if (checkboxes.length !== 1) {
        alert('Please select exactly one parsed file to analyze');
        return;
    }
    
    const filename = checkboxes[0].value;
    
    // Close the modal FIRST
    closeDataManager();
    
    // Then analyze the file
    await analyzeExistingFile(filename);
}

async function deleteSelectedFiles() {
    const checkboxes = document.querySelectorAll('.parsed-file-checkbox:checked');
    if (checkboxes.length === 0) {
        alert('Please select files to delete');
        return;
    }
    
    const filenames = Array.from(checkboxes).map(cb => cb.value);
    
    if (!confirm(`Delete ${filenames.length} selected file(s)? This cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch('/delete_files', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filenames: filenames,
                type: 'processed'
            })
        });
        
        const result = await response.json();
        
        if (result.error) {
            alert(`Error: ${result.error}`);
            return;
        }
        
        alert(`Deleted ${result.deleted_files.length} file(s)`);
        await loadServerFiles(); // Refresh the list
        
    } catch (error) {
        console.error('Error deleting files:', error);
        alert('Error deleting files');
    }
}

function replaceMasterFile() {
    // Close the modal first
    closeDataManager();
    
    // Wait a moment for DOM to update, then trigger file input
    setTimeout(() => {
        const fileInput = document.getElementById('raw-file');
        if (fileInput) {
            fileInput.click();
        } else {
            alert('File upload not available - please use the main upload area');
        }
    }, 100);
}

async function cleanupOldMasters() {
    if (!confirm('This will delete all master files except the most recent one. Continue?')) {
        return;
    }
    
    try {
        const response = await fetch('/cleanup_old_masters', { method: 'POST' });
        const result = await response.json();
        
        if (result.error) {
            alert(`Error: ${result.error}`);
            return;
        }
        
        alert(result.message);
        await loadServerFiles(); // Refresh
        
    } catch (error) {
        console.error('Error cleaning up files:', error);
        alert('Error cleaning up files');
    }
}

async function parseFromMaster(filename) {
    try {
        // Use the existing endpoint
        const response = await fetch(`/load_master_for_parsing/${encodeURIComponent(filename)}`);
        const result = await response.json();
        
        if (result.error) {
            alert(`Error: ${result.error}`);
            return;
        }
        
        // Close modal
        closeDataManager();
        
        // Update UI to show file is loaded
        const fileInfo = document.getElementById('file-info');
        if (fileInfo) {
            fileInfo.textContent = `Master loaded: ${filename} (${result.size_mb} MB)`;
            fileInfo.style.color = '#28a745';
        }
        
        // Store that we have a master ready
        window.reparsingMaster = filename;
        
        // Move to parse step
        if (typeof moveToStep === 'function') {
            moveToStep(1);
        }
        
        showNotification('Master file loaded. Set your date range and thresholds, then click Parse.', 'success');
        
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error loading master file', 'error');
    }
}

// Helper functions
function closeDataManager() {
    const modal = document.getElementById('dataManagerModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.style.display = 'none';
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(tabName + 'Tab');
    if (selectedTab) {
        selectedTab.style.display = 'block';
    }
    
    // Add active class to corresponding button
    const buttons = document.querySelectorAll('.tab-btn');
    if (tabName === 'originals' && buttons[1]) {
        buttons[1].classList.add('active');
    }
}

function showNotification(message, type = 'success') {
    // Use existing notification system if available
    if (typeof showStatus === 'function') {
        showStatus(message, type);
    } else {
        // Simple fallback notification
        alert(message);
    }
}

// Make functions globally available
// window.showAllSavedData = showAllSavedData;
window.loadServerFiles = loadServerFiles;
window.analyzeSelectedFile = analyzeSelectedFile;
window.deleteSelectedFiles = deleteSelectedFiles;
window.parseFromMaster = parseFromMaster;
window.replaceMasterFile = replaceMasterFile;
window.closeDataManager = closeDataManager;
window.switchTab = switchTab;