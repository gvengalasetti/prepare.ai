// Background script for handling API communication and storage
chrome.runtime.onInstalled.addListener(() => {
    console.log('Calendar Meeting Assistant installed');
});

// Handle messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'getMeetings') {
        // This could be used for additional background processing
        sendResponse({ success: true });
    }
    
    if (request.action === 'storeApiData') {
        // Store meeting data for offline access
        chrome.storage.local.set({ meetingData: request.data }, () => {
            sendResponse({ success: true });
        });
        return true; // Keep message channel open for async response
    }
    
    if (request.action === 'getStoredData') {
        // Retrieve stored meeting data
        chrome.storage.local.get(['meetingData'], (result) => {
            sendResponse({ data: result.meetingData });
        });
        return true; // Keep message channel open for async response
    }
});
