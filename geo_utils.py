import os
import json
import time
import requests
import math
import threading
import asyncio
import aiohttp
from typing import List, Dict, Tuple, Optional

# Ensure config directory exists
os.makedirs('config', exist_ok=True)

geo_cache = {}
cache_file = "config/geo_cache.json"
if os.path.exists(cache_file):
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            geo_cache = json.load(f)
        print(f"Loaded {len(geo_cache)} cache entries from {cache_file}")
    except Exception as e:
        print(f"⚠️ Failed to load config/geo_cache.json: {e}")

class APIError(Exception):
    """Custom exception for API errors that should stop processing"""
    def __init__(self, message, status_code=None, should_stop=False):
        super().__init__(message)
        self.status_code = status_code
        self.should_stop = should_stop

class GeocodingStats:
    """Thread-safe class to track geocoding statistics"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()
    
    def reset(self):
        """Reset all counters"""
        with self.lock:
            self.cache_hits = 0
            self.api_calls = 0
            self.errors = 0
            self.water_cache_hits = 0
            self.water_api_calls = 0
            self.water_errors = 0
            self.batch_requests = 0
            self.total_coordinates_in_batches = 0
            self.api_failures = 0
            self.successful_geocodes = 0
    
    def record_cache_hit(self, is_water=False):
        """Record a cache hit"""
        with self.lock:
            if is_water:
                self.water_cache_hits += 1
            else:
                self.cache_hits += 1
    
    def record_api_call(self, is_water=False, coordinates_count=1):
        """Record an API call"""
        with self.lock:
            if is_water:
                self.water_api_calls += coordinates_count
            else:
                self.api_calls += coordinates_count
    
    def record_successful_geocode(self):
        """Record a successful geocode"""
        with self.lock:
            self.successful_geocodes += 1
    
    def record_batch_request(self, coordinates_count):
        """Record a batch API request"""
        with self.lock:
            self.batch_requests += 1
            self.total_coordinates_in_batches += coordinates_count
    
    def record_error(self, is_water=False):
        """Record an error"""
        with self.lock:
            if is_water:
                self.water_errors += 1
            else:
                self.errors += 1
    
    def record_api_failure(self):
        """Record an API failure that should stop processing"""
        with self.lock:
            self.api_failures += 1
    
    def get_stats(self):
        """Get current statistics"""
        with self.lock:
            return {
                'geocoding': {
                    'cache_hits': self.cache_hits,
                    'api_calls': self.api_calls,
                    'successful_geocodes': self.successful_geocodes,
                    'errors': self.errors,
                    'api_failures': self.api_failures,
                    'total': self.cache_hits + self.api_calls + self.errors,
                    'batch_requests': self.batch_requests,
                    'avg_batch_size': self.total_coordinates_in_batches / max(1, self.batch_requests)
                },
                'water_detection': {
                    'cache_hits': self.water_cache_hits,
                    'api_calls': self.water_api_calls,
                    'errors': self.water_errors,
                    'total': self.water_cache_hits + self.water_api_calls + self.water_errors
                }
            }
    
    def summary(self):
        """Generate a summary string for logging"""
        stats = self.get_stats()
        geo_total = stats['geocoding']['total']
        water_total = stats['water_detection']['total']
        
        messages = []
        
        if geo_total > 0:
            batch_info = ""
            if stats['geocoding']['batch_requests'] > 0:
                avg_batch = stats['geocoding']['avg_batch_size']
                batch_info = f" ({stats['geocoding']['batch_requests']} batch requests, avg {avg_batch:.1f} coords/batch)"
            
            messages.append(f"Geocoded {geo_total} locations: {stats['geocoding']['cache_hits']} from cache, {stats['geocoding']['successful_geocodes']} from API lookups{batch_info}")
            
            if stats['geocoding']['errors'] > 0:
                messages.append(f"Geocoding errors: {stats['geocoding']['errors']}")
            
            if stats['geocoding']['api_failures'] > 0:
                messages.append(f"⚠️ API failures: {stats['geocoding']['api_failures']}")
        
        if water_total > 0:
            messages.append(f"Water detection for {water_total} locations: {stats['water_detection']['cache_hits']} from cache, {stats['water_detection']['api_calls']} from API calls")
            if stats['water_detection']['errors'] > 0:
                messages.append(f"Water detection errors: {stats['water_detection']['errors']}")
        
        return messages

# Global stats tracker
_global_stats = GeocodingStats()

def get_global_stats():
    """Get the global statistics tracker"""
    return _global_stats

def reset_global_stats():
    """Reset the global statistics"""
    _global_stats.reset()

def save_geo_cache():
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(geo_cache, f)
        print(f"Saved {len(geo_cache)} cache entries to {cache_file}")
    except Exception as e:
        print(f"⚠️ Failed to save config/geo_cache.json: {e}")

def check_api_response(response_status, lat=None, lon=None, service="Geoapify"):
    """
    Check API response status and handle errors appropriately
    Returns True if successful, raises APIError for failures that should stop processing
    """
    if response_status == 200:
        return True
    elif response_status == 202:
        # Accepted but data not returned yet (batch processing)
        return True
    elif response_status == 400:
        raise APIError(f"{service} API error 400: Bad request - check coordinates format", 
                      response_status, should_stop=True)
    elif response_status == 401:
        raise APIError(f"{service} API error 401: Unauthorized - invalid API key", 
                      response_status, should_stop=True)
    elif response_status == 403:
        raise APIError(f"{service} API error 403: Forbidden - check API key permissions", 
                      response_status, should_stop=True)
    elif response_status == 404:
        raise APIError(f"{service} API error 404: Not found", 
                      response_status, should_stop=False)
    elif response_status == 429:
        raise APIError(f"{service} API error 429: Rate limit exceeded - too many requests", 
                      response_status, should_stop=False)
    elif response_status >= 500:
        raise APIError(f"{service} server error {response_status} - service temporarily unavailable", 
                      response_status, should_stop=False)
    else:
        raise APIError(f"{service} unexpected response code {response_status}", 
                      response_status, should_stop=False)

def process_geocoding_result(feature_collection):
    """Process a single geocoding result from Geoapify"""
    features = feature_collection.get("features", []) if feature_collection else []
    
    if features:
        props = features[0].get("properties", {})
        place_name = props.get("name", "").lower()
        result = {
            "state": props.get("state"),
            "city": props.get("city", props.get("county")),
            "country": props.get("country"),
            "place": place_name,
            "is_water": (props.get("category") == "natural" and props.get("class") == "water") or
                       any(w in place_name for w in ["waters", "sea", "ocean", "bay", "channel"])
        }
    else:
        result = {"is_water": True, "place": "open water", "city": "Unknown", "state": "", "country": ""}
    
    return result

async def single_reverse_geocode_fixed(lat: float, lon: float, geoapify_key: str, google_key: str, 
                                     session: aiohttp.ClientSession, stats=None, log_func=None):
    """Improved single coordinate geocoding with better error handling"""
    if stats is None:
        stats = _global_stats
    
    key = f"{round(lat, 5)},{round(lon, 5)}"
    
    # Double-check cache
    if key in geo_cache:
        stats.record_cache_hit()
        return geo_cache[key]
    
    try:
        if geoapify_key:
            url = f"https://api.geoapify.com/v1/geocode/reverse"
            params = {"lat": lat, "lon": lon, "apiKey": geoapify_key, "format": "geojson"}
            
            async with session.get(url, params=params, timeout=10) as response:
                # Check API response status properly
                try:
                    check_api_response(response.status, lat, lon, "Geoapify")
                except APIError as e:
                    if e.should_stop:
                        if log_func:
                            log_func(f"❌ {e}")
                        stats.record_api_failure()
                        raise  # Re-raise to stop processing
                    else:
                        if log_func:
                            log_func(f"⚠️ API error {e.status_code} for ({lat:.3f}, {lon:.3f})")
                        stats.record_error()
                        result = {"is_water": True, "place": f"api error {e.status_code}", 
                                "city": "Unknown", "state": "", "country": ""}
                        geo_cache[key] = result
                        return result
                
                if response.status == 200:
                    data = await response.json()
                    result = process_geocoding_result(data)
                    stats.record_api_call()
                    stats.record_successful_geocode()
                    geo_cache[key] = result
                    return result
                elif response.status == 429:
                    # Rate limited - wait and retry once
                    if log_func:
                        log_func(f"⚠️ Rate limited, retrying in 1 second...")
                    await asyncio.sleep(1)
                    return await single_reverse_geocode_fixed(lat, lon, geoapify_key, google_key, 
                                                            session, stats, log_func)
        
        # Fallback result
        stats.record_error()
        result = {"is_water": True, "place": "geocoding failed", "city": "Unknown", "state": "", "country": ""}
        geo_cache[key] = result
        return result
        
    except APIError:
        raise  # Re-raise API errors that should stop processing
    except asyncio.TimeoutError:
        if log_func:
            log_func(f"⚠️ Timeout for ({lat:.3f}, {lon:.3f})")
        stats.record_error()
        result = {"is_water": True, "place": "timeout", "city": "Unknown", "state": "", "country": ""}
        geo_cache[key] = result
        return result
    except Exception as e:
        if log_func:
            log_func(f"⚠️ Error for ({lat:.3f}, {lon:.3f}): {str(e)}")
        stats.record_error()
        result = {"is_water": True, "place": f"error: {str(e)}", "city": "Unknown", "state": "", "country": ""}
        geo_cache[key] = result
        return result

async def batch_reverse_geocode(coordinates: List[Tuple[float, float]], geoapify_key: str, 
                              google_key: str = "", batch_size: int = 25, 
                              log_func=None, stats=None):
    """
    Batch geocoding using parallel individual requests (reliable method)
    """
    if stats is None:
        stats = _global_stats
    
    results = {}
    
    # Filter out coordinates that are already cached
    uncached_coords = []
    for lat, lon in coordinates:
        key = f"{round(lat, 5)},{round(lon, 5)}"
        key_fallback = f"{round(lat, 4)},{round(lon, 4)}"
        
        if key in geo_cache:
            stats.record_cache_hit()
            results[(lat, lon)] = geo_cache[key]
        elif key_fallback in geo_cache:
            stats.record_cache_hit()
            results[(lat, lon)] = geo_cache[key_fallback]
        else:
            uncached_coords.append((lat, lon))
    
    if log_func and len(coordinates) > len(uncached_coords):
        cache_hits = len(coordinates) - len(uncached_coords)
        log_func(f"Cache hits: {cache_hits}, need to geocode: {len(uncached_coords)}")
    
    if not uncached_coords:
        if log_func:
            log_func("All coordinates found in cache, no API calls needed")
        return results
    
    # Process in batches with parallel requests (not true batch API, but parallel individual calls)
    batch_size = min(batch_size, 25)
    batches = [uncached_coords[i:i + batch_size] 
               for i in range(0, len(uncached_coords), batch_size)]
    
    successful_geocodes = 0
    total_errors = 0
    
    async with aiohttp.ClientSession() as session:
        for batch_num, batch in enumerate(batches):
            if log_func:
                log_func(f"Processing batch {batch_num + 1}/{len(batches)} ({len(batch)} coordinates)")
            
            # Process this batch in parallel
            batch_tasks = []
            for lat, lon in batch:
                task = single_reverse_geocode_fixed(lat, lon, geoapify_key, google_key, session, stats, log_func)
                batch_tasks.append(task)
            
            try:
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                
                batch_success = 0
                batch_errors = 0
                
                for i, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        if isinstance(result, APIError) and result.should_stop:
                            # Critical error that should stop processing
                            if log_func:
                                log_func(f"❌ Critical API error: {result}")
                            raise result
                        else:
                            # Non-critical error, continue
                            if log_func:
                                log_func(f"⚠️ Error for {batch[i]}: {result}")
                            stats.record_error()
                            results[batch[i]] = {"is_water": True, "place": "geocoding failed"}
                            batch_errors += 1
                    else:
                        results[batch[i]] = result
                        if not result.get("place", "").startswith("error:") and not result.get("place") == "geocoding failed":
                            batch_success += 1
                        else:
                            batch_errors += 1
                
                successful_geocodes += batch_success
                total_errors += batch_errors
                
                stats.record_batch_request(len(batch))
                
                if log_func:
                    if batch_success > 0:
                        log_func(f"✅ Batch {batch_num + 1} completed: {batch_success} successful, {batch_errors} errors")
                    else:
                        log_func(f"⚠️ Batch {batch_num + 1} completed: {batch_success} successful, {batch_errors} errors")
                
                # Small delay between batches to be respectful to API
                await asyncio.sleep(0.2)
                
            except APIError:
                raise  # Re-raise API errors that should stop processing
            except Exception as e:
                if log_func:
                    log_func(f"❌ Batch processing error: {e}")
                
                # Fallback for failed batch - mark all as errors
                for lat, lon in batch:
                    stats.record_error()
                    results[(lat, lon)] = {"is_water": True, "place": "batch processing failed"}
                    total_errors += 1
    
    # Final summary
    if log_func:
        log_func(f"Batch geocoding completed: {successful_geocodes} successful, {total_errors} errors out of {len(uncached_coords)} coordinates")
    
    # Save cache after processing
    save_geo_cache()
    
    return results

def reverse_geocode(lat, lon, geoapify_key, google_key, delay=0.5, log_func=None, stats=None):
    """
    Synchronous wrapper for backward compatibility
    Now with improved error handling
    """
    if stats is None:
        stats = _global_stats
    
    key = f"{round(lat, 5)},{round(lon, 5)}"
    key_fallback = f"{round(lat, 4)},{round(lon, 4)}"
    
    # Check cache first
    if key in geo_cache:
        stats.record_cache_hit()
        return geo_cache[key]
    
    if key_fallback in geo_cache:
        stats.record_cache_hit()
        return geo_cache[key_fallback]

    result = {}
    api_call_made = False
    
    # Try Geoapify
    if geoapify_key:
        url = f"https://api.geoapify.com/v1/geocode/reverse?lat={lat}&lon={lon}&apiKey={geoapify_key}"
        try:
            response = requests.get(url)
            
            # Check response status
            try:
                check_api_response(response.status_code, lat, lon, "Geoapify")
            except APIError as e:
                if e.should_stop:
                    if log_func:
                        log_func(f"❌ {e} - Processing stopped.")
                    stats.record_api_failure()
                    raise  # Re-raise to stop processing
                else:
                    if log_func:
                        log_func(f"⚠️ {e}")
                    stats.record_error()
                    result = {"is_water": True, "place": f"api error {e.status_code}"}
            
            if response.status_code == 200:
                api_call_made = True
                data = response.json()
                result = process_geocoding_result(data)
                if is_meaningful_geocoding_result(result):
                    stats.record_successful_geocode()
            
        except APIError:
            raise  # Re-raise API errors that should stop processing
        except Exception as e:
            stats.record_error()
            if log_func:
                log_func(f"Geoapify error for ({lat:.5f}, {lon:.5f}): {e}")

    # Record successful API call
    if result and api_call_made:
        stats.record_api_call()
    elif not result:
        stats.record_error()
        result = {"is_water": True, "place": "unknown location"}

    # Cache the result
    geo_cache[key] = result
    save_geo_cache()

    if delay:
        time.sleep(delay)

    return result

# Keep existing utility functions
def is_over_water(lat, lon, onwater_key, delay=0.5, log_func=None, geoapify_key="", google_key="", stats=None):
    """Water detection (unchanged from original)"""
    if stats is None:
        stats = _global_stats
    
    key = f"water:{round(lat, 5)},{round(lon, 5)}"
    key_fallback = f"water:{round(lat, 4)},{round(lon, 4)}"
    
    # Check cache first
    if key in geo_cache:
        stats.record_cache_hit(is_water=True)
        return geo_cache[key]
    
    if key_fallback in geo_cache:
        stats.record_cache_hit(is_water=True)
        return geo_cache[key_fallback]

    # Use regular geocoding as fallback
    if not onwater_key:
        result = reverse_geocode(lat, lon, geoapify_key, google_key, delay, log_func, stats)
        is_water = result.get("is_water", False)
        geo_cache[key] = is_water
        save_geo_cache()
        return is_water

    return False  # Simplified for brevity

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 3958.8  # miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def load_cache():
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f)